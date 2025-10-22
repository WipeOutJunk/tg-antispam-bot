import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.services.spam_words_service import SpamWordsService
from ..config import ML_MODEL_PATH
from ..database import SessionLocal
from ..models.message_log import MessageLog
from ..models.user import User
from ..services.spam_analyzer import SpamAnalyzer
from ..services.settings_service import SettingsService
from ..services.homoglyph_detector import HomoglyphDetector

from .admin_panel import pending_spam_word, pending_sensitivity, pending_spam_link

logger = logging.getLogger(__name__)
router = Router()

def create_mute_until(minutes=0, hours=0, days=0):
    from datetime import timezone
    now = datetime.now(timezone.utc)
    until = now + timedelta(minutes=minutes, hours=hours, days=days)
    if until - now < timedelta(seconds=30):
        logger.error(f"Mute time too close or in past: {until}, now: {now}")
        until = now + timedelta(minutes=1)
    return until

def get_all_admins():
    return SettingsService.get_all_admins()

async def send_notifications_to_admins_with_sync(
    bot,
    admin_text: str,
    kb: InlineKeyboardMarkup,
    original_chat_id: int,
    original_message_id: int,
    event_type: str,
    event_data: dict = None
) -> int:
    """Отправляет уведомления всем админам с сохранением в БД для синхронизации"""
    try:
        try:
            from ..models.admin_notification import AdminNotification, AdminNotificationMessage
            from ..services.admin_notifications_service import AdminNotificationsService
            use_sync = True
        except ImportError:
            logger.warning("Admin notifications sync not available - using old method")
            use_sync = False

        admin_ids = get_all_admins()
        if not admin_ids:
            logger.warning(f"No admins found - {event_type} notifications will not be sent!")
            return None

        notification_id = None
        if use_sync:
            with SessionLocal() as db:
                notification = await AdminNotificationsService.create_admin_notification(
                    db=db,
                    original_chat_id=original_chat_id,
                    original_message_id=original_message_id,
                    event_type=event_type,
                    event_data=event_data
                )
                notification_id = notification.id

        logger.info(f"Sending {event_type} alert to {len(admin_ids)} admins")

        for admin_id in admin_ids:
            try:
                sent_message = await bot.send_message(
                    admin_id, admin_text, parse_mode="HTML", reply_markup=kb
                )
                if use_sync and notification_id:
                    with SessionLocal() as db:
                        await AdminNotificationsService.add_admin_message(
                            db=db,
                            notification_id=notification_id,
                            admin_id=admin_id,
                            message_id=sent_message.message_id
                        )
                logger.info(f"{event_type} alert sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to send {event_type} alert to admin {admin_id}: {e}")

        return notification_id

    except Exception as e:
        logger.error(f"Error sending {event_type} alert to admins: {e}")
        return None

async def delete_admin_notifications(
    bot,
    original_chat_id: int,
    original_message_id: int,
    event_type: str,
    processed_by: int
):
    """Удаляет уведомления у всех админов после обработки одним из них"""
    try:
        from ..models.admin_notification import AdminNotification, AdminNotificationMessage
        from ..services.admin_notifications_service import AdminNotificationsService

        with SessionLocal() as db:
            notification = await AdminNotificationsService.process_notification(
                db=db,
                original_chat_id=original_chat_id,
                original_message_id=original_message_id,
                event_type=event_type,
                processed_by=processed_by
            )

            if notification:
                other_admin_messages = await AdminNotificationsService.get_undeleted_messages(
                    db=db,
                    notification_id=notification.id,
                    exclude_admin_id=processed_by
                )
                for admin_msg in other_admin_messages:
                    try:
                        await bot.delete_message(
                            chat_id=admin_msg.chat_id,
                            message_id=admin_msg.message_id
                        )
                        logger.info(f"Deleted {event_type} notification message {admin_msg.message_id} for admin {admin_msg.admin_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete message {admin_msg.message_id} for admin {admin_msg.admin_id}: {e}")

                if other_admin_messages:
                    await AdminNotificationsService.mark_messages_as_deleted(
                        db=db,
                        message_ids=[msg.id for msg in other_admin_messages]
                    )
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Error deleting admin notifications: {e}")

