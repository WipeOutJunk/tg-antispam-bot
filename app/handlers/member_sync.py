# app/handlers/member_sync.py

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated

from ..database import SessionLocal
from ..models.chat import Chat
from ..models.user import User
from ..config import SYNC_HOUR_UTC

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.chat.type.in_({"group", "supergroup"}), F.any())
async def on_any_message(message: Message):
    """
    Регистрация авторов сообщений в БД.
    """
    user = message.from_user
    chat_id = message.chat.id

    with SessionLocal() as db:
        obj = db.query(User).filter_by(
            telegram_id=user.id, chat_id=chat_id
        ).first()
        if not obj:
            db.add(User(
                telegram_id=user.id,
                username=user.username,
                joined_at=datetime.utcnow(),
                chat_id=chat_id,
                is_admin=False,
                is_banned=False
            ))
            db.commit()
            logger.info(f"[Msg] Добавлен участник {user.id} в чат {chat_id}")


@router.chat_member(F.chat.type.in_({"group", "supergroup"}))
async def on_member_change(update: ChatMemberUpdated):
    """
    Обработка изменений статуса участника:
    - создание/обновление User
    - удаление при выходе
    - установка is_admin в зависимости от старого и нового статуса
    """
    user = update.new_chat_member.user
    chat_id = update.chat.id
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status

    with SessionLocal() as db:
        obj = db.query(User).filter_by(
            telegram_id=user.id, chat_id=chat_id
        ).first()

        # Пользователь зашел или получил новый статус
        if new_status in ("member", "administrator", "creator"):
            is_admin = new_status in ("administrator", "creator")
            if not obj:
                obj = User(
                    telegram_id=user.id,
                    username=user.username,
                    joined_at=datetime.utcnow(),
                    chat_id=chat_id,
                    is_admin=is_admin,
                    is_banned=False
                )
                db.add(obj)
                logger.info(f"[ChatMember] Добавлен {user.id} ({new_status})")
            else:
                obj.username = user.username
                obj.is_admin = is_admin
                obj.is_banned = False
                obj.joined_at = datetime.utcnow()
                logger.info(f"[ChatMember] Обновлён {user.id} {old_status}->{new_status}")
            db.commit()

        # Пользователь вышел или был исключён/забанен
        elif new_status in ("left", "kicked", "banned"):
            if obj:
                if new_status == "banned":
                    obj.is_banned = True
                    db.commit()
                    logger.info(f"[ChatMember] Забанен {user.id}")
                else:
                    db.delete(obj)
                    db.commit()
                    logger.info(f"[ChatMember] Удалён {user.id} при {new_status}")


async def sync_all_chats(bot: Bot):
    """
    Ежедневная синхронизация:
    - проверка админов via get_chat_administrators
    - проверка присутствия и is_banned via get_chat_member
    """
    logger.info("Начало ежедневной синхронизации")
    with SessionLocal() as db:
        chats = db.query(Chat).all()
        for chat in chats:
            try:
                admins = await bot.get_chat_administrators(chat.id)
                admin_ids = {m.user.id for m in admins}
            except Exception as e:
                logger.error(f"get_chat_administrators {chat.id}: {e}")
                admin_ids = set()

            users = db.query(User).filter_by(chat_id=chat.id).all()
            for u in users:
                # Проверка присутствия
                try:
                    await bot.get_chat_member(chat.id, u.telegram_id)
                    present = True
                except:
                    present = False

                # is_banned
                if not present and not u.is_banned:
                    u.is_banned = True
                    logger.info(f"(Sync) Помечен is_banned={True} {u.telegram_id}")
                elif present and u.is_banned:
                    u.is_banned = False
                    logger.info(f"(Sync) Помечен is_banned={False} {u.telegram_id}")

                # is_admin
                should_admin = u.telegram_id in admin_ids
                if u.is_admin != should_admin:
                    u.is_admin = should_admin
                    logger.info(f"(Sync) is_admin={should_admin} {u.telegram_id}")

        db.commit()
    logger.info("Синхронизация завершена")


async def schedule_daily_sync(bot: Bot):
    """
    Планировщик ежедневной синхронизации в SYNC_HOUR_UTC UTC.
    """
    while True:
        await sync_all_chats(bot)
        now = datetime.utcnow()
        next_run = now.replace(hour=SYNC_HOUR_UTC, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        delay = (next_run - now).total_seconds()
        logger.info(f"Следующая синхронизация через {delay/3600:.1f} ч")
        await asyncio.sleep(delay)
