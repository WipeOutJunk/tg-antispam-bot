from sqlalchemy import Column, Integer, String, BigInteger, DateTime
from datetime import datetime
from .base import Base


class AllowedAdder(Base):
    """
    Модель для хранения пользователей, которым разрешено добавлять бота в чаты.
    Пользователи попадают в эту таблицу после успешного ввода секретного слова.
    """
    __tablename__ = "allowed_adders"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True, comment="ID пользователя в Telegram")
    username = Column(String(128), nullable=True, comment="Username пользователя в Telegram")
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="Дата и время активации")
    
    def __repr__(self):
        return f"<AllowedAdder(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"
