# app/handlers/chat_events.py

import logging
import asyncio
import os
from datetime import datetime
from aiogram import Router, F
from aiogram.types import ChatMemberUpdated, Message
from aiogram.filters import ChatMemberUpdatedFilter, Command
from ..database import SessionLocal
from ..models.chat import Chat
from ..models.user import User
from ..models.allowed_adder import AllowedAdder


logger = logging.getLogger(__name__)
router = Router()


# Словарь для отслеживания ожидания активации: user_id -> {"chat_id": int, "waiting_for_code": bool, "activated": bool}
pending_activations = {}


# Получаем секретное слово из переменных окружения
SECRET_ACTIVATION_WORD = os.getenv("SECRET_ACTIVATION_WORD", "default_secret_word")



@router.my_chat_member()
async def bot_added_removed(event: ChatMemberUpdated):
    """Обработка добавления/удаления бота с проверкой whitelist"""
    print("CHAT_EVENTS MODULE LOADED")
    
    bot_user = await event.bot.get_me()
    if event.new_chat_member.user.id != bot_user.id:
        return
    
    chat_id = event.chat.id
    logger.info(f"BOT STATUS CHANGE: {event.old_chat_member.status} -> {event.new_chat_member.status} in {chat_id}")
    
    if event.new_chat_member.status in ("member", "administrator"):
        # Бот добавлен - проверяем whitelist
        adder_id = event.from_user.id  # ID пользователя, который добавил бота
        
        with SessionLocal() as db:
            # Проверяем, есть ли пользователь в whitelist
            allowed = db.query(AllowedAdder).filter_by(telegram_id=adder_id).first()
            
            if not allowed:
                # Пользователь не в whitelist - запускаем процесс активации
                logger.warning(f"User {adder_id} is not in whitelist. Starting activation process for chat {chat_id}")
                
                pending_activations[adder_id] = {
                    "chat_id": chat_id,
                    "waiting_for_code": False,
                    "activated": False
                }
                
                # Отправляем сообщение в личку пользователю
                try:
                    await event.bot.send_message(
                        adder_id,
                        f"⚠️ Для активации бота в чате используйте команду /activate\n"
                        f"У вас есть 2 минуты для активации, иначе бот покинет чат."
                    )
                    logger.info(f"Activation request sent to user {adder_id} in private chat")
                except Exception as e:
                    logger.error(f"Failed to send activation message to user {adder_id}: {e}")
                    # Если не удалось отправить в личку, отправляем в группу
                    await event.bot.send_message(
                        chat_id,
                        "⚠️ Для активации бота напишите мне в личные сообщения (@{}) и используйте команду /activate\n"
                        "У вас есть 2 минуты для активации, иначе бот покинет чат.".format(bot_user.username)
                    )
                
                # Запускаем таймер на выход из чата (2 минуты)
                asyncio.create_task(check_activation_timeout(event.bot, chat_id, adder_id, timeout=120))
                return
            else:
                logger.info(f"User {adder_id} is in whitelist. Bot activated for chat {chat_id}")
        
        # Если пользователь в whitelist или активация прошла - создаём чат и админов
        await create_chat_and_admins(event.bot, chat_id, event.chat.title or "")
    
    elif event.new_chat_member.status == "left":
        # Бот удалён - удаляем всё
        with SessionLocal() as db:
            db.query(Chat).filter(Chat.id == chat_id).delete()
            db.commit()
            logger.info(f"CHAT {chat_id} DELETED")
        
        # Удаляем из pending_activations если есть (ищем по chat_id)
        for user_id, data in list(pending_activations.items()):
            if data.get("chat_id") == chat_id:
                pending_activations.pop(user_id, None)


