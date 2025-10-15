import asyncio
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..config import ADMIN_IDS, ML_MODEL_PATH
from ..database import SessionLocal
from ..models.message_log import MessageLog
from ..services.spam_analyzer import SpamAnalyzer
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = Router()


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@router.message(
    F.content_type.in_(["text", "sticker"]),
    ~(F.content_type == "text") | ~F.text.startswith("/")
)
async def handle_all_messages(message: Message):
    if message.chat.type == "private":
        return

    now = datetime.utcnow()
    # Для стикера сохраняем file_id, для текста — сам текст
    if message.sticker:
        content = f"[sticker:{message.sticker.file_id}]"
    else:
        content = message.text or ""

    with SessionLocal() as db:
        try:
            # 1) Логируем сообщение/стикер
            log_entry = MessageLog(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                message_id=message.message_id,
                content=content,
                is_spam=False,
                created_at=now
            )
            db.add(log_entry)
            db.commit()

            # 2) Флуд-детекция: сообщения за последние 30 секунд
            window_start = now - timedelta(seconds=45)
            recent = (
                db.query(MessageLog)
                  .filter(
                      MessageLog.chat_id == message.chat.id,
                      MessageLog.user_id == message.from_user.id,
                      MessageLog.created_at >= window_start
                  )
                  .all()
            )
            dup_ids = [
                log.message_id
                for log in recent
                if text_similarity(content, log.content) >= 0.95
            ]
            if len(dup_ids) >= 3:
                # удаляем флуд-сообщения
                for msg_id in dup_ids:
                    try:
                        await message.bot.delete_message(message.chat.id, msg_id)
                    except:
                        pass
                # мутим на 1 минут
                mute_until = now + timedelta(minutes=1)
                await message.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=mute_until
                )
                logger.info(f"User {message.from_user.id} muted 5m for flood ({len(dup_ids)} msgs)")
                return

            # 3) Спам-анализ только для текстовых
            is_spam = False
            if not message.sticker:
                svc = SettingsService()
                chat_settings = await svc.get_chat_settings(message.chat.id, db) \
                    or await svc.create_default_settings(
                        message.chat.id, db, title=message.chat.title
                    )
                analyzer = SpamAnalyzer(ML_MODEL_PATH)
                raw = await analyzer.analyze_message(message, chat_settings, db)
                is_spam = analyzer.is_spam(raw, chat_settings)

            # 4) Обновляем is_spam
            log_entry.is_spam = is_spam
            db.commit()

            if is_spam:
                # удаляем спам и мутим на 3 часа
                await message.delete()
                until = now + timedelta(hours=3)
                await message.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                logger.info(f"User {message.from_user.id} muted 3h for spam")

                # уведомление и кнопки для админов
                mention = message.from_user.username or message.from_user.full_name
                await message.bot.send_message(
                    message.chat.id,
                    f"Сообщение от <a href='tg://user?id={message.from_user.id}'>{mention}</a> удалено за спам и он не сможет писать 3 ч.",
                    parse_mode="HTML"
                )
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
                    f"Сообщение:\n<code>{content[:200]}</code>"
                )
                for admin in ADMIN_IDS:
                    await message.bot.send_message(
                        admin, admin_text, parse_mode="HTML", reply_markup=kb
                    )

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
            # снимаем мут
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
            member = await cb.bot.get_chat_member(chat_id, log.user_id)
            user = member.user
            username = f"@{user.username}" if user.username else user.full_name
            text = (
                f"💬 Восстановлено сообщение от пользователя {username}:\n\n"
                f"{log.content}"
            )
            await cb.bot.send_message(chat_id, text)

    await cb.answer("✅ Обработано")
