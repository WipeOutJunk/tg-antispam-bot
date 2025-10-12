# app/services/settings_service.py
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..config import DEFAULT_SENSITIVITY, DEFAULT_WARN_LIMIT, DEFAULT_QUARANTINE_HOURS


class SettingsService:
    """
    Сервис управления настройками чата (F3.1)
    
    Функции:
    - Получение и создание настроек чата
    - Изменение чувствительности детекции
    - Настройка лимитов предупреждений
    - Управление карантином
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def get_chat_settings(self, chat_id: int, db: Session) -> Chat:
        """
        Получить настройки чата
        
        Args:
            chat_id: ID чата в Telegram
            db: Сессия базы данных
            
        Returns:
            Объект Chat с настройками
        """
        try:
            settings = db.query(Chat).filter(Chat.id == chat_id).first()
            
            if not settings:
                settings = await self._create_default_settings(chat_id, db)
            
            return settings
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек чата {chat_id}: {e}")
            raise
    
    async def _create_default_settings(self, chat_id: int, db: Session) -> Chat:
        """Создать настройки по умолчанию для нового чата"""
        try:
            chat = Chat(
                id=chat_id,
                title="",  # Будет обновлено при первом сообщении
                sensitivity=DEFAULT_SENSITIVITY,
                warn_limit=DEFAULT_WARN_LIMIT,
                quarantine_hours=DEFAULT_QUARANTINE_HOURS,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            db.add(chat)
            db.commit()
            
            self.logger.info(f"Созданы настройки по умолчанию для чата {chat_id}")
            return chat
            
        except Exception as e:
            self.logger.error(f"Ошибка при создании настроек для чата {chat_id}: {e}")
            db.rollback()
            raise
    
    async def update_sensitivity(self, chat_id: int, sensitivity: int, db: Session):
        """
        Изменить чувствительность детекции спама
        
        Args:
            chat_id: ID чата
            sensitivity: Чувствительность от 1 до 10
            db: Сессия БД
        """
        try:
            if not (1 <= sensitivity <= 10):
                raise ValueError("Чувствительность должна быть от 1 до 10")
            
            chat = await self.get_chat_settings(chat_id, db)
            chat.sensitivity = sensitivity
            chat.updated_at = datetime.now()
            
            db.commit()
            
            self.logger.info(f"Обновлена чувствительность чата {chat_id}: {sensitivity}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении чувствительности: {e}")
            db.rollback()
            raise
    
    async def update_warn_limit(self, chat_id: int, limit: int, db: Session):
        """
        Изменить лимит предупреждений
        
        Args:
            chat_id: ID чата
            limit: Количество предупреждений (1-10)
            db: Сессия БД
        """
        try:
            if not (1 <= limit <= 10):
                raise ValueError("Лимит предупреждений должен быть от 1 до 10")
            
            chat = await self.get_chat_settings(chat_id, db)
            chat.warn_limit = limit
            chat.updated_at = datetime.now()
            
            db.commit()
            
            self.logger.info(f"Обновлен лимит предупреждений чата {chat_id}: {limit}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении лимита предупреждений: {e}")
            db.rollback()
            raise
    
    async def update_quarantine_hours(self, chat_id: int, hours: int, db: Session):
        """
        Изменить время карантина для новых пользователей
        
        Args:
            chat_id: ID чата
            hours: Количество часов карантина (0-72)
            db: Сессия БД
        """
        try:
            if not (0 <= hours <= 72):
                raise ValueError("Время карантина должно быть от 0 до 72 часов")
            
            chat = await self.get_chat_settings(chat_id, db)
            chat.quarantine_hours = hours
            chat.updated_at = datetime.now()
            
            db.commit()
            
            self.logger.info(f"Обновлено время карантина чата {chat_id}: {hours} часов")
            
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении времени карантина: {e}")
            db.rollback()
            raise
    
    async def update_chat_title(self, chat_id: int, title: str, db: Session):
        """Обновить название чата"""
        try:
            chat = await self.get_chat_settings(chat_id, db)
            chat.title = title[:100]  # Ограничиваем длину
            chat.updated_at = datetime.now()
            
            db.commit()
            
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении названия чата: {e}")
            db.rollback()
    
    def get_settings_text(self, chat: Chat) -> str:
        """
        Форматирование настроек чата для вывода пользователю
        
        Args:
            chat: Объект настроек чата
            
        Returns:
            Отформатированная строка с настройками
        """
        sensitivity_desc = {
            1: "Очень строгая", 2: "Строгая", 3: "Повышенная", 4: "Умеренно высокая", 5: "Средняя",
            6: "Умеренно низкая", 7: "Низкая", 8: "Пониженная", 9: "Мягкая", 10: "Очень мягкая"
        }
        
        quarantine_text = f"{chat.quarantine_hours} ч." if chat.quarantine_hours > 0 else "Отключен"
        
        return f"""🔧 **Настройки анти-спам бота**

🎯 **Чувствительность**: {chat.sensitivity}/10 ({sensitivity_desc.get(chat.sensitivity, 'Неизвестно')})
⚠️ **Лимит предупреждений**: {chat.warn_limit}
🕐 **Карантин новичков**: {quarantine_text}

📊 Чат создан: {chat.created_at.strftime('%d.%m.%Y %H:%M')}
🔄 Последнее обновление: {chat.updated_at.strftime('%d.%m.%Y %H:%M')}"""
    
    def get_settings_keyboard_data(self, chat: Chat) -> dict:
        """Данные для создания inline-клавиатуры настроек"""
        return {
            "chat_id": chat.id,
            "sensitivity": chat.sensitivity,
            "warn_limit": chat.warn_limit,
            "quarantine_hours": chat.quarantine_hours
        }