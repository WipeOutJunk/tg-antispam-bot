# app/services/quarantine_service.py
import logging
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..models.user import User


class QuarantineService:
    """
    Сервис карантина для новых пользователей (F3.4)
    
    Функции:
    - Применение карантина к новым участникам
    - Проверка статуса карантина
    - Автоматическое снятие ограничений
    """
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        
        # Ограничения для карантина
        self.quarantine_permissions = ChatPermissions(
            can_send_messages=True,          # Может писать текст
            can_send_media_messages=False,   # Не может отправлять медиа
            can_send_other_messages=False,   # Не может отправлять стикеры/GIF
            can_add_web_page_previews=False, # Не может добавлять превью ссылок
            can_send_polls=False,            # Не может создавать опросы
            can_change_info=False,           # Не может изменять инфо чата
            can_invite_users=False,          # Не может приглашать пользователей
            can_pin_messages=False           # Не может закреплять сообщения
        )
        
        # Полные права после карантина
        self.full_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_send_polls=True,
            can_change_info=False,  # Остается False для обычных пользователей
            can_invite_users=True,
            can_pin_messages=False   # Остается False для обычных пользователей
        )
    
    async def apply_quarantine(self, user_id: int, chat_id: int, db: Session):
        """
        Применить карантин к новому пользователю
        
        Args:
            user_id: ID пользователя в Telegram
            chat_id: ID чата
            db: Сессия базы данных
        """
        try:
            # Получаем настройки чата
            chat_settings = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat_settings or chat_settings.quarantine_hours == 0:
                self.logger.info(f"Карантин отключен для чата {chat_id}")
                return
            
            # Проверяем, есть ли уже запись о пользователе
            user = db.query(User).filter(
                User.telegram_id == user_id,
                User.chat_id == chat_id
            ).first()
            
            if not user:
                # Создаем новую запись пользователя
                user = User(
                    telegram_id=user_id,
                    chat_id=chat_id,
                    joined_at=datetime.now(),
                    is_admin=False,
                    is_banned=False
                )
                db.add(user)
                db.commit()
            
            # Вычисляем время окончания карантина
            quarantine_end = user.joined_at + timedelta(hours=chat_settings.quarantine_hours)
            
            # Применяем ограничения в Telegram
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=self.quarantine_permissions,
                until_date=quarantine_end
            )
            
            self.logger.info(
                f"Применен карантин для пользователя {user_id} в чате {chat_id} "
                f"на {chat_settings.quarantine_hours} часов (до {quarantine_end})"
            )
            
            # Отправляем приветственное сообщение (опционально)
            await self._send_quarantine_notification(chat_id, user_id, chat_settings.quarantine_hours)
            
        except Exception as e:
            self.logger.error(f"Ошибка при применении карантина: {e}")
            db.rollback()
            raise
    
    async def is_in_quarantine(self, user_id: int, chat_id: int, db: Session) -> bool:
        """
        Проверить, находится ли пользователь в карантине
        
        Args:
            user_id: ID пользователя
            chat_id: ID чата
            db: Сессия БД
            
        Returns:
            True если пользователь в карантине
        """
        try:
            # Получаем данные пользователя
            user = db.query(User).filter(
                User.telegram_id == user_id,
                User.chat_id == chat_id
            ).first()
            
            if not user:
                return False
            
            # Получаем настройки чата
            chat_settings = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat_settings or chat_settings.quarantine_hours == 0:
                return False
            
            # Проверяем, не истек ли карантин
            quarantine_end = user.joined_at + timedelta(hours=chat_settings.quarantine_hours)
            is_quarantined = datetime.now() < quarantine_end
            
            self.logger.debug(
                f"Проверка карантина для пользователя {user_id}: "
                f"присоединился {user.joined_at}, карантин до {quarantine_end}, "
                f"статус: {'в карантине' if is_quarantined else 'свободен'}"
            )
            
            return is_quarantined
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке карантина: {e}")
            return False
    
    async def lift_quarantine(self, user_id: int, chat_id: int, db: Session):
        """
        Принудительно снять карантин с пользователя
        
        Args:
            user_id: ID пользователя
            chat_id: ID чата
            db: Сессия БД
        """
        try:
            # Восстанавливаем полные права
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=self.full_permissions
            )
            
            self.logger.info(f"Карантин снят с пользователя {user_id} в чате {chat_id}")
            
            # Отправляем уведомление (опционально)
            await self._send_quarantine_lifted_notification(chat_id, user_id)
            
        except Exception as e:
            self.logger.error(f"Ошибка при снятии карантина: {e}")
            raise
    
    async def get_quarantine_info(self, user_id: int, chat_id: int, db: Session) -> Optional[dict]:
        """
        Получить информацию о карантине пользователя
        
        Args:
            user_id: ID пользователя
            chat_id: ID чата
            db: Сессия БД
            
        Returns:
            Словарь с информацией о карантине или None
        """
        try:
            user = db.query(User).filter(
                User.telegram_id == user_id,
                User.chat_id == chat_id
            ).first()
            
            if not user:
                return None
            
            chat_settings = db.query(Chat).filter(Chat.id == chat_id).first()
            if not chat_settings or chat_settings.quarantine_hours == 0:
                return None
            
            quarantine_end = user.joined_at + timedelta(hours=chat_settings.quarantine_hours)
            is_active = datetime.now() < quarantine_end
            
            return {
                "user_id": user_id,
                "chat_id": chat_id,
                "joined_at": user.joined_at,
                "quarantine_hours": chat_settings.quarantine_hours,
                "quarantine_end": quarantine_end,
                "is_active": is_active,
                "remaining_time": (quarantine_end - datetime.now()).total_seconds() if is_active else 0
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении информации о карантине: {e}")
            return None
    
    async def _send_quarantine_notification(self, chat_id: int, user_id: int, hours: int):
        """Отправка уведомления о карантине (опционально)"""
        try:
            # Можно отправить личное сообщение пользователю или в чат
            # Пока только логируем
            self.logger.info(f"Пользователь {user_id} помещен в карантин на {hours} часов")
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления о карантине: {e}")
    
    async def _send_quarantine_lifted_notification(self, chat_id: int, user_id: int):
        """Уведомление об окончании карантина"""
        try:
            self.logger.info(f"Карантин пользователя {user_id} завершен")
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления об окончании карантина: {e}")
    
    async def check_and_lift_expired_quarantines(self, db: Session):
        """
        Проверка и автоматическое снятие истекших карантинов
        
        Этот метод можно вызывать периодически (например, каждый час)
        """
        try:
            # Получаем всех пользователей, чей карантин должен был закончиться
            current_time = datetime.now()
            
            # Получаем всех пользователей с активными настройками карантина
            users_in_quarantine = db.query(User, Chat).join(
                Chat, User.chat_id == Chat.id
            ).filter(
                Chat.quarantine_hours > 0,
                User.joined_at + timedelta(hours=Chat.quarantine_hours) <= current_time,
                User.is_banned == False
            ).all()
            
            lifted_count = 0
            for user, chat in users_in_quarantine:
                try:
                    await self.lift_quarantine(user.telegram_id, user.chat_id, db)
                    lifted_count += 1
                except Exception as e:
                    self.logger.error(f"Ошибка при снятии карантина с пользователя {user.telegram_id}: {e}")
            
            if lifted_count > 0:
                self.logger.info(f"Автоматически снят карантин с {lifted_count} пользователей")
                
        except Exception as e:
            self.logger.error(f"Ошибка при проверке истекших карантинов: {e}")