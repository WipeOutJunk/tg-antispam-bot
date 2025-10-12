# app/services/spam_analyzer.py (обновленная версия)
from typing import List, Optional
from .bayes_spam_detector import BayesSpamDetector
from .link_spam_detector import LinkSpamDetector  
from .base_detector import SpamDetectionResult
import logging


class SpamAnalyzer:
    """
    Координатор спам-детекторов
    
    Анализирует сообщения через:
    - ML-классификатор (F1.1 - ключевые слова через обученную модель)
    - Детектор ссылок (F1.2 - проверка доменов)
    """
    
    def __init__(self, model_path: str):
        self.logger = logging.getLogger(__name__)
        
        # Инициализация детекторов
        try:
            self.bayes_detector = BayesSpamDetector(model_path)
            self.link_detector = LinkSpamDetector()
            
            self.detectors = [
                self.bayes_detector,    # Главный ML-детектор (F1.1)
                self.link_detector,     # Проверка ссылок (F1.2)
            ]
            
            self.logger.info(f"Спам-анализатор инициализирован с {len(self.detectors)} детекторами")
            
        except Exception as e:
            self.logger.error(f"Ошибка инициализации спам-анализатора: {e}")
            raise
    
    async def analyze_message(self, message, chat_settings, db_session) -> List[SpamDetectionResult]:
        """
        Анализ сообщения на спам
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата из БД
            db_session: Сессия базы данных
            
        Returns:
            Список результатов детекции спама
        """
        results = []
        
        # Проходим по всем детекторам
        for detector in self.detectors:
            try:
                if detector == self.bayes_detector:
                    # ML-детектор не нуждается в БД
                    result = await detector.detect(message, chat_settings)
                else:
                    # Детектор ссылок использует БД для черного списка
                    result = await detector.detect(message, chat_settings, db_session)
                
                if result and result.is_spam:
                    results.append(result)
                    
                    # Если ML-классификатор определил спам с высокой уверенностью,
                    # можно не запускать остальные детекторы для экономии ресурсов
                    if (detector == self.bayes_detector and 
                        result.confidence > 0.8):
                        self.logger.info(f"ML-детектор определил спам с высокой уверенностью: {result.confidence:.1%}")
                        break
                        
            except Exception as e:
                self.logger.error(f"Ошибка в детекторе {detector.__class__.__name__}: {e}")
                continue
        
        return results
    
    def is_spam(self, results: List[SpamDetectionResult], chat_settings) -> bool:
        """
        Итоговое решение: является ли сообщение спамом
        
        Args:
            results: Результаты всех детекторов
            chat_settings: Настройки чата
            
        Returns:
            True если сообщение нужно считать спамом
        """
        if not results:
            return False
        
        # Если ML-классификатор определил спам - доверяем ему
        for result in results:
            if result.detector_name == "BayesClassifier":
                return True
        
        # Если ML не сработал, но сработал детектор ссылок
        if results:
            return self._combined_decision(results, chat_settings)
        
        return False
    
    def _combined_decision(self, results: List[SpamDetectionResult], chat_settings) -> bool:
        """
        Комбинированное решение на основе детекторов
        
        Args:
            results: Результаты детекторов (без ML)
            chat_settings: Настройки чата
            
        Returns:
            True если считаем спамом
        """
        # Если детектор ссылок нашел спам-домен с высокой уверенностью - блокируем
        for result in results:
            if result.detector_name == "LinkSpamDetector" and result.confidence >= 0.8:
                return True
        
        # Для менее уверенных результатов учитываем чувствительность чата
        if results:
            # Высокая чувствительность = низкий порог
            threshold = 0.9 - (chat_settings.sensitivity / 10) * 0.3  # от 0.6 до 0.8
            return max(r.confidence for r in results) >= threshold
        
        return False
    
    def get_detection_summary(self, results: List[SpamDetectionResult]) -> str:
        """
        Формирование краткого описания причин детекции спама
        
        Args:
            results: Результаты детекторов
            
        Returns:
            Строка с описанием причин
        """
        if not results:
            return "Спам не обнаружен"
        
        summary_parts = []
        for result in results:
            summary_parts.append(f"{result.detector_name}: {result.reason}")
        
        return "; ".join(summary_parts)
    
    def get_model_info(self) -> dict:
        """Получение информации о ML-модели"""
        return self.bayes_detector.get_model_info()
    
    def is_ready(self) -> bool:
        """Проверка готовности анализатора к работе"""
        return self.bayes_detector.is_ready()