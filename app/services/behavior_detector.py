# app/services/behavior_detector.py
import logging
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models.message_log import MessageLog
from .base_detector import SpamDetectionResult


class BehaviorDetector:
    """
    Детектор аномального поведения (F1.4)
    
    Функции:
    - Детекция флуда (много сообщений за короткое время)
    - Анализ капслока
    - Обнаружение повторяющихся сообщений
    - Отслеживание паттернов поведения пользователей
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.detector_name = "BehaviorDetector"
        
        # Настройки детекции
        self.flood_threshold = 5  # сообщений
        self.flood_window = 30    # секунд
        self.caps_threshold = 0.7 # 70% заглавных букв
        self.min_text_length = 10 # минимальная длина для анализа капса
        self.duplicate_window = 300  # секунд для поиска дубликатов
    
    async def detect(self, message, chat_settings, db_session: Session) -> Optional[SpamDetectionResult]:
        """
        Анализ поведения пользователя
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата
            db_session: Сессия БД
            
        Returns:
            SpamDetectionResult или None если нарушений не обнаружено
        """
        user_id = message.from_user.id
        chat_id = message.chat.id
        text = self._extract_text(message)
        
        # Проверка флуда
        flood_result = await self._check_flood(db_session, user_id, chat_id)
        if flood_result:
            return flood_result
        
        # Проверка капслока
        if text:
            caps_result = self._check_caps_lock(text)
            if caps_result:
                return caps_result
            
            # Проверка повторяющихся сообщений
            duplicate_result = await self._check_duplicate_messages(
                db_session, user_id, chat_id, text
            )
            if duplicate_result:
                return duplicate_result
        
        return None
    
    async def _check_flood(self, db: Session, user_id: int, chat_id: int) -> Optional[SpamDetectionResult]:
        """Проверка на флуд"""
        try:
            # Получаем количество сообщений пользователя за последние N секунд
            time_threshold = datetime.now() - timedelta(seconds=self.flood_window)
            
            message_count = db.query(MessageLog).filter(
                MessageLog.user_id == user_id,
                MessageLog.chat_id == chat_id,
                MessageLog.created_at >= time_threshold
            ).count()
            
            if message_count >= self.flood_threshold:
                confidence = min(0.5 + (message_count - self.flood_threshold) * 0.1, 1.0)
                
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=confidence,
                    reason=f"Флуд: {message_count} сообщений за {self.flood_window} секунд",
                    detector_name=self.detector_name
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке флуда: {e}")
            return None
    
    def _check_caps_lock(self, text: str) -> Optional[SpamDetectionResult]:
        """Проверка на чрезмерное использование ЗАГЛАВНЫХ БУКВ"""
        if len(text) < self.min_text_length:
            return None
        
        # Подсчитываем буквы (исключая цифры и символы)
        letters = [c for c in text if c.isalpha()]
        if len(letters) < self.min_text_length:
            return None
        
        # Процент заглавных букв
        caps_count = sum(1 for c in letters if c.isupper())
        caps_ratio = caps_count / len(letters)
        
        if caps_ratio >= self.caps_threshold:
            confidence = min(0.4 + (caps_ratio - self.caps_threshold) * 0.5, 0.9)
            
            return SpamDetectionResult(
                is_spam=True,
                confidence=confidence,
                reason=f"Злоупотребление капслоком: {caps_ratio:.0%} заглавных букв",
                detector_name=self.detector_name
            )
        
        return None
    
    async def _check_duplicate_messages(
        self, db: Session, user_id: int, chat_id: int, text: str
    ) -> Optional[SpamDetectionResult]:
        """Проверка на повторяющиеся сообщения"""
        if len(text.strip()) < 5:  # Слишком короткий текст
            return None
        
        try:
            # Ищем похожие сообщения за последние N минут
            time_threshold = datetime.now() - timedelta(seconds=self.duplicate_window)
            
            # Нормализуем текст для сравнения
            normalized_text = self._normalize_text(text)
            
            similar_messages = db.query(MessageLog).filter(
                MessageLog.user_id == user_id,
                MessageLog.chat_id == chat_id,
                MessageLog.created_at >= time_threshold,
                MessageLog.content.ilike(f"%{normalized_text[:50]}%")  # Первые 50 символов
            ).all()
            
            # Подсчитываем точные совпадения
            exact_matches = 0
            similar_matches = 0
            
            for msg in similar_messages:
                if not msg.content:
                    continue
                
                msg_normalized = self._normalize_text(msg.content)
                similarity = self._calculate_text_similarity(normalized_text, msg_normalized)
                
                if similarity > 0.9:
                    exact_matches += 1
                elif similarity > 0.7:
                    similar_matches += 1
            
            # Определяем, является ли это спамом
            if exact_matches >= 2:  # 2 или более точных копий
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=0.8,
                    reason=f"Повторяющиеся сообщения: {exact_matches} копий",
                    detector_name=self.detector_name
                )
            
            if similar_matches >= 3:  # 3 или более похожих сообщения
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=0.6,
                    reason=f"Похожие сообщения: {similar_matches} вариантов",
                    detector_name=self.detector_name
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке дубликатов: {e}")
            return None
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста для сравнения"""
        import re
        
        # Приводим к нижнему регистру
        text = text.lower()
        
        # Удаляем лишние пробелы и символы
        text = re.sub(r'[^\\w\\s\\u0400-\\u04FF]', ' ', text)
        text = re.sub(r'\\s+', ' ', text)
        
        return text.strip()
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Расчет схожести двух текстов"""
        if not text1 or not text2:
            return 0.0
        
        # Простой алгоритм схожести на основе общих слов
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def _extract_text(self, message) -> str:
        """Извлечение текста из сообщения"""
        text = ""
        if hasattr(message, 'text') and message.text:
            text = message.text
        elif hasattr(message, 'caption') and message.caption:
            text = message.caption
        return text.strip()
    
    async def log_user_activity(self, db: Session, message):
        """Логирование активности пользователя для анализа поведения"""
        try:
            from datetime import datetime
            
            log_entry = MessageLog(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                message_id=message.message_id,
                content=self._extract_text(message)[:500],  # Ограничиваем длину
                is_spam=False,  # Будет обновлено после анализа
                created_at=datetime.now()
            )
            
            db.add(log_entry)
            db.commit()
            
        except Exception as e:
            self.logger.error(f"Ошибка при логировании активности: {e}")