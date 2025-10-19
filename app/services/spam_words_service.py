from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models.spam_words import SpamWord
from ..models.chat import Chat
import logging
import re
logger = logging.getLogger(__name__)


class SpamWordsService:
    """Сервис для управления спам-словами"""
    
    async def add_spam_word(
        self,
        chat_id: int,
        word: str,
        admin_id: int,
        db: Session
    ) -> Optional[SpamWord]:
        """
        Добавить спам-слово для чата
        
        Args:
            chat_id: ID чата
            word: Слово для добавления
            admin_id: ID администратора
            db: Сессия БД
            
        Returns:
            SpamWord или None если слово уже существует
        """
        try:
            # Нормализуем слово
            normalized_word = word.strip().lower()
            
            # Проверяем существование
            existing = db.query(SpamWord).filter(
                SpamWord.chat_id == chat_id,
                SpamWord.word == normalized_word
            ).first()
            
            if existing:
                logger.info(f"Spam word '{word}' already exists for chat {chat_id}")
                return None
            
            # Создаем новое спам-слово
            spam_word = SpamWord(
                chat_id=chat_id,
                word=normalized_word,
                added_by=admin_id,
                added_at=datetime.utcnow()
            )
            
            db.add(spam_word)
            db.commit()
            db.refresh(spam_word)
            
            logger.info(f"Added spam word '{word}' for chat {chat_id} by admin {admin_id}")
            return spam_word
            
        except Exception as e:
            logger.error(f"Error adding spam word: {e}")
            db.rollback()
            return None
    
    async def remove_spam_word(
        self,
        chat_id: int,
        word_id: int,
        db: Session
    ) -> bool:
        """
        Удалить спам-слово
        
        Args:
            chat_id: ID чата
            word_id: ID спам-слова
            db: Сессия БД
            
        Returns:
            True если успешно удалено
        """
        try:
            spam_word = db.query(SpamWord).filter(
                SpamWord.id == word_id,
                SpamWord.chat_id == chat_id
            ).first()
            
            if not spam_word:
                logger.warning(f"Spam word {word_id} not found for chat {chat_id}")
                return False
            
            db.delete(spam_word)
            db.commit()
            
            logger.info(f"Removed spam word {word_id} from chat {chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing spam word: {e}")
            db.rollback()
            return False
    
    async def get_chat_spam_words(
        self,
        chat_id: int,
        db: Session
    ) -> List[SpamWord]:
        """
        Получить все спам-слова чата
        
        Args:
            chat_id: ID чата
            db: Сессия БД
            
        Returns:
            Список спам-слов
        """
        try:
            spam_words = db.query(SpamWord).filter(
                SpamWord.chat_id == chat_id
            ).order_by(SpamWord.added_at.desc()).all()
            
            return spam_words
            
        except Exception as e:
            logger.error(f"Error getting spam words: {e}")
            return []
    
    async def check_message_for_spam_words(
        self,
        message_text: str,
        chat_id: int,
        db: Session
    ) -> tuple[bool, Optional[str]]:
        """
        Проверить сообщение на наличие спам-слов
        
        Args:
            message_text: Текст сообщения
            chat_id: ID чата
            db: Сессия БД
            
        Returns:
            Tuple (содержит_спам, найденное_слово)
        """
        try:
            if not message_text:
                return False, None

            # Получаем спам-слова для чата
            spam_words = await self.get_chat_spam_words(chat_id, db)

            if not spam_words:
                return False, None

            # Нормализуем текст сообщения
            normalized_text = message_text.lower()

            for spam_word in spam_words:
                word_lower = spam_word.word.lower().strip()

                if not word_lower:  # Пропускаем пустые слова
                    continue

                # Используем регулярное выражение с границами слов
                # \\b - граница слова (начало/конец слова, пробел, знак препинания)
                # re.escape() - экранирует специальные символы regex
                pattern = r'\b' + re.escape(word_lower) + r'\b'

                if re.search(pattern, normalized_text):
                    logger.info(f"Found spam word '{spam_word.word}' in message for chat {chat_id}")
                    return True, spam_word.word

            return False, None

        except Exception as e:
            logger.error(f"Error checking spam words: {e}")
            return False, None
    
    async def bulk_add_spam_words(
        self,
        chat_id: int,
        words: List[str],
        admin_id: int,
        db: Session
    ) -> tuple[int, int]:
        """
        Массовое добавление спам-слов
        
        Args:
            chat_id: ID чата
            words: Список слов
            admin_id: ID администратора
            db: Сессия БД
            
        Returns:
            Tuple (добавлено, пропущено)
        """
        added = 0
        skipped = 0
        
        for word in words:
            result = await self.add_spam_word(chat_id, word, admin_id, db)
            if result:
                added += 1
            else:
                skipped += 1
        
        return added, skipped
    
    async def clear_chat_spam_words(
        self,
        chat_id: int,
        db: Session
    ) -> int:
        """
        Очистить все спам-слова чата
        
        Args:
            chat_id: ID чата
            db: Сессия БД
            
        Returns:
            Количество удаленных слов
        """
        try:
            count = db.query(SpamWord).filter(
                SpamWord.chat_id == chat_id
            ).delete()
            
            db.commit()
            logger.info(f"Cleared {count} spam words from chat {chat_id}")
            return count
            
        except Exception as e:
            logger.error(f"Error clearing spam words: {e}")
            db.rollback()
            return 0
