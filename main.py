# main.py
import asyncio
import logging
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from app.bot import AntiSpamBot

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
        # Создаем и запускаем бота
        bot = AntiSpamBot()
        logger.info("🤖 Запуск анти-спам бота...")
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        logger.info("🛑 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())
