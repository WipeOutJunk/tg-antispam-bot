import asyncio
import logging
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ChatPermissions
)
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.services.spam_words_service import SpamWordsService

from ..config import ML_MODEL_PATH
from ..database import SessionLocal
from ..models.message_log import MessageLog
from ..models.user import User
from ..services.spam_analyzer import SpamAnalyzer
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = Router()
def get_or_create_user(telegram_id, username, chat_id, db):
    """
    Получить пользователя из БД или создать нового если его нет
    """
    try:
        user = db.query(User).filter_by(telegram_id=telegram_id).first()
        
        if not user:
            # Создаем нового пользователя
            user = User(
                telegram_id=telegram_id,
                username=username,
                joined_at=datetime.utcnow(),
                is_admin=False,
                is_banned=False,
                chat_id=chat_id
            )
            db.add(user)
            db.commit()
            logger.info(f"Created new user: {telegram_id} (@{username})")
        else:
            # Обновляем username если изменился
            if user.username != username:
                user.username = username
                db.commit()
                
        return user
    except Exception as e:
        logger.error(f"Error creating/getting user {telegram_id}: {e}")
        db.rollback()
        return None

def get_all_admins():
    """Получить список всех реальных админов (не ботов) из базы данных"""
    with SessionLocal() as db:
        try:
            # Берем всех, кто в БД помечен как админ
            admins = db.query(User).filter(User.is_admin == True).all()

            # Фильтруем ботов: username заканчивается на 'bot' (регистр не важен)
            real_admin_ids = [
                admin.telegram_id
                for admin in admins
                if admin.username and not admin.username.lower().endswith('bot')
            ]

            # Дополнительно отфильтруем тех, у кого нет telegram_id (на всякий случай)
            real_admin_ids = [uid for uid in real_admin_ids if isinstance(uid, int)]

            logger.info(f"get_all_admins: Found {len(admins)} admins in DB")
            logger.info(f"get_all_admins: After filtering bots: {len(real_admin_ids)} real admins")
            if not real_admin_ids:
                logger.warning("get_all_admins: NO REAL ADMINS FOUND!")
            else:
                logger.info(f"get_all_admins: Admin IDs: {real_admin_ids}")

            return real_admin_ids
        except Exception as e:
            logger.error(f"get_all_admins: Error getting admins: {e}")
            return []


