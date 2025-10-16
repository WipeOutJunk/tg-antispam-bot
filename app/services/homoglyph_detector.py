
import re
import logging
import unicodedata
from typing import Dict, List, Set, Tuple, Optional
from urllib.parse import urlparse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class HomoglyphDetector:
    """
    Детектор гомоглифов для русского и английского языков
    
    Основные функции:
    - Обнаружение поддельных доменов с гомоглифами
    - Проверка смешивания кириллицы и латиницы
    - Защита от фишинговых ссылок
    - Настраиваемая чувствительность для разных чатов
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Карта гомоглифов: кириллица → латиница
        self.cyrillic_to_latin = {
            'а': 'a',    # cyrillic а → latin a
            'о': 'o',    # cyrillic о → latin o  
            'р': 'p',    # cyrillic р → latin p
            'с': 'c',    # cyrillic с → latin c
            'е': 'e',    # cyrillic е → latin e
            'х': 'x',    # cyrillic х → latin x
            'у': 'y',    # cyrillic у → latin y
            'к': 'k',    # cyrillic к → latin k
            'м': 'm',    # cyrillic м → latin m
            'н': 'h',    # cyrillic н → latin h
            'т': 't',    # cyrillic т → latin t
            'в': 'b',    # cyrillic в → latin b
            'і': 'i',    # cyrillic і → latin i (украинский)
            'ј': 'j',    # cyrillic ј → latin j
        }
        
        # Обратная карта: латиница → кириллица
        self.latin_to_cyrillic = {v: k for k, v in self.cyrillic_to_latin.items()}
        
        # Популярные домены для защиты от фишинга
        self.protected_domains = {
            'google', 'yandex', 'mail', 'vk', 'ok', 'telegram',
            'whatsapp', 'instagram', 'facebook', 'youtube', 'github',
            'amazon', 'ebay', 'paypal', 'apple', 'microsoft', 'steam',
            'sberbank', 'tinkoff', 'alfabank', 'vtb', 'gazprombank',
            'gosuslugi', 'mos', 'spb', 'avito', 'ozon', 'wildberries'
        }
        
        # Подозрительные слова часто маскируемые гомоглифами
        self.suspicious_words = {
            # Английские
            'free', 'win', 'prize', 'bonus', 'casino', 'betting', 'poker',
            'porn', 'sex', 'adult', 'dating', 'pills', 'viagra', 'drugs',
            'money', 'cash', 'bitcoin', 'crypto', 'trading', 'investment',
            'hack', 'crack', 'keygen', 'torrent', 'download',
            # Русские  
            'деньги', 'заработок', 'халява', 'бесплатно', 'выиграл',
            'казино', 'ставки', 'покер', 'рулетка', 'слоты',
            'секс', 'порно', 'эскорт', 'интим', 'знакомства',
            'таблетки', 'виагра', 'наркотики', 'спайс', 'соль',
            'взлом', 'крак', 'читы', 'боты', 'накрутка'
        }
        
        # Паттерны для поиска URL
        self.url_patterns = [
            r'https?://[^\s]+',
            r'www\.[^\s]+',
            r'[a-zA-Zа-яёА-ЯЁ0-9.-]+\.(com|net|org|ru|рф|tk|ml|ga|cf|xyz|top|click)[/\s]*'
        ]
        
        # Исключения - обычные смешанные фразы
        self.common_exceptions = [
            r'\b(ok|lol|omg|wow|wtf|thx|ty|np)\b',  # Английские сокращения
            r'\b\d+[a-zA-Z]+\b',                    # Номера с буквами: 123abc
            r'@\w+',                                # Упоминания пользователей
            r'#\w+',                                # Хештеги
            r'\b[a-zA-Z]{1,2}\s[а-яё]+\b',         # Короткие англ. слова: "я ok"
            r'\b[а-яё]+\s[a-zA-Z]{1,3}\b',         # Короткие англ. в конце: "спасибо lol"
            r'\b(cpu|gpu|ram|ssd|hdd|usb|wifi|ios|android|windows|linux)\b',  # IT термины
        ]
    
    async def detect_homoglyphs(self, text: str, chat_id: int, user_id: int, 
                              sensitivity: int = 5) -> Tuple[bool, str, float]:
        """
        Обнаружение гомоглифов в тексте
        
        Args:
            text: Текст для проверки
            chat_id: ID чата
            user_id: ID пользователя  
            sensitivity: Чувствительность 1-10 (5 = средняя)
            
        Returns:
            (обнаружено, причина, уверенность)
        """
        try:
            if not text or len(text.strip()) < 3:
                return False, "", 0.0
            
            text = text.strip()
            confidence = 0.0
            reasons = []
            
            # 1. Проверка исключений (обычные смешанные фразы)
            if self._is_common_exception(text):
                self.logger.debug(f"Text matches common exception: {text[:50]}")
                return False, "Common mixed language usage", 0.0
            
            # 2. Проверка URL и доменов на гомоглифы
            url_detected, url_reason, url_conf = self._check_domain_homoglyphs(text)
            if url_detected:
                confidence += url_conf
                reasons.append(url_reason)
            
            # 3. Проверка подозрительных слов
            word_detected, word_reason, word_conf = self._check_suspicious_words(text)
            if word_detected:
                confidence += word_conf
                reasons.append(word_reason)
            
            # 4. Проверка плотности гомоглифов
            density_detected, density_reason, density_conf = self._check_homoglyph_density(text)
            if density_detected:
                confidence += density_conf
                reasons.append(density_reason)
            
            # 5. Проверка подозрительного смешивания скриптов
            mix_detected, mix_reason, mix_conf = self._check_suspicious_mixing(text, sensitivity)
            if mix_detected:
                confidence += mix_conf
                reasons.append(mix_reason)
            
            # Корректировка уверенности в зависимости от длины
            if len(text) > 50:
                confidence *= 0.8  # Длинные тексты менее подозрительны
            elif len(text) > 100:
                confidence *= 0.6
            
            # Определение порога срабатывания
            threshold = self._get_threshold(sensitivity)
            detected = confidence > threshold
            reason = "; ".join(reasons) if reasons else ""
            
            if detected:
                self.logger.info(f"Homoglyphs detected: {reason} (confidence: {confidence:.2f})")
            else:
                self.logger.debug(f"No homoglyphs: confidence {confidence:.2f} < threshold {threshold:.2f}")
            
            return detected, reason, confidence
            
        except Exception as e:
            self.logger.error(f"Error in homoglyph detection: {e}")
            return False, "", 0.0
    
    def _is_common_exception(self, text: str) -> bool:
        """Проверка на обычные исключения"""
        text_lower = text.lower()
        
        for pattern in self.common_exceptions:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
    
    def _check_domain_homoglyphs(self, text: str) -> Tuple[bool, str, float]:
        """Проверка доменов на гомоглифы"""
        confidence = 0.0
        reasons = []
        
        # Извлекаем все URL из текста
        urls = []
        for pattern in self.url_patterns:
            found_urls = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(found_urls)
        
        if not urls:
            return False, "", 0.0
        
        for url in urls:
            try:
                # Нормализуем URL
                if not url.startswith(('http://', 'https://')):
                    url = 'http://' + url.rstrip('/')
                
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                if domain.startswith('www.'):
                    domain = domain[4:]
                
                # Проверяем каждый защищенный домен
                for protected_domain in self.protected_domains:
                    similarity = self._calculate_domain_similarity(domain, protected_domain)
                    
                    if similarity > 0.7 and domain != protected_domain:
                        confidence += similarity * 1.2  # Высокий вес для поддельных доменов
                        reasons.append(f"Поддельный домен: {domain} похож на {protected_domain}")
                
                # Проверяем смешивание скриптов в домене
                if self._has_mixed_scripts_in_domain(domain):
                    confidence += 0.6
                    reasons.append(f"Смешанные символы в домене: {domain}")
                    
            except Exception as e:
                self.logger.debug(f"Error parsing URL {url}: {e}")
                continue
        
        detected = confidence > 0.4
        reason = "; ".join(reasons)
        return detected, reason, confidence
    
    def _check_suspicious_words(self, text: str) -> Tuple[bool, str, float]:
        """Проверка подозрительных слов с гомоглифами"""
        confidence = 0.0
        reasons = []
        
        # Разбиваем на слова
        words = re.findall(r'\b\w+\b', text.lower())
        
        for word in words:
            if len(word) < 3:
                continue
                
            for suspicious_word in self.suspicious_words:
                similarity = self._calculate_word_similarity(word, suspicious_word)
                
                if similarity > 0.8 and word != suspicious_word:
                    confidence += similarity * 0.9
                    reasons.append(f"Подозрительное слово: '{word}' → '{suspicious_word}'")
        
        detected = confidence > 0.5
        reason = "; ".join(reasons)
        return detected, reason, confidence
    
    def _check_homoglyph_density(self, text: str) -> Tuple[bool, str, float]:
        """Проверка плотности гомоглифов в тексте"""
        if len(text) < 5:
            return False, "", 0.0
        
        cyrillic_homoglyphs = 0
        latin_chars = 0
        cyrillic_chars = 0
        
        for char in text.lower():
            if char in self.cyrillic_to_latin:
                cyrillic_homoglyphs += 1
                cyrillic_chars += 1
            elif re.match(r'[а-яё]', char):
                cyrillic_chars += 1
            elif re.match(r'[a-z]', char):
                latin_chars += 1
        
        total_alpha = cyrillic_chars + latin_chars
        
        if total_alpha == 0:
            return False, "", 0.0
        
        # Высокая плотность потенциальных гомоглифов подозрительна
        homoglyph_ratio = cyrillic_homoglyphs / total_alpha
        
        if homoglyph_ratio > 0.4 and cyrillic_homoglyphs >= 3:
            confidence = homoglyph_ratio * 0.8
            reason = f"Высокая плотность гомоглифов: {homoglyph_ratio:.1%} ({cyrillic_homoglyphs}/{total_alpha})"
            return True, reason, confidence
        
        return False, "", homoglyph_ratio * 0.3
    
    def _check_suspicious_mixing(self, text: str, sensitivity: int) -> Tuple[bool, str, float]:
        """Проверка подозрительного смешивания скриптов"""
        
        # Подсчет символов
        cyrillic_count = len(re.findall(r'[а-яёА-ЯЁ]', text))
        latin_count = len(re.findall(r'[a-zA-Z]', text))
        
        total_alpha = cyrillic_count + latin_count
        
        if total_alpha < 6:  # Слишком короткий текст
            return False, "", 0.0
        
        if cyrillic_count == 0 or latin_count == 0:  # Только один скрипт
            return False, "", 0.0
        
        # Рассчитываем соотношение меньшинства
        minority_ratio = min(cyrillic_count, latin_count) / total_alpha
        
        # Адаптивный порог в зависимости от чувствительности
        # sensitivity 1-10 → threshold 0.05-0.35
        base_threshold = 0.05 + (sensitivity - 1) * 0.03
        
        if minority_ratio > base_threshold:
            confidence = minority_ratio * 0.7
            reason = f"Подозрительное смешивание: {cyrillic_count} кир. + {latin_count} лат."
            return True, reason, confidence
        
        return False, "", 0.0
    
    def _calculate_domain_similarity(self, domain1: str, domain2: str) -> float:
        """Рассчитывает сходство доменов с учетом гомоглифов"""
        if len(domain1) != len(domain2):
            # Для доменов разной длины используем более сложный алгоритм
            return self._fuzzy_domain_match(domain1, domain2)
        
        matches = 0
        for c1, c2 in zip(domain1, domain2):
            if c1 == c2:
                matches += 1
            elif self._are_homoglyphs(c1, c2):
                matches += 0.95  # Почти полное совпадение для гомоглифов
        
        return matches / len(domain1)
    
    def _calculate_word_similarity(self, word1: str, word2: str) -> float:
        """Рассчитывает сходство слов с учетом гомоглифов"""
        if abs(len(word1) - len(word2)) > 2:
            return 0.0
        
        # Нормализуем к одинаковой длине для сравнения
        max_len = max(len(word1), len(word2))
        matches = 0
        
        for i in range(max_len):
            c1 = word1[i] if i < len(word1) else ''
            c2 = word2[i] if i < len(word2) else ''
            
            if c1 == c2:
                matches += 1
            elif self._are_homoglyphs(c1, c2):
                matches += 0.9
            elif not c1 or not c2:
                matches += 0.1  # Частичное совпадение для разной длины
        
        return matches / max_len
    
    def _are_homoglyphs(self, char1: str, char2: str) -> bool:
        """Проверяет являются ли символы гомоглифами"""
        c1, c2 = char1.lower(), char2.lower()
        
        # Прямое сравнение
        if (c1 in self.cyrillic_to_latin and self.cyrillic_to_latin[c1] == c2) or \
           (c2 in self.cyrillic_to_latin and self.cyrillic_to_latin[c2] == c1):
            return True
        
        return False
    
    def _has_mixed_scripts_in_domain(self, domain: str) -> bool:
        """Проверяет есть ли смешивание скриптов в домене"""
        has_cyrillic = bool(re.search(r'[а-яё]', domain))
        has_latin = bool(re.search(r'[a-z]', domain))
        return has_cyrillic and has_latin
    
    def _fuzzy_domain_match(self, domain1: str, domain2: str) -> float:
        """Нечеткое сравнение доменов разной длины"""
        # Простая реализация алгоритма Левенштейна с гомоглифами
        shorter, longer = (domain1, domain2) if len(domain1) <= len(domain2) else (domain2, domain1)
        
        if len(longer) - len(shorter) > 3:
            return 0.0
        
        matches = 0
        for i, char in enumerate(shorter):
            if i < len(longer):
                if char == longer[i]:
                    matches += 1
                elif self._are_homoglyphs(char, longer[i]):
                    matches += 0.9
        
        return matches / len(longer)
    
    def _get_threshold(self, sensitivity: int) -> float:
        """Возвращает порог срабатывания в зависимости от чувствительности"""
        # sensitivity 1 (низкая) → threshold 0.8 (только очевидные случаи)
        # sensitivity 10 (высокая) → threshold 0.2 (почти все случаи)
        return max(0.2, 1.0 - (sensitivity * 0.08))
    
    def normalize_text(self, text: str) -> str:
        """Нормализует текст, заменяя гомоглифы на латинские символы"""
        result = []
        for char in text:
            if char.lower() in self.cyrillic_to_latin:
                result.append(self.cyrillic_to_latin[char.lower()])
            else:
                result.append(char)
        return ''.join(result)