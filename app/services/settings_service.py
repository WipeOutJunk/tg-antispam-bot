import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..config import DEFAULT_SENSITIVITY, DEFAULT_WARN_LIMIT, DEFAULT_QUARANTINE_HOURS


class SettingsService:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    async def get_chat_settings(self, chat_id: int, db: Session) -> Optional[Chat]:
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

    async def create_default_settings(self, chat_id: int, db: Session, title: Optional[str] = None) -> Chat:
        """Создать настройки по умолчанию для нового чата"""
        try:
            chat = Chat(
                id=chat_id,
                title=title,
                sensitivity=DEFAULT_SENSITIVITY,
                warn_limit=DEFAULT_WARN_LIMIT,
                quarantine_hours=DEFAULT_QUARANTINE_HOURS,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(chat)
            db.commit()
            db.refresh(chat)
            self.logger.info("Created default settings for chat %s", chat_id)
            return chat
        except Exception as e:
            db.rollback()
            self.logger.error("Error creating default settings for %s: %s", chat_id, e)
            raise

    async def update_sensitivity(self, chat_id: int, new_sensitivity: int, db: Session) -> bool:
        """
        Обновить чувствительность детектора для чата.
        Возвращает True при успехе, False если чат не найден.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                self.logger.error("Chat %s not found when updating sensitivity", chat_id)
                return False
            
            chat.sensitivity = new_sensitivity
            chat.updated_at = datetime.now()
            db.commit()
            db.refresh(chat)
            self.logger.info("Updated sensitivity for chat %s to %s", chat_id, new_sensitivity)
            return True
        except Exception as e:
            db.rollback()
            self.logger.error("Error updating sensitivity for %s: %s", chat_id, e)
            raise

    async def update_warn_limit(self, chat_id: int, new_warn_limit: int, db: Session) -> bool:
        """
        Обновить лимит предупреждений для чата.
        Возвращает True при успехе, False если чат не найден.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                self.logger.error("Chat %s not found when updating warn limit", chat_id)
                return False
            
            chat.warn_limit = new_warn_limit
            chat.updated_at = datetime.now()
            db.commit()
            db.refresh(chat)
            self.logger.info("Updated warn limit for chat %s to %s", chat_id, new_warn_limit)
            return True
        except Exception as e:
            db.rollback()
            self.logger.error("Error updating warn limit for %s: %s", chat_id, e)
            raise

    async def update_quarantine_hours(self, chat_id: int, new_quarantine_hours: int, db: Session) -> bool:
        """
        Обновить время карантина для чата.
        Возвращает True при успехе, False если чат не найден.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                self.logger.error("Chat %s not found when updating quarantine hours", chat_id)
                return False
            
            chat.quarantine_hours = new_quarantine_hours
            chat.updated_at = datetime.now()
            db.commit()
            db.refresh(chat)
            self.logger.info("Updated quarantine hours for chat %s to %s", chat_id, new_quarantine_hours)
            return True
        except Exception as e:
            db.rollback()
            self.logger.error("Error updating quarantine hours for %s: %s", chat_id, e)
            raise

    async def update_chat_title(self, chat_id: int, new_title: str, db: Session) -> bool:
        """
        Обновить название чата.
        Возвращает True при успехе, False если чат не найден.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                self.logger.error("Chat %s not found when updating title", chat_id)
                return False
            
            chat.title = new_title
            chat.updated_at = datetime.now()
            db.commit()
            db.refresh(chat)
            self.logger.info("Updated title for chat %s to '%s'", chat_id, new_title)
            return True
        except Exception as e:
            db.rollback()
            self.logger.error("Error updating title for %s: %s", chat_id, e)
            raise

    async def upsert_chat_settings(self, chat_id: int, title: Optional[str] = None, 
                                  sensitivity: Optional[int] = None,
                                  warn_limit: Optional[int] = None,
                                  quarantine_hours: Optional[int] = None,
                                  db: Session = None) -> Chat:
        """
        Создать или обновить настройки чата.
        Если чат существует - обновляет только переданные параметры.
        Если не существует - создаёт с переданными параметрами или значениями по умолчанию.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            
            if not chat:
                # Создаём новый чат
                chat = Chat(
                    id=chat_id,
                    title=title,
                    sensitivity=sensitivity or DEFAULT_SENSITIVITY,
                    warn_limit=warn_limit or DEFAULT_WARN_LIMIT,
                    quarantine_hours=quarantine_hours or DEFAULT_QUARANTINE_HOURS,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(chat)
                self.logger.info("Creating new chat settings for %s", chat_id)
            else:
                # Обновляем существующий чат
                if title is not None:
                    chat.title = title
                if sensitivity is not None:
                    chat.sensitivity = sensitivity
                if warn_limit is not None:
                    chat.warn_limit = warn_limit
                if quarantine_hours is not None:
                    chat.quarantine_hours = quarantine_hours
                chat.updated_at = datetime.now()
                self.logger.info("Updating existing chat settings for %s", chat_id)
            
            db.commit()
            db.refresh(chat)
            return chat
        except Exception as e:
            db.rollback()
            self.logger.error("Error upserting settings for %s: %s", chat_id, e)
            raise

    async def delete_chat_settings(self, chat_id: int, db: Session) -> bool:
        """
        Удалить настройки чата.
        Возвращает True при успехе, False если чат не найден.
        """
        try:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat:
                self.logger.warning("Chat %s not found when trying to delete", chat_id)
                return False
            
            db.delete(chat)
            db.commit()
            self.logger.info("Deleted settings for chat %s", chat_id)
            return True
        except Exception as e:
            db.rollback()
            self.logger.error("Error deleting settings for %s: %s", chat_id, e)
            raise

    async def get_all_chats(self, db: Session, limit: Optional[int] = None) -> list[Chat]:
        """
        Получить все чаты с настройками.
        """
        try:
            query = db.query(Chat).order_by(Chat.updated_at.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        except Exception as e:
            self.logger.error("Error fetching all chats: %s", e)
            raise

    async def get_chats_by_sensitivity(self, sensitivity: int, db: Session) -> list[Chat]:
        """
        Получить чаты с определённым уровнем чувствительности.
        """
        try:
            return db.query(Chat).filter(Chat.sensitivity == sensitivity).all()
        except Exception as e:
            self.logger.error("Error fetching chats by sensitivity %s: %s", sensitivity, e)
            raise