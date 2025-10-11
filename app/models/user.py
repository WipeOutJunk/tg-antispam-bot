from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Column, Integer, Text, Boolean, ForeignKey, DateTime
from .base import Base


class User(Base):
    __tablename__ = "user"
    id           = Column(Integer, primary_key=True, index=True)
    telegram_id  = Column(Integer, unique=True, index=True)
    username     = Column(Text)
    joined_at    = Column(DateTime)
    is_admin     = Column(Boolean, default=False)
    is_banned    = Column(Boolean, default=False)
    chat_id      = Column(Integer, ForeignKey("chat.id"))

    chat         = relationship("Chat", back_populates="users")
    warnings     = relationship("Warning", back_populates="user")
    bans         = relationship("Ban", back_populates="user")
    messages     = relationship("MessageLog", back_populates="user")