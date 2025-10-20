from sqlalchemy import Column, Integer, Text, TIMESTAMP, func
from .base import Base

class ProfanityWord(Base):
    __tablename__ = 'profanity_words'

    id = Column(Integer, primary_key=True, index=True)
    word = Column(Text, unique=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
