# app/services/bayes_spam_detector.py
from typing import Optional
from dataclasses import dataclass
from .ml_classifier import MLSpamClassifier

@dataclass
class SpamDetectionResult:
    is_spam: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    detector_name: str


class BayesSpamDetector:
    """
    Детектор спама на основе байесовского классификатора
    
    Интегрируется с системой анти-спам бота и использует
    предобученную ML-модель для определения спама
    """
    
    def __init__(self, model_path: str):
        self.classifier = MLSpamClassifier(model_path)
        self.detector_name = "BayesClassifier"
        
        if not self.classifier.is_ready():
            raise ValueError(f"Не удалось загрузить модель из {model_path}")
    
    async def detect(self, message, chat_settings) -> Optional[SpamDetectionResult]:
        """
        Анализ сообщения на спам с помощью ML-модели
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата
            
        Returns:
            SpamDetectionResult или None если не спам
        """
        # Получаем текст из сообщения
        text = self._extract_text(message)
        if not text:
            return None
        
        # Классификация
        is_spam, confidence = self.classifier.predict(text)
        
        # Применяем чувствительность чата
        sensitivity_threshold = self._calculate_threshold(chat_settings.sensitivity)
        
        # Финальное решение на основе чувствительности
        final_is_spam = is_spam and confidence >= sensitivity_threshold
        
        if final_is_spam:
            return SpamDetectionResult(
                is_spam=True,
                confidence=confidence,
                reason=f"Байесовский классификатор: {confidence:.1%} уверенности",
                detector_name=self.detector_name
            )
        
        return None
    
    def _extract_text(self, message) -> str:
        """Извлечение текста из Telegram сообщения"""
        if hasattr(message, 'text') and message.text:
            return message.text
        elif hasattr(message, 'caption') and message.caption:
            return message.caption
        return ""
    
    def _calculate_threshold(self, sensitivity: int) -> float:
        """
        Расчет порога срабатывания на основе чувствительности чата
        
        Args:
            sensitivity: Чувствительность от 1 до 10
            
        Returns:
            Порог от 0.3 до 0.8
        """
        # Чувствительность 1 = порог 0.8 (очень строго)
        # Чувствительность 10 = порог 0.3 (менее строго)
        return 0.8 - (sensitivity - 1) * 0.05
    
    def get_model_info(self) -> dict:
        """Получение информации о загруженной модели"""
        return self.classifier.get_model_info()
    
    def is_ready(self) -> bool:
        """Проверка готовности детектора"""
        return self.classifier.is_ready()