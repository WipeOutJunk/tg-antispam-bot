# app/services/link_spam_detector.py
import re
import logging
from typing import Optional, List
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from ..models.spam_link import SpamLink
from .base_detector import SpamDetectionResult


class LinkSpamDetector:
    """
    Детектор спам-ссылок (F1.2)
    
    Функции:
    - Извлечение ссылок из сообщений
    - Проверка доменов против черного списка
    - Анализ подозрительных URL-паттернов
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.detector_name = "LinkSpamDetector"
        
        # Регулярные выражения для поиска ссылок
        self.url_patterns = [
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r'(?:www\\.)?[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\\.[a-zA-Z]{2,}',
            r'[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\\.(ru|com|org|net|info|biz|tk|ml|ga|cf)(?:/\\S*)?'
        ]
        
        # Подозрительные паттерны в доменах
        self.suspicious_patterns = [
            r'\\d{4,}',  # Много цифр подряд
            r'[a-z]{20,}',  # Очень длинные случайные строки
            r'(bit\\.ly|tinyurl|short|redirect)',  # Сокращатели ссылок
            r'(free|win|prize|money|cash|earn)',  # Подозрительные слова
        ]
    
    async def detect(self, message, chat_settings, db_session: Session) -> Optional[SpamDetectionResult]:
        """
        Анализ сообщения на наличие спам-ссылок
        
        Args:
            message: Telegram сообщение
            chat_settings: Настройки чата
            db_session: Сессия БД
            
        Returns:
            SpamDetectionResult или None если спам не обнаружен
        """
        text = self._extract_text(message)
        if not text:
            return None
        
        # Извлекаем все ссылки из текста
        links = self._extract_links(text)
        if not links:
            return None
        
        # Проверяем каждую ссылку
        for link in links:
            domain = self._extract_domain(link)
            if not domain:
                continue
            
            # Проверка в черном списке
            if await self._is_blacklisted_domain(db_session, domain, message.chat.id):
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=0.95,
                    reason=f"Домен в черном списке: {domain}",
                    detector_name=self.detector_name
                )
            
            # Эвристическая проверка подозрительности
            suspicion_score = self._calculate_suspicion_score(link, domain)
            if suspicion_score > 0.7:
                return SpamDetectionResult(
                    is_spam=True,
                    confidence=suspicion_score,
                    reason=f"Подозрительная ссылка: {domain}",
                    detector_name=self.detector_name
                )
        
        return None
    
    def _extract_text(self, message) -> str:
        """Извлечение текста из сообщения"""
        text = ""
        if hasattr(message, 'text') and message.text:
            text += message.text
        if hasattr(message, 'caption') and message.caption:
            text += " " + message.caption
        return text.strip()
    
    def _extract_links(self, text: str) -> List[str]:
        """Извлечение всех ссылок из текста"""
        links = []
        
        for pattern in self.url_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            links.extend(matches)
        
        # Удаляем дубликаты и нормализуем
        unique_links = []
        for link in links:
            normalized = self._normalize_url(link)
            if normalized and normalized not in unique_links:
                unique_links.append(normalized)
        
        return unique_links
    
    def _normalize_url(self, url: str) -> str:
        """Нормализация URL"""
        url = url.strip()
        
        # Добавляем протокол если отсутствует
        if not url.startswith(('http://', 'https://')):
            if url.startswith('www.'):
                url = 'http://' + url
            else:
                url = 'http://' + url
        
        return url
    
    def _extract_domain(self, url: str) -> str:
        """Извлечение домена из URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Убираем www.
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain
        except:
            return ""
    
    async def _is_blacklisted_domain(self, db: Session, domain: str, chat_id: int) -> bool:
        """Проверка домена в черном списке чата"""
        try:
            # Проверяем точное совпадение
            exact_match = db.query(SpamLink).filter(
                SpamLink.chat_id == chat_id,
                SpamLink.pattern == domain
            ).first()
            
            if exact_match:
                return True
            
            # Проверяем паттерны с wildcard
            patterns = db.query(SpamLink).filter(
                SpamLink.chat_id == chat_id
            ).all()
            
            for pattern_obj in patterns:
                pattern = pattern_obj.pattern
                if '*' in pattern:
                    # Преобразуем wildcard в regex
                    regex_pattern = pattern.replace('*', '.*')
                    if re.match(regex_pattern, domain):
                        return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке черного списка: {e}")
            return False
    
    def _calculate_suspicion_score(self, url: str, domain: str) -> float:
        """Расчет подозрительности ссылки"""
        score = 0.0
        
        # Проверяем подозрительные паттерны в домене
        for pattern in self.suspicious_patterns:
            if re.search(pattern, domain, re.IGNORECASE):
                score += 0.3
        
        # Длина URL
        if len(url) > 100:
            score += 0.2
        
        # Количество поддоменов
        subdomain_count = domain.count('.')
        if subdomain_count > 3:
            score += 0.2
        
        # IP-адрес вместо домена
        if re.match(r'^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}', domain):
            score += 0.4
        
        # Нестандартный порт
        if ':' in domain and not domain.endswith(':80') and not domain.endswith(':443'):
            score += 0.3
        
        return min(score, 1.0)
    
    async def add_to_blacklist(self, db: Session, chat_id: int, pattern: str, added_by: int):
        """Добавление домена/паттерна в черный список"""
        from datetime import datetime
        
        try:
            spam_link = SpamLink(
                chat_id=chat_id,
                pattern=pattern.lower(),
                added_by=added_by,
                added_at=datetime.now()
            )
            
            db.add(spam_link)
            db.commit()
            
            self.logger.info(f"Добавлен в черный список: {pattern} для чата {chat_id}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении в черный список: {e}")
            db.rollback()
            raise
    
    async def remove_from_blacklist(self, db: Session, chat_id: int, pattern: str):
        """Удаление из черного списка"""
        try:
            spam_link = db.query(SpamLink).filter(
                SpamLink.chat_id == chat_id,
                SpamLink.pattern == pattern.lower()
            ).first()
            
            if spam_link:
                db.delete(spam_link)
                db.commit()
                self.logger.info(f"Удален из черного списка: {pattern} для чата {chat_id}")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Ошибка при удалении из черного списка: {e}")
            db.rollback()
            raise