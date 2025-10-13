import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..config import DEFAULT_SENSITIVITY, DEFAULT_WARN_LIMIT, DEFAULT_QUARANTINE_HOURS


class SettingsService:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    async def get_chat_settings(self, chat_id: int, db: Session) -> Chat:
        """
        Получить настройки чата.
        Не создаёт чат автоматически — возвращает None, если запись отсутствует.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            return chat
        except Exception as e:
            self.logger.error("Error fetching settings for %s: %s", chat_id, e)
            raise

    async def create_default_settings(self, chat_id: int, db: Session) -> Chat:
        """Создать настройки по умолчанию для нового чата"""
        try:
            chat = Chat(
                id=chat_id,
                title=None,
                sensitivity=DEFAULT_SENSITIVITY,
                warn_limit=DEFAULT_WARN_LIMIT,
                quarantine_hours=DEFAULT_QUARANTINE_HOURS,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(chat)
            db.commit()
            self.logger.info("Created default settings for chat %s", chat_id)
            return chat
        except Exception as e:
            db.rollback()
            self.logger.error("Error creating default settings for %s: %s", chat_id, e)
            raise

    async def update_sensitivity(self, chat_id: int, new_sensitivity: int, db: Session):
        """Обновить чувствительность детектора для чата"""
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                # не создаём автоматически; можно выбросить ошибку или просто вернуть
                self.logger.error("Chat %s not found when updating sensitivity", chat_id)
                return
            chat.sensitivity = new_sensitivity
            chat.updated_at = datetime.now()
            db.commit()
            self.logger.info("Updated sensitivity for chat %s to %s", chat_id, new_sensitivity)
        except Exception as e:
            db.rollback()
            self.logger.error("Error updating sensitivity for %s: %s", chat_id, e)
            raise