async def create_chat_and_admins(bot, chat_id: int, chat_title: str = ""):
    with SessionLocal() as db:
        # 1. Создаём чат
        if not db.query(Chat).filter_by(id=chat_id).first():
            db.add(Chat(id=chat_id, title=chat_title, sensitivity=5, warn_limit=3))
            db.commit()

        # 2. Получаем админов и создаём или обновляем пользователей
        bot_user = await bot.get_me()
        admins = await bot.get_chat_administrators(chat_id=chat_id)

        for admin in admins:
            user_id = admin.user.id
            if user_id == bot_user.id:
                continue

            is_admin_status = admin.status in ("creator", "administrator")
            existing = db.query(User).filter_by(
                telegram_id=user_id, chat_id=chat_id
            ).first()

            if existing:
                # Обновляем флаг is_admin
                if existing.is_admin != is_admin_status:
                    existing.is_admin = is_admin_status
                    existing.username = admin.user.username or ""
                    logger.info(f"UPDATED user {user_id} is_admin -> {is_admin_status}")
            else:
                # Создаём нового пользователя
                db.add(User(
                    telegram_id=user_id,
                    username=admin.user.username or "",
                    joined_at=datetime.utcnow(),
                    is_admin=is_admin_status,
                    chat_id=chat_id
                ))
                logger.info(f"CREATED user {user_id} with is_admin={is_admin_status}")

        db.commit()

async def check_activation_timeout(bot, chat_id: int, adder_id: int, timeout: int = 120):
    """Проверка таймаута активации - если не активировано, бот выходит из чата"""
    await asyncio.sleep(timeout)
    
    activation_data = pending_activations.get(adder_id)
    
    if activation_data and not activation_data["activated"] and activation_data["chat_id"] == chat_id:
        logger.warning(f"Activation timeout for chat {chat_id} by user {adder_id}. Bot leaving chat.")
        try:
            # Уведомляем пользователя в личку
            try:
                await bot.send_message(
                    adder_id,
                    "❌ Время активации истекло. Бот покинул чат."
                )
            except:
                pass
            
            # Уведомляем в группе
            await bot.send_message(
                chat_id,
                "❌ Время активации истекло. Бот покидает чат."
            )
            await bot.leave_chat(chat_id)
            pending_activations.pop(adder_id, None)
        except Exception as e:
            logger.error(f"Error leaving chat {chat_id}: {e}")



@router.message(Command("activate"), F.chat.type == "private")
async def cmd_activate(message: Message):
    """Команда /activate для начала процесса активации"""
    user_id = message.from_user.id
    
    # Проверяем, ожидается ли активация для этого пользователя
    if user_id not in pending_activations:
        await message.reply("❌ У вас нет ожидающих активации ботов.")
        return
    
    activation_data = pending_activations[user_id]
    
    # Если уже активировано
    if activation_data["activated"]:
        await message.reply("✅ Бот уже активирован!")
        return
    
    # Переводим в режим ожидания кода
    activation_data["waiting_for_code"] = True
    
    await message.reply(
        "🔐 Введите секретное кодовое слово для активации бота:\n\n"
        "Отправьте кодовое слово в следующем сообщении."
    )
    logger.info(f"User {user_id} started activation process")



@router.message(
    F.chat.type == "private",
    ~F.text.startswith("/")  # НЕ команда!
)
async def check_activation_word(message: Message):
    """Проверка секретного слова для активации бота (только в личных сообщениях)"""
    user_id = message.from_user.id
    
    # Проверяем, ожидается ли активация для этого пользователя
    if user_id not in pending_activations:
        return
    
    activation_data = pending_activations[user_id]
    
    # Если уже активировано, пропускаем
    if activation_data["activated"]:
        return
    
    # Проверяем, ожидается ли ввод кода
    if not activation_data.get("waiting_for_code", False):
        return
    
    chat_id = activation_data["chat_id"]
    
    # Проверяем секретное слово
    if message.text and message.text.strip() == SECRET_ACTIVATION_WORD:
        # Активация успешна!
        activation_data["activated"] = True
        
        with SessionLocal() as db:
            # Добавляем пользователя в whitelist
            if not db.query(AllowedAdder).filter_by(telegram_id=user_id).first():
                db.add(AllowedAdder(
                    telegram_id=user_id,
                    username=message.from_user.username or "",
                    activated_at=datetime.utcnow()
                ))
                db.commit()
                logger.info(f"User {user_id} added to whitelist")
        
        # Создаём чат и админов
        try:
            chat_info = await message.bot.get_chat(chat_id)
            chat_title = chat_info.title or ""
        except:
            chat_title = ""
        
        await create_chat_and_admins(message.bot, chat_id, chat_title)
        
        # Отправляем подтверждение пользователю в личку
        await message.reply("✅ Бот успешно активирован! Теперь вы можете использовать все функции в вашем чате.")
        
        # Отправляем уведомление в группу
        try:
            await message.bot.send_message(
                chat_id,
                "✅ Бот успешно активирован и готов к работе!"
            )
        except Exception as e:
            logger.error(f"Failed to send activation confirmation to chat {chat_id}: {e}")
        
        logger.info(f"Chat {chat_id} activated by user {user_id}")
        
        # Удаляем из pending после успешной активации
        pending_activations.pop(user_id, None)
    else:
        await message.reply("❌ Неверное кодовое слово. Попробуйте снова.")



