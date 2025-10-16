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
