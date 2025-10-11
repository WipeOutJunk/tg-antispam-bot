from sqlalchemy.orm import  relationship
from sqlalchemy import DateTime, Column, Integer, Text, ForeignKey
from .base import Base

class Warning(Base):
    __tablename__ = "warning"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("user.id"))
    chat_id    = Column(Integer, ForeignKey("chat.id"))
    reason     = Column(Text)
    issued_at  = Column(DateTime)

    user       = relationship("User", back_populates="warnings")
    chat       = relationship("Chat", back_populates="warnings")

