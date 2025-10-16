# models/admin_notification.py
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base

class AdminNotification(Base):
    __tablename__ = "admin_notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    original_chat_id = Column(BigInteger, nullable=False)
    original_message_id = Column(BigInteger, nullable=False)
    event_type = Column(String(50), nullable=False)
    event_data = Column(Text)  # JSON данные
    is_processed = Column(Boolean, default=False)
    processed_by = Column(BigInteger)
    processed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    
    # Связь с сообщениями админов
    messages = relationship("AdminNotificationMessage", back_populates="notification")

class AdminNotificationMessage(Base):
    __tablename__ = "admin_notification_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    admin_notification_id = Column(Integer, ForeignKey("admin_notifications.id"), nullable=False)
    admin_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Связь с уведомлением
    notification = relationship("AdminNotification", back_populates="messages")
