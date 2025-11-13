
from typing import Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import pickle


@dataclass
class SpamDetectionResult:
    """Результат классификации спама"""
    is_spam: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    detector_name: str
    classifier_type: str = "unknown"
    timestamp: datetime = None


class BayesSpamDetector:
    """
    Детектор спама на основе ML-модели (SVM/Logistic/SGD/NB)
    
    Совместим с существующим SpamAnalyzer
    Внутри использует обученную SVM модель (98.95% точность)
    """
    
    def __init__(self, model_path: str):
        """
        Args:
            model_path: Путь к обученной модели (.pkl)
        """
        self.model_path = Path(model_path)
        self.pipeline = None
        self.classifier_type = "unknown"
        self._is_ready = False
        self.logger = logging.getLogger(__name__)
        
        # Статистика
        self.stats = {
            'total_predictions': 0,
            'spam_detected': 0,
            'ham_detected': 0,
            'avg_confidence': 0.0
        }
        
        # Загружаем модель
        self._load_model()
    
    def _load_model(self):
        """Загрузка модели из файла"""
        try:
            if not self.model_path.exists():
                raise FileNotFoundError(f"Модель не найдена: {self.model_path}")
            
            with open(self.model_path, 'rb') as f:
                self.pipeline = pickle.load(f)
            
            # Определяем тип классификатора
            classifier = self.pipeline.named_steps['classifier']
            self.classifier_type = type(classifier).__name__
            self._is_ready = True
            
            self.logger.info(
                f"✅ ML модель загружена: {self.classifier_type} "
                f"из {self.model_path}"
            )
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки модели: {e}")
            self._is_ready = False
            raise
    
    async def detect(self, message, chat_settings) -> Optional[SpamDetectionResult]:
        """
        Анализ сообщения на спам
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата
        
        Returns:
            SpamDetectionResult если спам, иначе None
        """
        try:
            if not self._is_ready:
                self.logger.warning("Детектор не готов")
                return None
            
            # Извлечение текста
            text = self._extract_text(message)
            if not text or len(text.strip()) < 2:
                return None
            
            # Минимум 4 слова
            if len(text.split()) < 4:
                return None
            
            # Предсказание
            is_spam, confidence = self._predict(text)
            
            # Применяем чувствительность
            sensitivity = getattr(chat_settings, 'sensitivity', 5) if chat_settings else 5
            threshold = self._calculate_threshold(sensitivity)
            
            # Финальное решение
            final_is_spam = is_spam and confidence >= threshold
            
            # Обновляем статистику
            self._update_stats(final_is_spam, confidence)
            
            if final_is_spam:
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=confidence,
                    reason=f"{self.classifier_type}: {confidence:.1%} уверенности",
                    detector_name="BayesClassifier",  # Для совместимости с SpamAnalyzer
                    classifier_type=self.classifier_type,
                    timestamp=datetime.now()
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка детекции: {e}")
            return None
    
    def _predict(self, text: str) -> tuple:
        """
        Предсказание
        
        Returns:
            (is_spam, confidence)
        """
        try:
            # Пробуем predict_proba (для NB, LR)
            try:
                probabilities = self.pipeline.predict_proba([text])[0]
                spam_probability = probabilities[1]
            except AttributeError:
                # Для SVM используем decision_function с sigmoid
                import numpy as np
                decision = self.pipeline.decision_function([text])[0]
                spam_probability = 1 / (1 + np.exp(-decision))
            
            is_spam = spam_probability > 0.5
            return is_spam, float(spam_probability)
            
        except Exception as e:
            self.logger.error(f"Ошибка предсказания: {e}")
            return False, 0.0
    
    def _extract_text(self, message) -> str:
        """Извлечение текста из сообщения"""
        try:
            if hasattr(message, 'text') and message.text:
                return message.text
            elif hasattr(message, 'caption') and message.caption:
                return message.caption
            return ""
        except Exception as e:
            self.logger.error(f"Ошибка извлечения текста: {e}")
            return ""
    
    def _calculate_threshold(self, sensitivity: int) -> float:
        """
        Порог на основе чувствительности
        
        sensitivity 1 = 0.8 (строгий)
        sensitivity 5 = 0.55 (средний)
        sensitivity 10 = 0.3 (мягкий)
        """
        sensitivity = max(1, min(10, sensitivity))
        threshold = 0.8 - (sensitivity - 1) * 0.05
        return max(0.3, min(0.8, threshold))
    
    def _update_stats(self, is_spam: bool, confidence: float):
        """Обновление статистики"""
        self.stats['total_predictions'] += 1
        if is_spam:
            self.stats['spam_detected'] += 1
        else:
            self.stats['ham_detected'] += 1
        
        # Running average
        current_avg = self.stats['avg_confidence']
        total = self.stats['total_predictions']
        self.stats['avg_confidence'] = (
            (current_avg * (total - 1) + confidence) / total
        )
    
    def get_model_info(self) -> dict:
        """Информация о модели"""
        if not self._is_ready:
            return {"status": "not_ready"}
        
        try:
            vectorizer = self.pipeline.named_steps['vectorizer']
            classifier = self.pipeline.named_steps['classifier']
            
            return {
                'status': 'ready',
                'classifier_type': self.classifier_type,
                'vectorizer_type': type(vectorizer).__name__,
                'vocabulary_size': len(vectorizer.vocabulary_) if hasattr(vectorizer, 'vocabulary_') else 0,
                'ngram_range': vectorizer.ngram_range if hasattr(vectorizer, 'ngram_range') else None,
                'max_features': vectorizer.max_features if hasattr(vectorizer, 'max_features') else None,
                'model_path': str(self.model_path)
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения инфо: {e}")
            return {"status": "error", "error": str(e)}
    
    def is_ready(self) -> bool:
        """Готовность детектора"""
        return self._is_ready