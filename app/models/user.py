from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Column, Integer, Text, Boolean, ForeignKey, DateTime, UniqueConstraint
from .base import Base


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint('telegram_id', 'chat_id', name='ix_user_telegram_chat'),
    )
    id           = Column(Integer, primary_key=True)
    telegram_id  = Column(Integer, nullable=False)
    username     = Column(Text)
    joined_at    = Column(DateTime)
    is_admin     = Column(Boolean, default=False)
    is_banned    = Column(Boolean, default=False)
    chat_id      = Column(Integer, ForeignKey("chat.id"))

    chat         = relationship("Chat", back_populates="users")
    warnings     = relationship("Warning", back_populates="user")
    bans         = relationship("Ban", back_populates="user")
    messages     = relationship("MessageLog", back_populates="user")