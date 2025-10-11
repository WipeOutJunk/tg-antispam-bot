from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey, Column, Integer, Text, Boolean, DateTime
from .base import Base

class MessageLog(Base):
    __tablename__ = "message_log"

    id          = Column(Integer, primary_key=True, index=True)
    chat_id     = Column(Integer, ForeignKey("chat.id"))
    user_id     = Column(Integer, ForeignKey("user.id"))
    message_id  = Column(Integer)
    content     = Column(Text)
    is_spam     = Column(Boolean)
    created_at  = Column(DateTime)

    chat        = relationship("Chat", back_populates="messages")
    user        = relationship("User", back_populates="messages")
