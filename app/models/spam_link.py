from sqlalchemy.orm import  relationship
from sqlalchemy import Column, Integer, Text, DATETIME, ForeignKey
from .base import Base

class SpamLink(Base):
    __tablename__ = "spam_link"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chat.id"))
    pattern = Column(Text)
    added_by = Column(Integer) # id админа который добавил слово
    added_at = Column(DATETIME)

    chat = relationship("Chat", back_populates="spam_links")