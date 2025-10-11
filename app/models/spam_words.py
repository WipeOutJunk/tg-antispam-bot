from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy import Column, ForeignKey, Integer, Text, DATETIME
from .base import Base

class SpamWord(Base): 
    __tablename__ = "spam_word"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chat.id"))
    word = Column(Text)
    added_by = Column(Integer) # id админа который добавил слово
    added_at = Column(DATETIME)

    chat = relationship("Chat", back_populates="spam_words")