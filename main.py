import asyncio
import logging
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from app.bot import AntiSpamBot
from app.database import SessionLocal, engine
from app.models.profanity_word import ProfanityWord
from app.models.base import Base

def initialize_database():
    """Инициализация базы данных и таблиц"""
    logger = logging.getLogger(__name__)

    try:
        logger.info(" Инициализация базы данных...")
        Base.metadata.create_all(bind=engine)
        logger.info(" Таблицы созданы/проверены")

        session = SessionLocal()
        try:
            count = session.query(ProfanityWord).count()
            logger.info(f"Слов в таблице profanity_words: {count}")

            if count == 0:
                logger.info("Таблица profanity_words пуста, загружаем слова...")
                load_profanity_words(session)
            else:
                logger.info("Таблица profanity_words уже заполнена")
        finally:
            session.close()

    except Exception as e:
        logger.error(f" Ошибка при инициализации БД: {e}")
        raise

def load_profanity_words(session):
    """Загрузка нецензурных слов из файла в БД"""
    logger = logging.getLogger(__name__)

    words_file = "data/ru_curse_words.txt"

    if not os.path.exists(words_file):
        logger.warning(f" Файл {words_file} не найден, пропускаем загрузку")
        return

    try:
        with open(words_file, 'r', encoding='utf-8') as f:
            words = list(set(line.strip() for line in f if line.strip()))

        logger.info(f"📄 Загружено {len(words)} уникальных слов из файла")

        batch_size = 500
        added_count = 0

        for i in range(0, len(words), batch_size):
            batch = words[i:i+batch_size]
            session.bulk_insert_mappings(
                ProfanityWord,
                [{'word': word} for word in batch]
            )
            added_count += len(batch)
            logger.info(f"Добавлено {added_count}/{len(words)} слов...")

        session.commit()
        logger.info(f"Успешно добавлено {len(words)} слов в базу данных")

    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при загрузке слов: {e}")
        raise

async def main():
    """Точка входа в приложение"""
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger(__name__)

    try:
        initialize_database()

        bot = AntiSpamBot()
        logger.info("🤖 Запуск анти-спам бота...")
        await bot.start()

    except KeyboardInterrupt:
        logger.info(" Получен сигнал остановки")
    except Exception as e:
        logger.error(f" Критическая ошибка: {e}")
    finally:
        logger.info(" Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())
