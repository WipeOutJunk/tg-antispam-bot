import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from sqlalchemy.orm import sessionmaker

from .config import BOT_TOKEN, ML_MODEL_PATH, validate_config
from .database import engine
from .services.spam_analyzer import SpamAnalyzer
from .services.moderation_service import ModerationService
from .services.settings_service import SettingsService
from .services.statistics_service import StatisticsService
from .services.quarantine_service import QuarantineService

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
        
        # Инициализация сервисов
        self.spam_analyzer = SpamAnalyzer(ML_MODEL_PATH)
        self.settings_service = SettingsService()
        self.statistics_service = StatisticsService()
        self.quarantine_service = QuarantineService(self.bot)
        
        # Регистрация обработчиков
        self._register_handlers()
        
        logger.info("Анти-спам бот инициализирован (F1.1 + F1.2)")
    
    def _register_handlers(self):
        """Регистрация обработчиков сообщений"""
        
        @self.dp.message()
        async def handle_message(message: Message):
            """Обработка всех входящих сообщений"""
            
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
        
        @self.dp.message(commands=["test_spam"])
        async def test_spam_command(message: Message):
            """Тестовая команда для проверки ML-классификатора"""
            
            # Проверяем права администратора
            if not await self._is_admin(message):
                return
            
            # Получаем текст для анализа
            if len(message.text.split()) < 2:
                await message.reply(
                    "Использование: /test_spam <текст для анализа>"
                )
                return
            
            test_text = " ".join(message.text.split()[1:])
            
            # Классифицируем текст через ML-модель
            is_spam, confidence = self.spam_analyzer.bayes_detector.classifier.predict(test_text)
            
            # Формируем ответ
            status = "🔴 СПАМ" if is_spam else "✅ НЕ СПАМ"
            confidence_percent = confidence * 100
            
            response = (
                f"{status}\\n"
                f"🎯 Уверенность: {confidence_percent:.1f}%\\n"
                f"📝 Текст: {test_text[:100]}{'...' if len(test_text) > 100 else ''}"
            )
            
            await message.reply(response)
        
        @self.dp.message(commands=["model_info"])
        async def model_info_command(message: Message):
            """Информация о загруженной ML-модели"""
            
            if not await self._is_admin(message):
                return
            
            model_info = self.spam_analyzer.get_model_info()
            
            if model_info["status"] == "loaded":
                response = (
                    f"🤖 **Информация о модели**\\n\\n"
                    f"📊 Тип: {model_info['model_type']}\\n"
                    f"🔤 Векторизатор: {model_info['vectorizer_type']}\\n"
                    f"📚 Размер словаря: {model_info['vocabulary_size']:,}\\n"
                    f"📝 N-граммы: {model_info['ngram_range']}\\n"
                    f"📁 Путь: `{model_info['model_path']}`\\n\\n"
                    f"🔍 **Активные детекторы:**\\n"
                    f"• F1.1: ML-классификатор (Байесовский)\\n"
                    f"• F1.2: Детектор спам-ссылок"
                )
            else:
                response = f"❌ Модель не загружена: {model_info.get('error', 'Неизвестная ошибка')}"
            
            await message.reply(response, parse_mode="Markdown")
        
        @self.dp.message(commands=["stats"])
        async def stats_command(message: Message):
            """Команда статистики (F3.2)"""
            
            if not await self._is_admin(message):
                return
            
            with SessionLocal() as db:
                try:
                    # Получаем статистику за неделю
                    stats = await self.statistics_service.get_chat_statistics(
                        message.chat.id, db, days=7
                    )
                    
                    # Форматируем для вывода
                    stats_text = self.statistics_service.format_statistics_text(stats)
                    
                    await message.reply(stats_text, parse_mode="Markdown")
                    
                except Exception as e:
                    logger.error(f"Ошибка при получении статистики: {e}")
                    await message.reply("❌ Ошибка при получении статистики")
        
        @self.dp.message(commands=["settings"])
        async def settings_command(message: Message):
            """Команда настроек (F3.1)"""
            
            if not await self._is_admin(message):
                return
            
            with SessionLocal() as db:
                try:
                    # Получаем текущие настройки
                    chat_settings = await self.settings_service.get_chat_settings(
                        message.chat.id, db
                    )
                    
                    # Форматируем для вывода
                    settings_text = self.settings_service.get_settings_text(chat_settings)
                    
                    await message.reply(settings_text, parse_mode="Markdown")
                    
                except Exception as e:
                    logger.error(f"Ошибка при получении настроек: {e}")
                    await message.reply("❌ Ошибка при получении настроек")
    
    async def _is_admin(self, message: Message) -> bool:
        """Проверка прав администратора"""
        try:
            member = await self.bot.get_chat_member(message.chat.id, message.from_user.id)
            return member.status in ["creator", "administrator"]
        except:
            return False
    
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