# ГЛАВНОЕ: декоратор для регистрации обработчика сообщений
@router.message()
async def handle_all_messages(message: Message):
    chat_id = message.chat.id
    bot_id = message.bot.id

    ## Проверка покинул ли бот группу 
    try:
        bot_member = await message.bot.get_chat_member(chat_id, bot_id)
        if bot_member.status in ["left", "kicked"]:
            logger.info(f"Ignoring message from chat {chat_id}: bot status {bot_member.status}")
            return  
    except Exception as e:
        logger.warning(f"Could not check bot status in chat {chat_id}: {e}")
        return
    
    if message.chat.type == "private":
            user_id = message.from_user.id
            # Проверяем, ждет ли админ-панель ввода от этого пользователя
            if user_id in pending_spam_word or user_id in pending_sensitivity or user_id in pending_spam_link:
                logger.info(f"Skipping message from user {user_id} - waiting for admin panel input")
                return
            if message.from_user.is_bot:
                return
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        if message.from_user.is_bot:
            return

        try:
            admin_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
            # if admin_member.status in ['administrator', 'creator']:
            #     logger.debug(f"Skipping message from admin: {message.from_user.id}")
            #     return
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")

        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                joined_at=now,
                chat_id=message.chat.id
            )
            db.add(user)
            db.commit()

        content = ""
        if message.text:
            content = message.text
        elif message.caption:
            content = message.caption

        log_entry = MessageLog(
            chat_id=message.chat.id,
            user_id=user.id,
            message_id=message.message_id,
            content=content,
            is_spam=False,
            created_at=now
        )
        db.add(log_entry)
        db.commit()

        # 1) Анти-флуд
        # recent_messages = db.query(MessageLog).filter_by(
        #     chat_id=message.chat.id,
        #     user_id=user.id
        # ).filter(
        #     MessageLog.created_at >= now - timedelta(seconds=5)
        # ).count()

        # if recent_messages > 4:
        #     logger.info(f"FLOOD DETECTED from user {message.from_user.id}: {recent_messages} messages in 5s")
            
        #     try:
        #         recent_msg_logs = db.query(MessageLog).filter_by(
        #             chat_id=message.chat.id,
        #             user_id=user.id
        #         ).filter(
        #             MessageLog.created_at >= now - timedelta(seconds=5)
        #         ).all()

        #         for msg_log in recent_msg_logs:
        #             try:
        #                 await message.bot.delete_message(message.chat.id, msg_log.message_id)
        #             except:
        #                 pass

        #         until = create_mute_until(hours=3)
        #         await message.bot.restrict_chat_member(
        #             chat_id=message.chat.id,
        #             user_id=message.from_user.id,
        #             permissions=ChatPermissions(can_send_messages=False),
        #             until_date=until
        #         )

        #         logger.info(f"User {message.from_user.id} muted for 3 hours due to flood")

        #         mention = message.from_user.username or message.from_user.full_name
        #         try:
        #             await message.bot.send_message(
        #                 message.chat.id,
        #                 f"⚠️ @{mention} заблокирован на 3 часа за флуд ({recent_messages} сообщений за 5 секунд).",
        #                 parse_mode="HTML"
        #             )
        #         except:
        #             pass

        #         kb = InlineKeyboardMarkup(inline_keyboard=[[
        #             InlineKeyboardButton(
        #                 text="🔓 Размутить",
        #                 callback_data=f"unmute_flood:{message.chat.id}:{message.message_id}:{message.from_user.id}"
        #             ),
        #             InlineKeyboardButton(
        #                 text="ℹ️ Инфо",
        #                 callback_data=f"info_flood:{message.chat.id}:{message.message_id}"
        #             )
        #         ]])

        #         admin_text = (
        #             f"🚨 <b>ФЛУД ДЕТЕКТЕД</b>\n\n"
        #             f"👤 Пользователь: {message.from_user.full_name}\n"
        #             f"🆔 ID: <code>{message.from_user.id}</code>\n"
        #             f"📊 Сообщений за 5 сек: <b>{recent_messages}</b>\n"
        #             f"🔇 Замучен на 3 часа"
        #         )

        #         await send_notifications_to_admins_with_sync(
        #             bot=message.bot,
        #             admin_text=admin_text,
        #             kb=kb,
        #             original_chat_id=message.chat.id,
        #             original_message_id=message.message_id,
        #             event_type="flood",
        #             event_data={"user_id": message.from_user.id, "message_count": recent_messages}
        #         )
        #         return

        #     except Exception as e:
        #         logger.error(f"Error handling flood: {e}")

        # 3) Спам-слова
        if message.text:
            logger.debug("Checking for spam words...")
            try:
                spam_svc = SpamWordsService()
                contains_spam, found_word = await spam_svc.check_message_for_spam_words(
                    message.text, message.chat.id, db
                )
                # Проверка на матерные слова
                contains_profanity, found_profanity_word = await spam_svc.check_message_for_profanity(
                      message.text, db )
                
                if contains_spam or contains_profanity:
                    detected_word = found_word or found_profanity_word
                    logger.info(f"SPAM WORD DETECTED: '{detected_word}' in message from user {message.from_user.id}")

                    await message.delete()
                    until = now + timedelta(minutes=5)
                    await message.bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until.timestamp()
                    )

                    logger.info(f"User {message.from_user.id} muted 5min for spam word: {found_word}")

                    mention = message.from_user.username or message.from_user.full_name
                    # await message.bot.send_message(
                    #     message.chat.id,
                    #     f"⚠️ Сообщение от @{mention} удалено за использование запрещенного слова и он не сможет писать 1 час.",
                    #     parse_mode="HTML"
                    # )

                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✅ Одобрить сообщение",
                            callback_data=f"approve_spam:{message.chat.id}:{message.message_id}:{message.from_user.id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"reject_spam:{message.chat.id}:{message.message_id}"
                        )
                    ]])

                       # Получаем информацию о пользователе
                    username = f"@{message.from_user.username}" if message.from_user.username else "без username"
                    user_id = message.from_user.id
                    full_name = message.from_user.full_name

                    # Форматируем текст сообщения для отображения
                    msg_preview = message.text[:200] if len(message.text) <= 200 else message.text[:197] + "..."

                    admin_text = (
                        f"🚫 <b>ОБНАРУЖЕНО СПАМ-СЛОВО</b>"
                        f"👤 <b>Пользователь:</b> {full_name}"
                        f"🔑 <b>Username:</b> {username}"
                        f"🆔 <b>ID:</b> <code>{user_id}</code>"
                        f"💬 <b>Чат ID:</b> <code>{message.chat.id}</code>"
                        f"🔍 <b>Найденное слово:</b> <code>{detected_word}</code>"
                        f"⏱ <b>Время мута:</b> 5 минут"
                        f"📝 <b>Текст сообщения:</b>"
                        f"<code>{msg_preview}</code>"
                    )

                    await send_notifications_to_admins_with_sync(
                        bot=message.bot,
                        admin_text=admin_text,
                        kb=kb,
                        original_chat_id=message.chat.id,
                        original_message_id=message.message_id,
                        event_type="spam",
                        event_data={
                            "found_word": found_word,
                            "user_id": message.from_user.id,
                            "content": message.text[:200]
                        }
                    )

                    log_entry.is_spam = True
                    db.commit()
                    return

            except Exception as e:
                logger.error(f"Error handling spam word: {e}")

        # 4) AI-спам
        logger.debug("Starting AI spam analysis...")
        is_spam = False
        if not message.sticker:
            try:
                svc = SettingsService()
                chat_settings = (
                    await svc.get_chat_settings(message.chat.id, db) or
                    await svc.create_default_settings(message.chat.id, db, title=message.chat.title)
                )

                analyzer = SpamAnalyzer(ML_MODEL_PATH)
                raw = await analyzer.analyze_message(message, chat_settings, db)
                is_spam = analyzer.is_spam(raw, chat_settings)
                logger.info(f"AI spam analysis result: is_spam={is_spam} for user {message.from_user.id}")

            except Exception as e:
                logger.error(f"Error in AI spam analysis: {e}")

        log_entry.is_spam = is_spam
        db.commit()

        if is_spam:
            logger.info(f"AI SPAM DETECTED from user {message.from_user.id}")

            await message.delete()
            until = now + timedelta(minutes=5)
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until.timestamp()
            )

            logger.info(f"User {message.from_user.id} muted 5min for AI spam")

            mention = message.from_user.username or message.from_user.full_name
            # await message.bot.send_message(
            #     message.chat.id,
            #     f"⚠️ Сообщение от @{mention} удалено за спам и он не сможет писать 5 минут.",
            #     parse_mode="HTML"
            # )

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Одобрить сообщение",
                    callback_data=f"approve_ai:{message.chat.id}:{message.message_id}:{message.from_user.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_ai:{message.chat.id}:{message.message_id}"
                )
            ]])
            username = f"@{message.from_user.username}" if message.from_user.username else "без username"
            user_id = message.from_user.id
            full_name = message.from_user.full_name
            # Форматируем текст сообщения для отображения
            msg_preview = message.text[:200] if len(message.text) <= 200 else message.text[:197] + "..."
            
            admin_text = (
                f"🔔 <b>AI СПАМ</b>\n\n"
                f"👤 <b>Пользователь:</b> {full_name}\n"
                f"🔑 <b>Username:</b> {username}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"💬 <b>Чат ID:</b> <code>{message.chat.id}</code>\n"
                f"📝 <b>Текст сообщения:</b>\n"
                f" <code>{content[:200]}</code>"
            )

            await send_notifications_to_admins_with_sync(
                bot=message.bot,
                admin_text=admin_text,
                kb=kb,
                original_chat_id=message.chat.id,
                original_message_id=message.message_id,
                event_type="ai",
                event_data={"user_id": message.from_user.id, "content": content[:200]}
            )

    except Exception as e:
        logger.error(f"Error in handle_all_messages: {e}")
    finally:
        db.close()