@router.message(
    F.content_type.in_(["text", "sticker"]),
    ~(F.content_type == "text") | ~F.text.startswith("/")
)
async def handle_all_messages(message: Message):
    if message.chat.type == "private":
        return

    now = datetime.utcnow()
    content = f"[sticker:{message.sticker.file_id}]" if message.sticker else (message.text or "")
    
    # Добавляем диагностические логи
    logger.info(f"Processing message from user {message.from_user.id} in chat {message.chat.id}")
    logger.info(f"Content type: {message.content_type}, Text length: {len(content)}")

    db = SessionLocal()
    
    try:
        user = get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            chat_id=message.chat.id,
            db=db
        )
    
        if not user:
            logger.error(f"Failed to create/get user {message.from_user.id}")
            return

        # Создаем лог сообщения
        log_entry = MessageLog(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            message_id=message.message_id,
            content=content,
            created_at=now
        )
        db.add(log_entry)
        db.commit()
        
        # 1) Проверка флуда
        logger.debug("Checking for flood...")
        try:
            recent_messages = db.query(MessageLog).filter(
                and_(
                    MessageLog.chat_id == message.chat.id,
                    MessageLog.user_id == message.from_user.id,
                    MessageLog.created_at > now - timedelta(seconds=7)
                )
            ).all()
            
            recent_count = len(recent_messages)
            
            if recent_count >= 3:
                logger.info(f"FLOOD DETECTED: {recent_count} messages in 7 seconds from user {message.from_user.id}")
                
                # Удаляем ВСЕ флудовые сообщения (включая текущее)
                for msg_log in recent_messages:
                    try:
                        await message.bot.delete_message(message.chat.id, msg_log.message_id)
                        logger.debug(f"Deleted flood message {msg_log.message_id}")
                    except Exception as e:
                        logger.debug(f"Could not delete message {msg_log.message_id}: {e}")
                
                try:
                    await message.delete()
                except:
                    pass
                    
                # Мутим пользователя
                mute_until = now + timedelta(minutes=1)
                
                await message.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=mute_until.timestamp()
                )
                
                # Отправляем уведомление в чат
                mention = message.from_user.username or message.from_user.full_name
                await message.bot.send_message(
                    message.chat.id,
                    f"⚠️ {mention} заблокирован на 1 минут за флуд .",
                    parse_mode="HTML"
                )
                
                logger.info(f"User {message.from_user.id} muted 5min for flood, deleted {recent_count} messages")
                 # НОВОЕ: Уведомление админам о флуде
                admin_text = (
                    f"⚡ <b>Обнаружен флуд</b>\n\n"
                    f"Чат: {message.chat.title or message.chat.id}\n"
                    f"Пользователь: @{mention} ({message.from_user.id})\n"
                    f"Количество сообщений: {recent_count} за 20 секунд\n"
                    f"Действие: Мут на 5 минут"
                )
                
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✅ Снять мут",
                        callback_data=f"unmute_flood:{message.chat.id}:{message.from_user.id}"
                    ),
                    InlineKeyboardButton(
                        text="ℹ️ Информация/отклонить",
                        callback_data=f"info_flood:{message.chat.id}:{message.from_user.id}"
                    )
                ]])
                
                try:
                    admin_ids = get_all_admins()
                    if not admin_ids:
                        logger.warning("No admins found - flood notifications will not be sent!")
                    else:
                        logger.info(f"Sending flood alert to {len(admin_ids)} admins")
                        for admin_id in admin_ids:
                            await message.bot.send_message(
                                admin_id, admin_text, parse_mode="HTML", reply_markup=kb
                            )
                            logger.info(f"Flood alert sent to admin {admin_id}")
                except Exception as e:
                    logger.error(f"Error sending flood alert to admins: {e}")
                
                logger.info(f"User {message.from_user.id} muted 5min for flood, deleted {recent_count} messages")
                # Обновляем лог - помечаем все как спам
                for msg_log in recent_messages:
                    msg_log.is_spam = True
                log_entry.is_spam = True
                db.commit()
                
                return
                
        except Exception as e:
            logger.error(f"Error checking flood: {e}")

        # 2) Проверка гомоглифов (только для текста)
        if message.text and len(message.text) > 3:
            logger.debug("Checking for homoglyphs...")
            try:
                # Простая проверка на кириллицу с латиницей
                cyrillic = bool(re.search(r'[а-яё]', message.text.lower()))
                latin = bool(re.search(r'[a-z]', message.text.lower()))
                homoglyphs_detected = cyrillic and latin
                
                if homoglyphs_detected:
                    logger.info(f"HOMOGLYPHS DETECTED in message: {message.text[:50]}...")
                    
                    # Удаляем сообщение и мутим
                    await message.delete()
                    mute_until = now + timedelta(minutes=10)
                    
                    await message.bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=mute_until
                    )
                    
                    # Уведомление в чат
                    mention = message.from_user.username or message.from_user.full_name
                    await message.bot.send_message(
                        message.chat.id,
                        f"⚠️ Сообщение от @{mention} удалено за использование гомоглифов. Мут на 10 минут.",
                        parse_mode="HTML"
                    )
                    
                    # Уведомление админам
                    alert_text = (
                        f"⚠️ <b>Гомоглифы обнаружены</b>\n"
                        f"Чат: {message.chat.title or message.chat.id}\n"
                        f"Пользователь: @{mention}\n\n"
                        f"Сообщение:\n<code>{content[:200]}</code>"
                    )
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✅ Одобрить и восстановить",
                            callback_data=f"approve_homo:{message.chat.id}:{message.message_id}:{message.from_user.id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"reject_homo:{message.chat.id}:{message.message_id}"
                        )
                    ]])
                    
                    try:
                        admin_ids = get_all_admins()
                        if not admin_ids:
                            logger.warning("No admins found - homoglyph notifications will not be sent!")
                        else:
                            logger.info(f"Sending homoglyph alert to {len(admin_ids)} admins")
                            for admin_id in admin_ids:
                                await message.bot.send_message(
                                    admin_id, alert_text, parse_mode="HTML", reply_markup=kb
                                )
                                logger.info(f"Homoglyph alert sent to admin {admin_id}")
                    except Exception as e:
                        logger.error(f"Error sending homoglyph alert to admins: {e}")
                    
                    return
            except Exception as e:
                logger.error(f"Error checking homoglyphs: {e}")

        # 3) Проверка спам-слов (только для текста)
        if message.text:
            logger.debug("Checking for spam words...")
            try:
                spam_svc = SpamWordsService()
                contains_spam, found_word = await spam_svc.check_message_for_spam_words(
                    message.text, message.chat.id, db
                )
                
                if contains_spam:
                    logger.info(f"SPAM WORD DETECTED: '{found_word}' in message from user {message.from_user.id}")
                    
                    # Удаляем сообщение и мутим
                    await message.delete()
                    until = now + timedelta(hours=1)
                    
                    await message.bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until.timestamp()
                    )
                    
                    logger.info(f"User {message.from_user.id} muted 1h for spam word: {found_word}")
                    
                    # Уведомление в чат
                    mention = message.from_user.username or message.from_user.full_name
                    await message.bot.send_message(
                        message.chat.id,
                        f"⚠️ Сообщение от @{mention} удалено за использование запрещенного слова и он не сможет писать 1 час.",
                        parse_mode="HTML"
                    )
                    
                    # Уведомление админам
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
                    
                    admin_text = (
                        f"🚫 <b>Обнаружено спам-слово</b>\n\n"
                        f"Чат: {message.chat.title}\n"
                        f"Пользователь: @{mention}\n"
                        f"Слово: <code>{found_word}</code>\n"
                        f"Текст: <code>{message.text[:200]}</code>"
                    )
                    
                    try:
                        admin_ids = get_all_admins()
                        if not admin_ids:
                            logger.warning("No admins found - spam word notifications will not be sent!")
                        else:
                            logger.info(f"Sending spam word alert to {len(admin_ids)} admins")
                            for admin_id in admin_ids:
                                await message.bot.send_message(
                                    admin_id, admin_text, parse_mode="HTML", reply_markup=kb
                                )
                                logger.info(f"Spam word alert sent to admin {admin_id}")
                    except Exception as e:
                        logger.error(f"Error sending spam word alert to admins: {e}")
                    
                    # Обновляем лог
                    log_entry.is_spam = True
                    db.commit()
                    
                    return  # Прерываем обработку
            except Exception as e:
                logger.error(f"Error handling spam word: {e}")

        # 4) AI Спам-анализ
        logger.debug("Starting AI spam analysis...")
        is_spam = False
        if not message.sticker:
            try:
                svc = SettingsService()
                chat_settings = (
                    await svc.get_chat_settings(message.chat.id, db) or
                    await svc.create_default_settings(
                        message.chat.id, db, title=message.chat.title
                    )
                )
                
                analyzer = SpamAnalyzer(ML_MODEL_PATH)
                raw = await analyzer.analyze_message(message, chat_settings, db)
                is_spam = analyzer.is_spam(raw, chat_settings)
                
                logger.info(f"AI spam analysis result: is_spam={is_spam} for user {message.from_user.id}")
            except Exception as e:
                logger.error(f"Error in AI spam analysis: {e}")

        # 5) Обновляем лог is_spam
        log_entry.is_spam = is_spam
        db.commit()

        if is_spam:
            logger.info(f"AI SPAM DETECTED from user {message.from_user.id}")
            
            # Удаляем сообщение и мутим
            await message.delete()
            until = now + timedelta(hours=3)
            
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until.timestamp()
            )
            
            logger.info(f"User {message.from_user.id} muted 3h for AI spam")
            
            # Уведомление в чат
            mention = message.from_user.username or message.from_user.full_name
            await message.bot.send_message(
                message.chat.id,
                f"⚠️ Сообщение от @{mention} удалено за спам и он не сможет писать 3 часа.",
                parse_mode="HTML"
            )
            
            # Уведомление админам
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
            
            admin_text = (
                f"🔔 <b>AI: Мут пользователя за спам</b>\\n"
                f"Чат: {message.chat.title or message.chat.id}\\n"
                f"Пользователь: {message.from_user.full_name} (@{message.from_user.username})\\n\\n"
                f"Сообщение:\\n<code>{content[:200]}</code>"
            )
            
            try:
                admin_ids = get_all_admins()
                if not admin_ids:
                    logger.warning("No admins found - AI spam notifications will not be sent!")
                else:
                    logger.info(f"Sending AI spam alert to {len(admin_ids)} admins: {admin_ids}")
                    for admin_id in admin_ids:
                        await message.bot.send_message(
                            admin_id, admin_text, parse_mode="HTML", reply_markup=kb
                        )
                        logger.info(f"AI spam alert sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"Error sending AI spam alert to admins: {e}")

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
        
        # Удаляем уведомление админу
        try:
            await cb.message.delete()
        except:
            pass

        if action == "approve_homo":
            user_id = int(parts[3])
            
            # Снимаем мут с пользователя
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            
            # Получаем информацию о сообщении из логов
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(
                    chat_id=chat_id, message_id=msg_id
                ).first()
                
                if log:
                    # Получаем username пользователя
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    
                    # Отправляем сообщение в чат
                    await cb.bot.send_message(
                        chat_id,
                        f"✅ <b>Сообщение одобрено администратором</b>\n"
                        f"👤 @{username} отправил сообщение:\n"
                        f"💬 <i>{log.content[:300]}</i>",
                        parse_mode="HTML"
                    )
                    
            await cb.answer("✅ Сообщение одобрено и пользователь разблокирован")
        else:  # reject_homo
            await cb.answer("❌ Сообщение отклонено")
            
    except Exception as e:
        logger.error(f"Error in homoglyph decision: {e}")
        await cb.answer("❌ Ошибка обработки")

@router.callback_query(F.data.startswith(("approve_spam:", "reject_spam:")))
async def on_spam_word_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        
        # Удаляем уведомление админу
        try:
            await cb.message.delete()
        except:
            pass

        if action == "approve_spam":
            user_id = int(parts[3])
            
            # Снимаем мут с пользователя
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            
            # Получаем информацию о сообщении из логов
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(
                    chat_id=chat_id, message_id=msg_id
                ).first()
                
                if log:
                    # Получаем username пользователя
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    
                    # Отправляем сообщение в чат
                    await cb.bot.send_message(
                        chat_id,
                        f"✅ <b>Сообщение одобрено администратором</b>\n"
                        f"👤 @{username} отправил сообщение:\n"
                        f"💬 <i>{log.content[:300]}</i>",
                        parse_mode="HTML"
                    )
                    
            await cb.answer("✅ Сообщение одобрено и пользователь разблокирован")
        else:  # reject_spam
            await cb.answer("❌ Сообщение отклонено")
            
    except Exception as e:
        logger.error(f"Error in spam word decision: {e}")
        await cb.answer("❌ Ошибка обработки")

@router.callback_query(F.data.startswith(("approve_ai:", "reject_ai:")))
async def on_ai_spam_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 4)
        action = parts[0]
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        
        # Удаляем уведомление админу
        try:
            await cb.message.delete()
        except:
            pass

        if action == "approve_ai":
            user_id = int(parts[3])
            
            # Снимаем мут с пользователя
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            
            # Получаем информацию о сообщении из логов
            with SessionLocal() as db:
                log = db.query(MessageLog).filter_by(
                    chat_id=chat_id, message_id=msg_id
                ).first()
                
                if log:
                    # Получаем username пользователя
                    user = db.query(User).filter_by(telegram_id=user_id).first()
                    username = user.username if user and user.username else f"ID{user_id}"
                    
                    # Отправляем сообщение в чат
                    await cb.bot.send_message(
                        chat_id,
                        f"✅ <b>Сообщение одобрено администратором</b>\n"
                        f"👤 @{username} отправил сообщение:\n"
                        f"💬 <i>{log.content[:300]}</i>",
                        parse_mode="HTML"
                    )
                    
            await cb.answer("✅ Сообщение одобрено и пользователь разблокирован")
        else:  # reject_ai
            await cb.answer("❌ Сообщение отклонено")
            
    except Exception as e:
        logger.error(f"Error in AI spam decision: {e}")
        await cb.answer("❌ Ошибка обработки")
@router.callback_query(F.data.startswith(("unmute_flood:", "info_flood:")))
async def on_flood_decision(cb: CallbackQuery):
    try:
        parts = cb.data.split(":", 3)
        action = parts[0]
        chat_id = int(parts[1])
        user_id = int(parts[2])
        
        # Удаляем уведомление админу
        try:
            await cb.message.delete()
        except:
            pass

        if action == "unmute_flood":
            # Снимаем мут с пользователя
            await cb.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            
            # Уведомляем в чат
            await cb.bot.send_message(
                chat_id,
                f"✅ Мут с пользователя {user_id} снят администратором.",
                parse_mode="HTML"
            )
            
            await cb.answer("✅ Мут за флуд снят")
            
        else:  # info_flood
            await cb.answer("ℹ️ Флуд: 3+ сообщений за 20 секунд", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error in flood decision: {e}")
        await cb.answer("❌ Ошибка обработки")