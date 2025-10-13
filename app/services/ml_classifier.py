# app/services/ml_classifier.py (правильная версия с исправленными regex)
import pickle
import logging
import re
from typing import Tuple, Dict, Any
from pathlib import Path

# Text Processing
import nltk
from nltk.corpus import stopwords


class MLSpamClassifier:
    """
    Классификатор спама для Telegram бота
    Использует ТОЧНО такую же предобработку как в оригинальном SpamClassifier
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, model_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, model_path: str = None):
        if self._initialized:
            return
            
        self.pipeline = None
        self.russian_stopwords = set()
        self.model_path = model_path
        self.is_loaded = False
        
        # Настройка логирования
        self.logger = logging.getLogger(__name__)
        
        # Инициализация NLTK ресурсов
        self._setup_nltk_resources()
        
        # Загрузка модели если указан путь
        if model_path and Path(model_path).exists():
            self.load_model(model_path)
            
        self._initialized = True
    
    def _setup_nltk_resources(self):
        """Загрузка необходимых ресурсов NLTK - ТОЧНО КАК В ОРИГИНАЛЕ"""
        try:
            nltk.download('stopwords', quiet=True)
            nltk.download('punkt', quiet=True)
            self.russian_stopwords = set(stopwords.words('russian'))
            self.logger.info("NLTK ресурсы загружены успешно")
        except Exception as e:
            self.logger.warning(f"Не удалось загрузить NLTK ресурсы: {e}")
            # Fallback к базовым русским стоп-словам - ТОЧНО КАК В ОРИГИНАЛЕ
            self.russian_stopwords = {
                'и', 'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как',
                'а', 'то', 'все', 'она', 'так', 'его', 'но', 'да', 'ты', 'к',
                'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'ее', 'мне', 'было',
                'или', 'от', 'при', 'до', 'из', 'для', 'об', 'под', 'над'
            }
    
    def preprocess_text(self, text: str) -> str:
        """
        Предобработка текста - ТОЧНАЯ КОПИЯ ИЗ ОРИГИНАЛЬНОГО SpamClassifier
        """
        if not isinstance(text, str):
            return ""
        
        # Приведение к нижнему регистру
        text = text.lower()
        
        # Удаление URL - ИСПРАВЛЕНО (правильный regex без лишних слэшей)
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', ' ', text)
        
        # Удаление email адресов - ИСПРАВЛЕНО
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', ' ', text)
        
        # Удаление телефонных номеров - ИСПРАВЛЕНО  
        text = re.sub(r'\+?[7-8][\s\-\(\)]?\d{3}[\s\-\(\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', ' ', text)
        
        # Удаление избыточной пунктуации и спецсимволов - ИСПРАВЛЕНО
        text = re.sub(r'[^\w\s\u0400-\u04FF]', ' ', text)
        
        # Удаление множественных пробелов - ИСПРАВЛЕНО
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Удаление стоп-слов - ТОЧНО КАК В ОРИГИНАЛЕ
        if self.russian_stopwords:
            words = text.split()
            words = [word for word in words if word not in self.russian_stopwords and len(word) > 2]
            text = ' '.join(words)
        
        return text
    
    def load_model(self, filepath: str):
        """Загрузка обученной модели"""
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Файл модели не найден: {filepath}")
        
        try:
            with open(filepath, 'rb') as f:
                self.pipeline = pickle.load(f)
            
            self.model_path = filepath
            self.is_loaded = True
            self.logger.info(f"Модель загружена: {filepath}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке модели: {e}")
            raise
    
    def predict(self, text: str) -> Tuple[bool, float]:
        """
        Предсказание для одного текста - ТОЧНО КАК В ОРИГИНАЛЕ
        """
        if not self.is_loaded:
            raise ValueError("Модель не загружена! Сначала загрузите модель.")
        
        processed_text = self.preprocess_text(text)
        if not processed_text:
            return False, 0.0
        
        try:
            # Получение вероятностей - ТОЧНО КАК В ОРИГИНАЛЕ
            probabilities = self.pipeline.predict_proba([processed_text])[0]
            spam_probability = probabilities[1] if len(probabilities) > 1 else 0.0
            
            is_spam = spam_probability > 0.5
            
            return is_spam, spam_probability
            
        except Exception as e:
            self.logger.error(f"Ошибка при предсказании: {e}")
            return False, 0.0
    
    def get_model_info(self) -> Dict[str, Any]:
        """Получение информации о загруженной модели"""
        if not self.is_loaded:
            return {
                "status": "not_loaded",
                "model_path": self.model_path
            }
        
        try:
            vectorizer = self.pipeline.named_steps['vectorizer']
            classifier = self.pipeline.named_steps['classifier']
            
            return {
                "status": "loaded",
                "model_type": type(classifier).__name__,
                "vectorizer_type": type(vectorizer).__name__,
                "vocabulary_size": len(vectorizer.vocabulary_) if hasattr(vectorizer, 'vocabulary_') else 0,
                "ngram_range": getattr(vectorizer, 'ngram_range', None),
                "max_features": getattr(vectorizer, 'max_features', None),
                "alpha": getattr(classifier, 'alpha', None),
                "model_path": self.model_path
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении информации о модели: {e}")
            return {
                "status": "error",
                "error": str(e),
                "model_path": self.model_path
            }
    
    def is_ready(self) -> bool:
        """Проверка готовности классификатора к работе"""
        return self.is_loaded and self.pipeline is not None
