import asyncio
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import Session

from ..config import ADMIN_IDS, ML_MODEL_PATH
from ..database import SessionLocal
from ..models.message_log import MessageLog
from ..services.spam_analyzer import SpamAnalyzer
from ..services.moderation_service import ModerationService
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
            # Настройки чата
            svc_set = SettingsService()
            chat_settings = await svc_set.get_chat_settings(message.chat.id, db) \
                             or await svc_set.create_default_settings(message.chat.id, db, title=message.chat.title)
            # Спам-анализ
            analyzer = SpamAnalyzer(ML_MODEL_PATH)
            raw = await analyzer.analyze_message(message, chat_settings, db)
            is_spam = analyzer.is_spam(raw, chat_settings)
            # Лог
            msg_log = MessageLog(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                message_id=message.message_id,
                content=message.text or "",
                is_spam=is_spam,
                created_at=datetime.now()
            )
            db.add(msg_log); db.commit()
            if not is_spam:
                return
            # Удаляем спам
            await message.delete()
            processed = process_spam_results(raw)
            # Уведомляем в чат
            user_mention = message.from_user.username or message.from_user.full_name
            await message.bot.send_message(
                message.chat.id,
                f"Сообщение пользователя <a href=\"tg://user?id={message.from_user.id}\">{user_mention}</a> удалено по подозрению в спаме",
                parse_mode="HTML"
            )
            # Кнопки для админов
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✅ Одобрить",
                        callback_data=f"approve:{message.chat.id}:{message.message_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"reject:{message.chat.id}:{message.message_id}"
                    )
                ]]
            )
            text = (
                f"🔔 <b>Восстановление</b>\n"
                f"Чат: {message.chat.title or message.chat.id}\n"
                f"Пользователь: {message.from_user.full_name} "
                f"(@{message.from_user.username}) [ID: {message.from_user.id}]\n\n"
                f"Сообщение:\n<code>{(message.text or '')[:200]}</code>"
            )
            for admin in ADMIN_IDS:
                await message.bot.send_message(admin, text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logger.error(f"Ошибка в handle_all_messages: {e}")



@router.callback_query(F.data.startswith(("approve:", "reject:")))
async def on_admin_decision(cb: CallbackQuery):
    action, chat_id, msg_id = cb.data.split(":", 2)
    chat_id, msg_id = int(chat_id), int(msg_id)

    # Удаляем уведомление админу
    try:
        await cb.message.delete()
    except Exception:
        pass

    if action == "approve":
        with SessionLocal() as db:
            log = db.query(MessageLog).filter_by(
                chat_id=chat_id, message_id=msg_id
            ).first()

        if log:
            # Получаем данные пользователя из Telegram
            try:
                member = await cb.bot.get_chat_member(chat_id, log.user_id)
                user = member.user
                user_display = user.username and f"@{user.username}" or user.full_name
            except Exception:
                # fallback на ID если запрос не удался
                user_display = f"ID {log.user_id}"

            timestamp = log.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = log.content

            await cb.bot.send_message(
                chat_id,
                (
                    f"💬 Восстановлено сообщение от {user_display} "
                    f"({timestamp}):\n\n{content}"
                ),
                parse_mode="HTML"
            )

    await cb.answer("✅ Готово")
