from sqlalchemy.orm import relationship
from sqlalchemy import DateTime, Column, Integer, Text, ForeignKey
from .base import Base


class Ban(Base):
    __tablename__ = "ban"

    id = Column(Integer , primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"))
    chat_id = Column(Integer, ForeignKey("chat.id"))
    action = Column(Text)
    reason = Column(Text)
    issued_at = Column(DateTime)
    expires_at = Column(DateTime)

    user       = relationship("User", back_populates="bans")
    chat       = relationship("Chat", back_populates="bans")
    