@router.chat_member()
async def user_role_changed(event: ChatMemberUpdated):
    """Обработка изменения роли пользователя в чате"""
    try:
        bot_user = await event.bot.get_me()
        chat_id = event.chat.id
        user_id = event.new_chat_member.user.id
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        
        # Пропускаем самого бота
        if user_id == bot_user.id:
            return
        
        logger.info(f"USER {user_id} STATUS CHANGE: {old_status} -> {new_status} in chat {chat_id}")
        
        # Определяем новую роль
        new_is_admin = new_status in ["administrator", "creator"]
        old_is_admin = old_status in ["administrator", "creator"]
        
        # Если роль изменилась
        if new_is_admin != old_is_admin:
            with SessionLocal() as db:
                # Ищем пользователя в базе
                user = db.query(User).filter_by(
                    telegram_id=user_id,
                    chat_id=chat_id
                ).first()
                
                if user:
                    # Обновляем роль существующего пользователя
                    user.is_admin = new_is_admin
                    user.username = event.new_chat_member.user.username or ""
                    logger.info(f"UPDATED user {user_id} admin status to {new_is_admin}")
                else:
                    # Создаем нового пользователя если его нет в базе
                    if new_status != "left":  # Не создаваем пользователя если он покинул чат
                        new_user = User(
                            telegram_id=user_id,
                            username=event.new_chat_member.user.username or "",
                            joined_at=datetime.utcnow(),
                            is_admin=new_is_admin,
                            chat_id=chat_id
                        )
                        db.add(new_user)
                        logger.info(f"CREATED new user {user_id} with admin status {new_is_admin}")
                
                # Если пользователь покинул чат - удаляем его из базы
                if new_status == "left":
                    if user:
                        db.delete(user)
                        logger.info(f"DELETED user {user_id} from chat {chat_id}")
                
                db.commit()
    except Exception as e:
        logger.error(f"ERROR in user_role_changed: {e}")



@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def user_joined_left(event: ChatMemberUpdated):
    """Обработка входа/выхода пользователей"""
    try:
        bot_user = await event.bot.get_me()
        chat_id = event.chat.id
        user_id = event.new_chat_member.user.id
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        
        # Пропускаем самого бота
        if user_id == bot_user.id:
            return
        
        # Пользователь присоединился к чату
        if old_status in ["left", "kicked"] and new_status in ["member", "restricted", "administrator", "creator"]:
            logger.info(f"USER {user_id} JOINED chat {chat_id}")
            
            with SessionLocal() as db:
                # Проверяем есть ли пользователь в базе
                existing_user = db.query(User).filter_by(
                    telegram_id=user_id,
                    chat_id=chat_id
                ).first()
                
                if not existing_user:
                    # Создаем нового пользователя
                    is_admin = new_status in ["administrator", "creator"]
                    new_user = User(
                        telegram_id=user_id,
                        username=event.new_chat_member.user.username or "",
                        joined_at=datetime.utcnow(),
                        is_admin=is_admin,
                        is_banned=False,
                        chat_id=chat_id
                    )
                    db.add(new_user)
                    db.commit()
                    logger.info(f"CREATED user {user_id} in chat {chat_id}")
        
        # Пользователь покинул чат
        elif new_status in ["left", "kicked"] and old_status in ["member", "restricted", "administrator", "creator"]:
            logger.info(f"USER {user_id} LEFT chat {chat_id}")
            
            with SessionLocal() as db:
                user = db.query(User).filter_by(
                    telegram_id=user_id,
                    chat_id=chat_id
                ).first()
                
                if user:
                    if new_status == "kicked":
                        # Если забанен - обновляем статус
                        user.is_banned = True
                        logger.info(f"BANNED user {user_id} in chat {chat_id}")
                    else:
                        # Если просто покинул - удаляем
                        db.delete(user)
                        logger.info(f"DELETED user {user_id} from chat {chat_id}")
                    
                    db.commit()
    except Exception as e:
        logger.error(f"ERROR in user_joined_left: {e}")