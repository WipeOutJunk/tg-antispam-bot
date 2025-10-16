import json
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from ..models.admin_notification import AdminNotification, AdminNotificationMessage

class AdminNotificationsService:
    
    @staticmethod
    async def create_admin_notification(
        db: Session,
        original_chat_id: int,
        original_message_id: int,
        event_type: str,
        event_data: dict = None
    ) -> AdminNotification:
        """Создает новое админское уведомление"""
        notification = AdminNotification(
            original_chat_id=original_chat_id,
            original_message_id=original_message_id,
            event_type=event_type,
            event_data=json.dumps(event_data) if event_data else None
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification
    
    @staticmethod
    async def add_admin_message(
        db: Session,
        notification_id: int,
        admin_id: int,
        message_id: int
    ) -> AdminNotificationMessage:
        """Добавляет сообщение админа к уведомлению"""
        admin_message = AdminNotificationMessage(
            admin_notification_id=notification_id,
            admin_id=admin_id,
            message_id=message_id,
            chat_id=admin_id  # для личных сообщений chat_id = admin_id
        )
        db.add(admin_message)
        db.commit()
        db.refresh(admin_message)
        return admin_message
    
    @staticmethod
    async def process_notification(
        db: Session,
        original_chat_id: int,
        original_message_id: int,
        event_type: str,
        processed_by: int
    ) -> Optional[AdminNotification]:
        """Помечает уведомление как обработанное и возвращает его"""
        notification = db.query(AdminNotification).filter(
            and_(
                AdminNotification.original_chat_id == original_chat_id,
                AdminNotification.original_message_id == original_message_id,
                AdminNotification.event_type == event_type,
                AdminNotification.is_processed == False
            )
        ).first()
        
        if notification:
            notification.is_processed = True
            notification.processed_by = processed_by
            notification.processed_at = datetime.utcnow()
            db.commit()
            return notification
        return None
    
    @staticmethod
    async def get_undeleted_messages(
        db: Session,
        notification_id: int,
        exclude_admin_id: int = None
    ) -> List[AdminNotificationMessage]:
        """Получает все неудаленные сообщения уведомления (кроме указанного админа)"""
        query = db.query(AdminNotificationMessage).filter(
            and_(
                AdminNotificationMessage.admin_notification_id == notification_id,
                AdminNotificationMessage.is_deleted == False
            )
        )
        
        if exclude_admin_id:
            query = query.filter(AdminNotificationMessage.admin_id != exclude_admin_id)
        
        return query.all()
    
    @staticmethod
    async def mark_messages_as_deleted(
        db: Session,
        message_ids: List[int]
    ):
        """Помечает сообщения как удаленные"""
        if message_ids:
            db.query(AdminNotificationMessage).filter(
                AdminNotificationMessage.id.in_(message_ids)
            ).update({"is_deleted": True})
            db.commit()
    
    @staticmethod
    async def cleanup_old_notifications(
        db: Session,
        days_old: int = 7
    ):
        """Удаляет старые уведомления"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Сначала удаляем связанные сообщения
        db.query(AdminNotificationMessage).filter(
            AdminNotificationMessage.admin_notification_id.in_(
                db.query(AdminNotification.id).filter(
                    AdminNotification.created_at < cutoff_date
                )
            )
        ).delete(synchronize_session=False)
        
        # Затем удаляем сами уведомления
        deleted_count = db.query(AdminNotification).filter(
            AdminNotification.created_at < cutoff_date
        ).delete()
        
        db.commit()
        return deleted_count