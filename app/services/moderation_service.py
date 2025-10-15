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

    async def handle_spam_message(self, message: Message, spam_results: dict):
        """
        Обработка спам-сообщения.
        Принимает результаты анализа в виде словаря.
        """
        try:
            # Выдаем предупреждение
            reason = self.format_spam_reason(spam_results)
            await self.issue_warning(message.from_user.id, message.chat.id, reason)
            
            self.logger.info(f"Warning issued to user {message.from_user.id} in chat {message.chat.id}")
            
        except Exception as e:
            self.logger.error(f"Error in handle_spam_message: {e}")

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

    def format_spam_reason(self, spam_results: dict) -> str:
        """Преобразовать результаты анализа в читаемую строку"""
        if not spam_results:
            return "Неизвестная причина"
        
        reasons = spam_results.get('reasons', [])
        if reasons:
            return ', '.join(reasons)
        
        # Fallback на основании confidence
        confidence = spam_results.get('confidence', 0)
        if confidence > 0.8:
            return "Высокая вероятность спама"
        elif confidence > 0.6:
            return "Подозрительное содержимое"
        else:
            return "Потенциальный спам"
    async def notify_user_spam(self, message: Message, reason: str):
        try:
            text = (
                f"⚠️ Ваше сообщение было удалено по подозрению в спаме.\n"
                f"Причина: {reason}"
            )
            await self.bot.send_message(chat_id=message.chat.id, text=text)
        except Exception as e:
            self.logger.error(f"Ошибка уведомления пользователя: {e}")