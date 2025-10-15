import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from sqlalchemy.orm import Session

from ..config import ADMIN_IDS, ML_MODEL_PATH
from ..database import SessionLocal
from ..models.message_log import MessageLog
from ..services.spam_analyzer import SpamAnalyzer
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = Router()


def process_spam_results(spam_results) -> dict:
    reasons, max_conf = [], 0.0
    if isinstance(spam_results, list):
        for r in spam_results:
            reasons.append(getattr(r, "reason", getattr(r, "label", "Неизвестно")))
            max_conf = max(max_conf, getattr(r, "confidence", getattr(r, "score", 0.0)))
    elif isinstance(spam_results, dict):
        reasons = spam_results.get("reasons", ["Неизвестно"])
        max_conf = spam_results.get("confidence", 0.0)
    else:
        reasons = ["Неизвестно"]
    return {"reasons": reasons, "confidence": max_conf}


@router.message(F.text, ~F.text.startswith("/"))
async def handle_all_messages(message: Message):
    if message.chat.type == "private":
        return

    with SessionLocal() as db:
        try:
            svc_set = SettingsService()
            chat_settings = await svc_set.get_chat_settings(message.chat.id, db) \
                             or await svc_set.create_default_settings(
                                 message.chat.id, db, title=message.chat.title
                             )

            spam = SpamAnalyzer(ML_MODEL_PATH)
            raw = await spam.analyze_message(message, chat_settings, db)
            is_spam = spam.is_spam(raw, chat_settings)

            log = MessageLog(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                message_id=message.message_id,
                content=message.text or "",
                is_spam=is_spam,
                created_at=datetime.utcnow()
            )
            db.add(log)
            db.commit()

            if not is_spam:
                return

            # Удаляем спам и мутим на 3 часа
            await message.delete()
            until = datetime.utcnow() + timedelta(hours=3)
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            logger.info(f"User {message.from_user.id} muted until {until}")

            # Уведомление в общем чате
            mention = message.from_user.username or message.from_user.full_name
            await message.bot.send_message(
                message.chat.id,
                f"Сообщение от <a href='tg://user?id={message.from_user.id}'>{mention}</a> удалено за спам и он не сможет писать 3 ч.",
                parse_mode="HTML"
            )

            # Кнопки для админов
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Восстановить и снять мут",
                    callback_data=f"restore:{message.chat.id}:{message.message_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{message.chat.id}:{message.message_id}"
                )
            ]])

            admin_text = (
                f"🔔 <b>Мут пользователя</b>\n"
                f"Чат: {chat_settings.title or message.chat.id}\n"
                f"Пользователь: {message.from_user.full_name}"
                f" (@{message.from_user.username})\n\n"
                f"Сообщение:\n<code>{(message.text or '')[:200]}</code>"
            )

            for admin in ADMIN_IDS:
                await message.bot.send_message(admin, admin_text, parse_mode="HTML", reply_markup=kb)

        except Exception as e:
            logger.error(f"Ошибка handle_all_messages: {e}")


@router.callback_query(F.data.startswith(("restore:", "reject:")))
async def on_admin_decision(cb: CallbackQuery):
    action, chat_id, msg_id = cb.data.split(":", 2)
    chat_id, msg_id = int(chat_id), int(msg_id)

    try:
        await cb.message.delete()
    except:
        pass

    if action == "restore":
        with SessionLocal() as db:
            log = db.query(MessageLog).filter_by(
                chat_id=chat_id, message_id=msg_id
            ).first()

        if log:
            # Снимаем мут
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=log.user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            # Получаем username
            member = await cb.bot.get_chat_member(chat_id, log.user_id)
            user = member.user
            username = f"@{user.username}" if user.username else user.full_name

            # Отправляем одним сообщением
            text = (
                f"💬 Восстановлено сообщение от пользователя {username}:\n\n"
                f"{log.content}"
            )
            await cb.bot.send_message(chat_id, text)

    await cb.answer("✅ Обработано")
