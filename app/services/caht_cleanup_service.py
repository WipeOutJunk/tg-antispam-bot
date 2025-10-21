# app/services/chat_cleanup_service.py

import logging
from typing import Dict, Any

from sqlalchemy.orm import Session

from ..models.chat import Chat
from ..models.user import User
from ..models.warning import Warning
from ..models.ban import Ban
from ..models.spam_words import SpamWord
from ..models.spam_link import SpamLink
from ..models.message_log import MessageLog
from ..models.statistic import Statistic
from ..models.admin_notification import AdminNotification
from ..models.admin_notification import  AdminNotificationMessage

logger = logging.getLogger(__name__)


class ChatCleanupService:
    """
    Сервис для полной очистки данных чата при удалении бота.
    """

    async def dry_run_cleanup(self, chat_id: int, db: Session) -> Dict[str, int]:
        """
        Подсчёт записей для удаления.
        """
        counts: Dict[str, int] = {}

        counts['message_logs'] = db.query(MessageLog).filter(MessageLog.chat_id == chat_id).count()
        counts['users']        = db.query(User).filter(User.chat_id == chat_id).count()
        counts['warnings']     = db.query(Warning).filter(Warning.chat_id == chat_id).count()
        counts['bans']         = db.query(Ban).filter(Ban.chat_id == chat_id).count()
        counts['spam_words']   = db.query(SpamWord).filter(SpamWord.chat_id == chat_id).count()
        counts['spam_links']   = db.query(SpamLink).filter(SpamLink.chat_id == chat_id).count()
        counts['statistics']   = db.query(Statistic).filter(Statistic.chat_id == chat_id).count()
        counts['notifications'] = db.query(AdminNotification).filter(
            AdminNotification.original_chat_id == chat_id
        ).count()
        counts['notification_messages'] = db.query(AdminNotificationMessage).filter(
            AdminNotificationMessage.chat_id == chat_id
        ).count()
        counts['chats']        = db.query(Chat).filter(Chat.id == chat_id).count()

        total = sum(counts.values())
        counts['total'] = total
        logger.info(f"[dry_run] chat {chat_id}: total records = {total}")
        return counts

    async def cleanup_chat_data(self, chat_id: int, db: Session, reason: str = "bot_removed") -> Dict[str, Any]:
        """
        Каскадное удаление всех записей чата.
        ВАЖНО: метод НЕ делает commit - это делает вызывающий код!
        """
        logger.info(f"[cleanup] Start cleanup for chat {chat_id} (reason: {reason})")
        results: Dict[str, int] = {}

        try:
            # Удаляем зависимые записи СНАЧАЛА
            results['bans'] = db.query(Ban).filter(Ban.chat_id == chat_id).delete(synchronize_session=False)
            results['warnings'] = db.query(Warning).filter(Warning.chat_id == chat_id).delete(synchronize_session=False)
            results['message_logs'] = db.query(MessageLog).filter(MessageLog.chat_id == chat_id).delete(synchronize_session=False)
            
            # Затем остальные связанные таблицы
            results['spam_words'] = db.query(SpamWord).filter(SpamWord.chat_id == chat_id).delete(synchronize_session=False)
            results['spam_links'] = db.query(SpamLink).filter(SpamLink.chat_id == chat_id).delete(synchronize_session=False)
            results['statistics'] = db.query(Statistic).filter(Statistic.chat_id == chat_id).delete(synchronize_session=False)
            
            # Уведомления
            results['notification_messages'] = db.query(AdminNotificationMessage).filter(
                AdminNotificationMessage.chat_id == chat_id
            ).delete(synchronize_session=False)
            results['notifications'] = db.query(AdminNotification).filter(
                AdminNotification.original_chat_id == chat_id
            ).delete(synchronize_session=False)
            
            # Пользователи
            results['users'] = db.query(User).filter(User.chat_id == chat_id).delete(synchronize_session=False)
            
            # Сам чат в конце
            results['chats'] = db.query(Chat).filter(Chat.id == chat_id).delete(synchronize_session=False)
            
            # КРИТИЧНО: делаем commit
            db.commit()
            
            logger.info(f"[cleanup] ✅ chat {chat_id} deleted: {results}")
            return {"success": True, "deleted": results}
            
        except Exception as e:
            db.rollback()
            logger.error(f"[cleanup] ❌ Error deleting chat {chat_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def clean_pending_activations(self, chat_id: int, pending: Dict[int, Any]) -> int:
        """
        Удаляет ожидания активации для чата.
        """
        removed = [uid for uid, info in pending.items() if info.get("chat_id") == chat_id]
        for uid in removed:
            pending.pop(uid, None)
        logger.info(f"[cleanup] Removed {len(removed)} pending activations for chat {chat_id}")
        return len(removed)
