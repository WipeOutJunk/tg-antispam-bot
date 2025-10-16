# app/bot.py

import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.types import ChatMemberUpdated, ChatPermissions
from sqlalchemy.orm import sessionmaker

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
from app.handlers.message_handler import message_router
from app.handlers.chat_events import router as chat_events_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SessionLocal = sessionmaker(bind=engine)

class AntiSpamBot:
    def __init__(self):
        validate_config()
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher()

        # ВАЖНО: chat_events_router должен быть ПЕРВЫМ!
        self.dp.include_router(chat_events_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(message_router)

        # УБРАНО: self.dp.my_chat_member.register(self._on_my_chat_member_update)

        self.spam_analyzer = SpamAnalyzer(ML_MODEL_PATH)
        self.settings_service = SettingsService()
        self.statistics_service = StatisticsService()
        self.quarantine_service = QuarantineService(self.bot)

        logger.info("Бот инициализирован")

    async def start(self):
        logger.info("Запуск бота...")
        
        if not self.spam_analyzer.is_ready():
            raise RuntimeError("ML-классификатор не готов!")

        await self.dp.start_polling(
            self.bot,
            allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"]
        )

    async def stop(self):
        logger.info("Остановка...")
        await self.bot.session.close()

async def main():
    bot = AntiSpamBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Остановка")
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
