# app/models/chat.py

from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, Text, DateTime
from .base import Base

class Chat(Base):
    __tablename__ = "chat"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(Text)
    sensitivity = Column(Integer)
    warn_limit = Column(Integer)
    quarantine_hours = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    
    # Relationships с CASCADE DELETE
    users = relationship(
        "User", 
        back_populates="chat",
        cascade="all, delete-orphan"  
    )
    
    warnings = relationship(
        "Warning", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
    bans = relationship(
        "Ban", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
    spam_words = relationship(
        "SpamWord", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
    spam_links = relationship(
        "SpamLink", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
    messages = relationship(
        "MessageLog", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
    statistics = relationship(
        "Statistic", 
        back_populates="chat",
        cascade="all, delete-orphan"
    )
