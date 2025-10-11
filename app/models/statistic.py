from sqlalchemy.orm import  relationship
from sqlalchemy import ForeignKey, Column , Integer,  DateTime, Text
from .base import Base

class Statistic(Base):
    __tablename__ = "statistic"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chat.id"))
    date = Column(DateTime)
    total_messages = Column(Integer)
    total_spam = Column(Integer)
    total_warnings = Column(Integer)
    total_bans = Column(Integer)

    chat = relationship("Chat", back_populates="statistics")
