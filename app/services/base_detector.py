# app/services/base_detector.py
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.orm import Session


@dataclass
class SpamDetectionResult:
    """Результат детекции спама"""
    is_spam: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    detector_name: str


class BaseSpamDetector(ABC):
    """Базовый класс для всех детекторов спама"""
    
    @abstractmethod
    async def detect(self, message, chat_settings, db_session: Session = None) -> Optional[SpamDetectionResult]:
        """
        Анализ сообщения на спам
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата
            db_session: Сессия базы данных (опционально)
            
        Returns:
            SpamDetectionResult или None если спам не обнаружен
        """
        pass