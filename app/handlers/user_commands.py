# app/handlers/user_commands.py
import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.orm import sessionmaker

from ..config import ADMIN_IDS
from ..database import engine
from ..services.settings_service import SettingsService
from ..services.statistics_service import StatisticsService

logger = logging.getLogger(__name__)
router = Router()

# Создание сессий БД
SessionLocal = sessionmaker(bind=engine)


def is_admin_user(user_id: int, chat_type: str) -> bool:
    """Проверка прав администратора"""
    # В личке - проверяем по списку ADMIN_IDS
    if chat_type == "private":
        return user_id in ADMIN_IDS
    
    # В группе - пока True (можно добавить проверку через get_chat_member)
    return True


@router.message(Command("test_spam"))
async def test_spam_command(message: Message):
    """Тестовая команда для проверки ML-классификатора"""
    
    logger.info(f"Получена команда /test_spam от {message.from_user.id}")
    
    if not is_admin_user(message.from_user.id, message.chat.type):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Получаем текст для анализа
    if len(message.text.split()) < 2:
        await message.reply("Использование: /test_spam <текст для анализа>")
        return
    
    test_text = " ".join(message.text.split()[1:])
    
    try:
        # Импортируем здесь чтобы избежать циклических импортов
        from ..services.ml_classifier import MLSpamClassifier
        from ..config import ML_MODEL_PATH
        
        classifier = MLSpamClassifier(ML_MODEL_PATH)
        is_spam, confidence = classifier.predict(test_text)
        
        # Формируем ответ
        status = "🔴 СПАМ" if is_spam else "✅ НЕ СПАМ"
        confidence_percent = confidence * 100
        
        response = (
            f"{status}\\n"
            f"🎯 Уверенность: {confidence_percent:.1f}%\\n"
            f"📝 Текст: {test_text[:100]}{'...' if len(test_text) > 100 else ''}"
        )
        
        await message.reply(response)
        
    except Exception as e:
        logger.error(f"Ошибка в test_spam_command: {e}")
        await message.reply("❌ Ошибка при обработке команды")


@router.message(Command("model_info"))
async def model_info_command(message: Message):
    """Информация о загруженной ML-модели"""
    
    logger.info(f"Получена команда /model_info от {message.from_user.id}")
    
    if not is_admin_user(message.from_user.id, message.chat.type):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        from ..services.ml_classifier import MLSpamClassifier
        from ..config import ML_MODEL_PATH
        
        classifier = MLSpamClassifier(ML_MODEL_PATH)
        
        if classifier.is_ready():
            model_info = classifier.get_model_info()
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
            response = "❌ Модель не загружена"
        
        await message.reply(response, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка в model_info_command: {e}")
        await message.reply("❌ Ошибка при получении информации о модели")


@router.message(Command("stats"))
async def stats_command(message: Message):
    """Команда статистики (F3.2)"""
    
    logger.info(f"Получена команда /stats от {message.from_user.id}")
    
    if not is_admin_user(message.from_user.id, message.chat.type):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    with SessionLocal() as db:
        try:
            stats_service = SettingsService()
            stats = await stats_service.get_chat_statistics(message.chat.id, db, days=7)
            
            # Простое форматирование статистики
            response = (
                f"📊 **Статистика за 7 дней**\\n\\n"
                f"📨 Всего сообщений: {stats.get('total_messages', 0)}\\n"
                f"🚫 Спам сообщений: {stats.get('total_spam', 0)}\\n"
                f"⚠️ Предупреждений: {stats.get('total_warnings', 0)}\\n"
                f"🔨 Блокировок: {stats.get('total_bans', 0)}"
            )
            
            await message.reply(response, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            await message.reply("❌ Ошибка при получении статистики")


@router.message(Command("settings"))
async def settings_command(message: Message):
    """Команда настроек (F3.1)"""
    
    logger.info(f"Получена команда /settings от {message.from_user.id}")
    
    if not is_admin_user(message.from_user.id, message.chat.type):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    with SessionLocal() as db:
        try:
            settings_service = SettingsService()
            chat_settings = await settings_service.get_chat_settings(message.chat.id, db)
            
            response = (
                f"⚙️ **Настройки чата**\\n\\n"
                f"🎯 Чувствительность: {chat_settings.sensitivity}/10\\n"
                f"⚠️ Лимит предупреждений: {chat_settings.warn_limit}\\n"
                f"🕐 Карантин новичков: {getattr(chat_settings, 'quarantine_hours', 0)} ч.\\n\\n"
                f"Для изменения настроек используйте команду /admin в личке с ботом."
            )
            
            await message.reply(response, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка при получении настроек: {e}")
            await message.reply("❌ Ошибка при получении настроек")


@router.message(Command("start"))
async def start_command(message: Message):
    """Команда /start"""
    logger.info(f"Получена команда /start от {message.from_user.id}")
    
    if message.chat.type == "private":
        response = (
            "🤖 **Анти-спам бот**\\n\\n"
            "Привет! Я защищаю чаты от спама используя машинное обучение.\\n\\n"
            "🔧 **Доступные команды:**\\n"
            "• /admin - Админ-панель (только для админов)\\n"
            "• /settings - Текущие настройки\\n"
            "• /stats - Статистика работы\\n\\n"
            "Добавьте меня в группу и дайте права администратора для защиты от спама."
        )
    else:
        response = (
            "🤖 Анти-спам бот активен в этом чате!\\n\\n"
            "Используйте /settings для просмотра настроек."
        )
    
    await message.answer(response, parse_mode="Markdown")