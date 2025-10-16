# app/handlers/chat_events.py

import logging
from datetime import datetime
from aiogram import Router
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter
from ..database import SessionLocal
from ..models.chat import Chat
from ..models.user import User

logger = logging.getLogger(__name__)
router = Router()

@router.my_chat_member()
async def bot_added_removed(event: ChatMemberUpdated):
    """Простая обработка добавления/удаления бота"""
    print("CHAT_EVENTS MODULE LOADED")
    bot_user = await event.bot.get_me()
    
    if event.new_chat_member.user.id != bot_user.id:
        return
    
    chat_id = event.chat.id
    logger.info(f"BOT STATUS CHANGE: {event.old_chat_member.status} -> {event.new_chat_member.status} in {chat_id}")
    
    if event.new_chat_member.status in ("member", "administrator"):
        # Бот добавлен - создаём чат и админов
        with SessionLocal() as db:
            # 1. Создаём чат
            if not db.query(Chat).filter_by(id=chat_id).first():
                db.add(Chat(
                    id=chat_id,
                    title=event.chat.title or "",
                    sensitivity=5,
                    warn_limit=3
                ))
                db.commit()
                logger.info(f"CHAT {chat_id} CREATED")
            
            # 2. Получаем админов и создаём пользователей
            try:
                admins = await event.bot.get_chat_administrators(chat_id=chat_id)
                logger.info(f"FOUND {len(admins)} ADMINS")
                
                for admin in admins:
                    user_id = admin.user.id
                    if not db.query(User).filter_by(telegram_id=user_id, chat_id=chat_id).first():
                        db.add(User(
                            telegram_id=user_id,
                            username=admin.user.username or "",
                            joined_at=datetime.utcnow(),
                            is_admin=True,
                            chat_id=chat_id
                        ))
                        logger.info(f"ADMIN {user_id} CREATED")
                
                db.commit()
                logger.info(f"ALL ADMINS SAVED FOR CHAT {chat_id}")
            except Exception as e:
                logger.error(f"ERROR GETTING ADMINS: {e}")
                
    elif event.new_chat_member.status == "left":
        # Бот удалён - удаляем всё
        with SessionLocal() as db:
            db.query(Chat).filter(Chat.id == chat_id).delete()
            db.commit()
            logger.info(f"CHAT {chat_id} DELETED")


@router.chat_member()
async def user_role_changed(event: ChatMemberUpdated):
    """Обработка изменения роли пользователя в чате"""
    try:
        chat_id = event.chat.id
        user_id = event.new_chat_member.user.id
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        
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
        chat_id = event.chat.id
        user_id = event.new_chat_member.user.id
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        
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