# app/bot.py (упрощенная версия)

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from sqlalchemy.orm import sessionmaker

from .config import BOT_TOKEN, ML_MODEL_PATH, validate_config
from .database import engine
from .services.spam_analyzer import SpamAnalyzer
from .services.moderation_service import ModerationService
from .services.settings_service import SettingsService
from .services.statistics_service import StatisticsService
from .services.quarantine_service import QuarantineService

# Импорт всех роутеров
from app.handlers.admin_panel import router as admin_router
from app.handlers.user_commands import router as user_router

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание сессий БД
SessionLocal = sessionmaker(bind=engine)

class AntiSpamBot:
    def __init__(self):
        # Валидация конфигурации
        validate_config()
        
        # Инициализация компонентов
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher()
        
        # Подключение всех роутеров
        self.dp.include_router(admin_router)  # Админ-панель
        self.dp.include_router(user_router)  # Пользовательские команды
        
        # Инициализация сервисов
        self.spam_analyzer = SpamAnalyzer(ML_MODEL_PATH)
        self.settings_service = SettingsService()
        self.statistics_service = StatisticsService()
        self.quarantine_service = QuarantineService(self.bot)
        
        # Регистрация обработчика всех сообщений
        self._register_message_handler()
        
        logger.info("Анти-спам бот инициализирован (F1.1 + F1.2)")
    
    def _register_message_handler(self):
        """Регистрация основного обработчика сообщений"""
        
        @self.dp.message(
            F.text,  # Только текстовые сообщения
            ~F.text.startswith('/')  # Игнорируем команды
        )
        async def handle_message(message: Message):
            """Обработка всех входящих сообщений на спам"""
            
            # Создаем сессию БД для этого сообщения
            with SessionLocal() as db:
                try:
                    # Получаем настройки чата
                    chat_settings = await self.settings_service.get_chat_settings(
                        message.chat.id, db
                    )
                    
                    # Анализируем сообщение на спам (только F1.1 + F1.2)
                    spam_results = await self.spam_analyzer.analyze_message(
                        message, chat_settings, db
                    )
                    
                    # Проверяем, является ли сообщение спамом
                    if self.spam_analyzer.is_spam(spam_results, chat_settings):
                        # Инициализируем сервис модерации
                        moderation = ModerationService(self.bot, db)
                        
                        # Обрабатываем спам-сообщение
                        await moderation.handle_spam_message(message, spam_results)
                        
                        # Логируем детекцию
                        summary = self.spam_analyzer.get_detection_summary(spam_results)
                        logger.info(
                            f"Спам обнаружен в чате {message.chat.id} "
                            f"от пользователя {message.from_user.id}: {summary}"
                        )
                
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения: {e}")
    
    async def start(self):
        """Запуск бота"""
        logger.info("Запуск анти-спам бота...")
        
        # Проверяем готовность ML-модели
        if not self.spam_analyzer.is_ready():
            raise RuntimeError("ML-классификатор не готов к работе!")
        
        # Выводим информацию о модели
        model_info = self.spam_analyzer.get_model_info()
        logger.info(f"Загружена модель: {model_info}")
        logger.info("Активные детекторы: F1.1 (ML-классификатор), F1.2 (проверка ссылок)")
        
        # Запускаем polling
        await self.dp.start_polling(self.bot)
    
    async def stop(self):
        """Остановка бота"""
        logger.info("Остановка бота...")
        await self.bot.session.close()

# Точка входа
async def main():
    bot = AntiSpamBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