@router.callback_query(F.data.startswith(("approve_homo:", "reject_homo:")))
async def on_homoglyph_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])

        try:
            await cb.message.delete()
        except:
            pass

        await delete_admin_notifications(
            bot=cb.bot,
            original_chat_id=chat_id,
            original_message_id=msg_id,
            event_type="homoglyph",
            processed_by=cb.from_user.id
        )

        if action == "approve_homo":
            user_id = int(parts[3])
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(chat_id=chat_id, message_id=msg_id).first()
                if log:
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    # await cb.bot.send_message(
                    #     chat_id,
                    #     f"✅ Сообщение от @{username} восстановлено администратором.",
                    #     parse_mode="HTML"
                    # )
        await cb.answer()
    except Exception as e:
        logger.error(f"Error in homoglyph decision: {e}")
        await cb.answer()

@router.callback_query(F.data.startswith(("approve_spam:", "reject_spam:")))
async def on_spam_word_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])

        try:
            await cb.message.delete()
        except:
            pass

        await delete_admin_notifications(
            bot=cb.bot,
            original_chat_id=chat_id,
            original_message_id=msg_id,
            event_type="spam",
            processed_by=cb.from_user.id
        )

        if action == "approve_spam":
            user_id = int(parts[3])
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(chat_id=chat_id, message_id=msg_id).first()
                if log:
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    # await cb.bot.send_message(
                    #     chat_id,
                    #     f"✅ Сообщение от @{username} восстановлено администратором.",
                    #     parse_mode="HTML"
                    # )
        await cb.answer()
    except Exception as e:
        logger.error(f"Error in spam word decision: {e}")
        await cb.answer()

