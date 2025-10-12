# app/services/moderation_service.py
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..models.user import User
from ..models.warning import Warning
from ..models.ban import Ban
from ..models.message_log import MessageLog
from .base_detector import SpamDetectionResult


class ModerationService:
    """
    Сервис модерации пользователей (F2.1-F2.4)
    
    Функции:
    - Автоматическое удаление спам-сообщений (F2.1)
    - Выдача предупреждений (F2.2)
    - Блокировка при превышении лимита (F2.3)
    - Учет предупреждений (F2.4)
    """
    
    def __init__(self, bot: Bot, db: Session):
        self.bot = bot
        self.db = db
        self.logger = logging.getLogger(__name__)
    
    async def handle_spam_message(self, message, spam_results: List[SpamDetectionResult]):
        """
        Обработка спам-сообщения (F2.1)
        
        Args:
            message: Telegram сообщение
            spam_results: Результаты детекции спама
        """
        try:
            user_id = message.from_user.id
            chat_id = message.chat.id
            
            # 1. Удаляем сообщение
            await self.delete_message(chat_id, message.message_id)
            
            # 2. Логируем спам
            await self._log_spam_message(message, spam_results)
            
            # 3. Выдаем предупреждение
            reason = self._format_spam_reason(spam_results)
            await self.issue_warning(user_id, chat_id, reason)
            
            # 4. Уведомляем о действии (опционально)
            await self._notify_spam_action(message, reason)
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке спам-сообщения: {e}")
    
    async def delete_message(self, chat_id: int, message_id: int):
        """Удаление сообщения (F2.1)"""
        try:
            await self.bot.delete_message(chat_id, message_id)
            self.logger.info(f"Удалено сообщение {message_id} из чата {chat_id}")
            
        except Exception as e:
            self.logger.warning(f"Не удалось удалить сообщение {message_id}: {e}")
    
    async def issue_warning(self, user_id: int, chat_id: int, reason: str):
        """Выдача предупреждения (F2.2, F2.4)"""
        try:
            # Создаем предупреждение
            warning = Warning(
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                issued_at=datetime.now()
            )
            
            self.db.add(warning)
            self.db.commit()
            
            self.logger.info(f"Выдано предупреждение пользователю {user_id} в чате {chat_id}: {reason}")
            
            # Проверяем лимит предупреждений
            await self._check_warning_limit(user_id, chat_id)
            
        except Exception as e:
            self.logger.error(f"Ошибка при выдаче предупреждения: {e}")
            self.db.rollback()
            raise
    
    async def _check_warning_limit(self, user_id: int, chat_id: int):
        """Проверка лимита предупреждений (F2.3)"""
        try:
            # Получаем настройки чата
            chat_settings = self.db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat_settings:
                return
            
            # Подсчитываем активные предупреждения пользователя
            warning_count = self.db.query(Warning).filter(
                Warning.user_id == user_id,
                Warning.chat_id == chat_id
            ).count()
            
            self.logger.info(f"Пользователь {user_id} имеет {warning_count}/{chat_settings.warn_limit} предупреждений")
            
            # Если лимит превышен - баним
            if warning_count >= chat_settings.warn_limit:
                await self.ban_user(
                    user_id, 
                    chat_id, 
                    reason=f"Превышен лимит предупреждений ({warning_count}/{chat_settings.warn_limit})"
                )
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке лимита предупреждений: {e}")
    
    async def ban_user(self, user_id: int, chat_id: int, duration: Optional[int] = None, reason: str = ""):
        """Блокировка пользователя (F2.3)"""
        try:
            action_type = "mute" if duration else "ban"
            expires_at = datetime.now() + timedelta(seconds=duration) if duration else None
            
            # Применяем блокировку в Telegram
            if duration:
                # Временная блокировка (mute)
                await self.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=expires_at
                )
                self.logger.info(f"Пользователь {user_id} заблокирован на {duration} секунд в чате {chat_id}")
                
            else:
                # Постоянная блокировка (ban)
                await self.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                self.logger.info(f"Пользователь {user_id} забанен в чате {chat_id}")
            
            # Записываем в базу данных
            ban_record = Ban(
                user_id=user_id,
                chat_id=chat_id,
                action=action_type,
                reason=reason,
                issued_at=datetime.now(),
                expires_at=expires_at
            )
            
            self.db.add(ban_record)
            
            # Обновляем статус пользователя
            user = self.db.query(User).filter(
                User.telegram_id == user_id,
                User.chat_id == chat_id
            ).first()
            
            if user:
                user.is_banned = True
                if expires_at:
                    user.ban_expires_at = expires_at
            
            self.db.commit()
            
        except Exception as e:
            self.logger.error(f"Ошибка при блокировке пользователя: {e}")
            self.db.rollback()
            raise
    
    async def unban_user(self, user_id: int, chat_id: int, reason: str = ""):
        """Разблокировка пользователя"""
        try:
            # Разблокировка в Telegram
            await self.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            
            # Обновляем статус в БД
            user = self.db.query(User).filter(
                User.telegram_id == user_id,
                User.chat_id == chat_id
            ).first()
            
            if user:
                user.is_banned = False
                user.ban_expires_at = None
            
            # Логируем разблокировку
            unban_record = Ban(
                user_id=user_id,
                chat_id=chat_id,
                action="unban",
                reason=reason,
                issued_at=datetime.now(),
                expires_at=None
            )
            
            self.db.add(unban_record)
            self.db.commit()
            
            self.logger.info(f"Пользователь {user_id} разблокирован в чате {chat_id}: {reason}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при разблокировке пользователя: {e}")
            self.db.rollback()
            raise
    
    async def kick_user(self, user_id: int, chat_id: int, reason: str = ""):
        """Исключение пользователя из чата"""
        try:
            # Исключаем из чата
            await self.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            # Сразу разбаниваем (чтобы мог вернуться по ссылке)
            await self.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            
            # Записываем в БД
            kick_record = Ban(
                user_id=user_id,
                chat_id=chat_id,
                action="kick",
                reason=reason,
                issued_at=datetime.now(),
                expires_at=None
            )
            
            self.db.add(kick_record)
            self.db.commit()
            
            self.logger.info(f"Пользователь {user_id} исключен из чата {chat_id}: {reason}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при исключении пользователя: {e}")
            self.db.rollback()
            raise
    
    def get_user_warnings(self, user_id: int, chat_id: int) -> List[Warning]:
        """Получение предупреждений пользователя"""
        return self.db.query(Warning).filter(
            Warning.user_id == user_id,
            Warning.chat_id == chat_id
        ).order_by(Warning.issued_at.desc()).all()
    
    def clear_user_warnings(self, user_id: int, chat_id: int):
        """Очистка предупреждений пользователя"""
        try:
            warnings = self.db.query(Warning).filter(
                Warning.user_id == user_id,
                Warning.chat_id == chat_id
            ).all()
            
            for warning in warnings:
                self.db.delete(warning)
            
            self.db.commit()
            self.logger.info(f"Очищены предупреждения пользователя {user_id} в чате {chat_id}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при очистке предупреждений: {e}")
            self.db.rollback()
            raise
    
    async def _log_spam_message(self, message, spam_results: List[SpamDetectionResult]):
        """Логирование спам-сообщения"""
        try:
            # Обновляем лог сообщения
            log_entry = self.db.query(MessageLog).filter(
                MessageLog.chat_id == message.chat.id,
                MessageLog.user_id == message.from_user.id,
                MessageLog.message_id == message.message_id
            ).first()
            
            if log_entry:
                log_entry.is_spam = True
                detected_by = ", ".join([r.detector_name for r in spam_results])
                # Можно добавить поле detected_by в модель MessageLog
            else:
                # Создаем новую запись если не было логирования
                log_entry = MessageLog(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    message_id=message.message_id,
                    content=self._extract_text(message)[:500],
                    is_spam=True,
                    created_at=datetime.now()
                )
                self.db.add(log_entry)
            
            self.db.commit()
            
        except Exception as e:
            self.logger.error(f"Ошибка при логировании спама: {e}")
    
    def _format_spam_reason(self, spam_results: List[SpamDetectionResult]) -> str:
        """Форматирование причины спама"""
        if not spam_results:
            return "Обнаружен спам"
        
        reasons = []
        for result in spam_results[:2]:  # Берем первые 2 причины
            reasons.append(f"{result.detector_name}: {result.reason}")
        
        return "; ".join(reasons)
    
    def _extract_text(self, message) -> str:
        """Извлечение текста из сообщения"""
        if hasattr(message, 'text') and message.text:
            return message.text
        elif hasattr(message, 'caption') and message.caption:
            return message.caption
        return ""
    
    async def _notify_spam_action(self, message, reason: str):
        """Уведомление о действии модерации (опционально)"""
        # Можно отправить уведомление в чат или в логи
        # Пока только логируем
        self.logger.info(f"Модерация в чате {message.chat.id}: {reason}")