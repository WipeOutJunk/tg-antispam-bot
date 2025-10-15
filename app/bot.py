# app/bot.py
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatMemberUpdated , ChatPermissions
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from .config import (
    BOT_TOKEN,
    ML_MODEL_PATH,
    DEFAULT_QUARANTINE_HOURS,
    DEFAULT_SENSITIVITY,
    DEFAULT_WARN_LIMIT,
    validate_config,
)
from .database import engine
from .models.chat import Chat

from .services.spam_analyzer import SpamAnalyzer
from .services.moderation_service import ModerationService
from .services.settings_service import SettingsService
from .services.statistics_service import StatisticsService
from .services.quarantine_service import QuarantineService

from app.handlers.admin_panel import router as admin_router
from app.handlers.message_handler import router as message_router
from app.handlers.member_sync import router as member_sync_router, schedule_daily_sync

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Сессии БД
SessionLocal = sessionmaker(bind=engine)


class AntiSpamBot:
    def __init__(self):
        validate_config()
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher()

        # Роутеры
        self.dp.include_router(admin_router)
        self.dp.include_router(message_router)
        self.dp.include_router(member_sync_router)

        # Хук на смену статуса бота
        self.dp.my_chat_member.register(self._on_my_chat_member_update)

        # Сервисы
        self.spam_analyzer = SpamAnalyzer(ML_MODEL_PATH)
        self.settings_service = SettingsService()
        self.statistics_service = StatisticsService()
        self.quarantine_service = QuarantineService(self.bot)

        logger.info("Анти-спам бот инициализирован (F1.1 + F1.2)")

    async def _on_my_chat_member_update(self, event: ChatMemberUpdated):
        """
        Срабатывает при изменении статуса бота в чате.
        Создаёт или обновляет запись чата, но пропускает случаи без title.
        """
        # Пропускаем чаты без названия (например, ЛС)
        if not getattr(event.chat, "title", None):
            logger.debug("Пропущен чат без title")
            return

        new_status = event.new_chat_member.status
        if new_status in ("member", "administrator"):
            with SessionLocal() as db:
                try:
                    db.add(Chat(
                        id=event.chat.id,
                        title=event.chat.title,
                        sensitivity=DEFAULT_SENSITIVITY,
                        warn_limit=DEFAULT_WARN_LIMIT,
                        quarantine_hours=DEFAULT_QUARANTINE_HOURS,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    ))
                    db.commit()
                    logger.info(f"Чат {event.chat.id} сохранён в БД")
                except IntegrityError:
                    db.rollback()
                    existing = db.get(Chat, event.chat.id)
                    if existing:
                        existing.title = event.chat.title
                        existing.updated_at = datetime.utcnow()
                        db.commit()
                        logger.info(f"Чат {event.chat.id} обновлён в БД")

    async def start(self):
        logger.info("Запуск анти-спам бота...")
        if not self.spam_analyzer.is_ready():
            raise RuntimeError("ML-классификатор не готов к работе!")
        model_info = self.spam_analyzer.get_model_info()
        logger.info(f"Загружена модель: {model_info}")
        logger.info("Активные детекторы: F1.1 (ML-классификатор), F1.2 (проверка ссылок)")
        
        # Запускаем задачу ежедневной синхронизации
        asyncio.create_task(schedule_daily_sync(self.bot))
        logger.info("Запущена задача ежедневной синхронизации участников")
        
        await self.dp.start_polling(self.bot)

    async def stop(self):
        logger.info("Остановка бота...")
        await self.bot.session.close()


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