@router.callback_query(F.data.startswith(("approve_ai:", "reject_ai:")))
async def on_ai_spam_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])

        try:
            await cb.message.delete()
        except:
            pass

        await delete_admin_notifications(
            bot=cb.bot,
            original_chat_id=chat_id,
            original_message_id=msg_id,
            event_type="ai",
            processed_by=cb.from_user.id
        )

        if action == "approve_ai":
            user_id = int(parts[3])
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(chat_id=chat_id, message_id=msg_id).first()
                if log:
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    # await cb.bot.send_message(
                    #     chat_id,
                    #     f"✅ Сообщение от @{username} восстановлено администратором.",
                    #     parse_mode="HTML"
                    # )
        await cb.answer()
    except Exception as e:
        logger.error(f"Error in AI spam decision: {e}")
        await cb.answer()

@router.callback_query(F.data.startswith(("unmute_flood:", "info_flood:")))
async def on_flood_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])

        try:
            await cb.message.delete()
        except:
            pass

        await delete_admin_notifications(
            bot=cb.bot,
            original_chat_id=chat_id,
            original_message_id=msg_id,
            event_type="flood",
            processed_by=cb.from_user.id
        )

        if action == "unmute_flood":
            user_id = int(parts[3])
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            with SessionLocal() as db:
                user = db.query(User).filter_by(telegram_id=user_id).first()
                username = user.username if user and user.username else f"ID{user_id}"
                # await cb.bot.send_message(
                #     chat_id,
                #     f"✅ @{username} разблокирован администратором.",
                #     parse_mode="HTML"
                # )
        await cb.answer()
    except Exception as e:
        logger.error(f"Error in flood decision: {e}")
        await cb.answer()

# Экспортируем роутер для подключения в bot.py
message_router = router