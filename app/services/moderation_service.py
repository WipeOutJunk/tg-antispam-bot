import logging
from datetime import datetime
from typing import List, Optional

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy.orm import Session

from ..models.warning import Warning
from ..models.message_log import MessageLog
from .base_detector import SpamDetectionResult


class ModerationService:
    def __init__(self, bot: Bot, db: Session, logger: Optional[logging.Logger] = None):
        self.bot = bot
        self.db = db
        self.logger = logger or logging.getLogger(__name__)

    async def handle_message(self, message: Message, spam_results: List[SpamDetectionResult]):
        """Обработка любого входящего сообщения"""
        # 1) Лог любого сообщения
        await self.log_message(message, is_spam=False)

        # 2) Если нет спама — выходим
        if not spam_results:
            return

        # 3) Удаляем спам
        await self.delete_message(message.chat.id, message.message_id)
        # 4) Логируем спам
        await self.log_message(message, is_spam=True)

        # 5) Предупреждаем и уведомляем автора
        reason = self.format_spam_reason(spam_results)
        await self.issue_warning(message.from_user.id, message.chat.id, reason)
        await self.notify_spam_action(message, reason)

    # Псевдоним для обратной совместимости
    handle_spam_message = handle_message

    async def log_message(self, message: Message, is_spam: bool,
                          spam_results: Optional[List[SpamDetectionResult]] = None):
        """Сохранить сообщение в MessageLog"""
        try:
            log = MessageLog(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                content=message.text or message.caption or "",
                is_spam=is_spam,
                created_at=datetime.now()
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            self.logger.error("Error logging message: %s", e)

    async def delete_message(self, chat_id: int, message_id: int):
        """Удалить сообщение из чата"""
        try:
            await self.bot.delete_message(chat_id, message_id)
        except Exception as e:
            self.logger.error("Error deleting message %s/%s: %s", chat_id, message_id, e)

    async def issue_warning(self, user_id: int, chat_id: int, reason: str):
        """Добавить предупреждение в базу"""
        try:
            warn = Warning(
                user_id=user_id,
                chat_id=chat_id,
                issued_at=datetime.now(),
                reason=reason
            )
            self.db.add(warn)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            self.logger.error("Error issuing warning: %s", e)

    async def notify_spam_action(self, message: Message, reason: str):
        """Уведомить автора об удалении"""
        text = (
            f"⚠️ Ваше сообщение было удалено как вредоносное.\n"
            f"Причина: {reason}"
        )
        try:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text=text
            )
        except Exception as e:
            self.logger.error("Error notifying user: %s", e)

    def format_spam_reason(self, results: List[SpamDetectionResult]) -> str:
        """Преобразовать список результатов в строку"""
        return ", ".join(r.label for r in results)
