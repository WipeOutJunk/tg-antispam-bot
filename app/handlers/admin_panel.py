import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import html
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, Filter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.chat import Chat
from ..models.message_log import MessageLog
from ..models.warning import Warning
from ..models.ban import Ban
from ..config import ADMIN_IDS
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = Router()

# Словарь ожидания ввода: admin_user_id -> {chat_id, started_at, chat_context_id}
pending_sensitivity: Dict[int, Dict[str, Any]] = {}

# Таймаут ожидания ввода (2 минуты)
SENS_INPUT_TIMEOUT_SEC = 120


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def escape_md(text: str) -> str:
    """
    Экранирование символов для Markdown в Telegram.
    Для MarkdownV2 нужно экранировать эти символы: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return ""
    
    # Символы, которые нужно экранировать для MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def safe_html_escape(text: str) -> str:
    """Безопасное экранирование HTML символов"""
    if not text:
        return ""
    return html.escape(text)


def build_chat_menu_text_and_kb(chat: Chat):
    """Построить текст и клавиатуру для меню чата"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Статистика", callback_data=f"stats_{chat.id}")
    builder.button(text="📝 Логи", callback_data=f"logs_{chat.id}")
    builder.button(text="⚙️ Настройки", callback_data=f"settings_{chat.id}")
    builder.button(text="🔙 Назад", callback_data="admin_chats")
    builder.adjust(1)

    # Безопасное экранирование для HTML (рекомендуется использовать HTML вместо Markdown)
    title = safe_html_escape(chat.title or f'Chat {chat.id}')
    text = (
        f"💬 <b>{title}</b>\n"
        f"ID: <code>{chat.id}</code>  Чувствительность: {chat.sensitivity}/10\n"
        f"Лимит варнов: {chat.warn_limit}"
    )
    return text, builder.as_markup()


class WaitingSensitivity(Filter):
    """Фильтр для проверки ожидания ввода чувствительности"""
    async def __call__(self, message: Message) -> bool:
        state = pending_sensitivity.get(message.from_user.id)
        return bool(
            state and 
            state.get("chat_context_id") == message.chat.id and 
            message.text
        )


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Инфо", callback_data="admin_info")
    builder.adjust(1)
    await message.answer(
        "🔐 <b>Админ-панель</b>\nВыберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_chats")
async def show_chats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        chats = db.query(Chat).all()
    
    if not chats:
        await callback.message.edit_text(
            "📊 <b>Мои чаты</b>\nНет чатов.",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for c in chats:
        chat_title = safe_html_escape(c.title or f'Chat {c.id}')
        builder.button(text=f"💬 {c.title or f'Chat {c.id}'}", callback_data=f"chat_{c.id}")
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "📊 <b>Список чатов</b>\nВыберите чат:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chat_"))
async def show_chat_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    with SessionLocal() as db:
        chat = db.get(Chat, chat_id)
    
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    
    text, markup = build_chat_menu_text_and_kb(chat)
    await callback.message.edit_text(
        text,
        reply_markup=markup,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings_"))
async def ask_sensitivity(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    # Получаем текущее значение для отображения
    with SessionLocal() as db:
        chat = db.get(Chat, chat_id)
    
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    
    # Сохраняем состояние ожидания ввода
    pending_sensitivity[callback.from_user.id] = {
        "chat_id": chat_id,
        "started_at": datetime.now(),
        "chat_context_id": callback.message.chat.id,
    }
    
    await callback.message.edit_text(
        f"⚙️ <b>Настройка чувствительности</b>\n\n"
        f"Текущее значение: {chat.sensitivity}/10\n\n"
        f"Введите новое число от 1 до 10:\n"
        f"• 1 - минимальная чувствительность\n"
        f"• 10 - максимальная чувствительность\n\n"
        f"Для отмены отправьте 'отмена'.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(WaitingSensitivity())
async def set_sensitivity_value(message: Message):
    admin_id = message.from_user.id
    state = pending_sensitivity.get(admin_id)
    
    if not state:
        return
    
    # Проверка таймаута
    started_at = state.get("started_at")
    if started_at and (datetime.now() - started_at).total_seconds() > SENS_INPUT_TIMEOUT_SEC:
        pending_sensitivity.pop(admin_id, None)
        await message.answer("⌛ Время ожидания ввода истекло. Попробуйте снова через меню настроек.")
        return
    
    # Обработка отмены
    if message.text.strip().lower() in {"отмена", "cancel", "/cancel"}:
        pending_sensitivity.pop(admin_id, None)
        await message.answer("❎ Изменение чувствительности отменено.")
        
        # Вернуться к карточке чата
        chat_id = state["chat_id"]
        with SessionLocal() as db:
            chat = db.get(Chat, chat_id)
        if chat:
            text, kb = build_chat_menu_text_and_kb(chat)
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    
    # Проверка, что это число
    if not message.text.isdigit():
        await message.answer("❌ Ошибка: введите число от 1 до 10 или 'отмена'.")
        return
    
    new_sens = int(message.text)
    if not 1 <= new_sens <= 10:
        await message.answer("❌ Ошибка: число должно быть от 1 до 10.")
        return
    
    chat_id = state["chat_id"]
    # Удаляем состояние перед записью
    pending_sensitivity.pop(admin_id, None)
    
    # Обновление в БД
    with SessionLocal() as db:
        svc = SettingsService(logger=logger)
        try:
            updated = await svc.update_sensitivity(chat_id, new_sens, db)
            if not updated:
                await message.answer(f"⚠️ Не удалось обновить чувствительность: чат {chat_id} не найден.")
                return
            
            # Загружаем обновлённый чат
            chat = db.get(Chat, chat_id)
            
        except Exception as e:
            logger.error("Error updating sensitivity: %s", e)
            await message.answer("❌ Произошла ошибка при обновлении настроек.")
            return
    
    await message.answer(f"✅ Чувствительность чата {chat_id} установлена: {new_sens}/10.")
    
    # Возвращаем карточку чата
    if chat:
        text, kb = build_chat_menu_text_and_kb(chat)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("stats_"))
async def show_chat_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    start = datetime.now() - timedelta(days=7)
    
    with SessionLocal() as db:
        total = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start
        ).count()
        
        spam = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start,
            MessageLog.is_spam == True
        ).count()
        
        warns = db.query(Warning).filter(
            Warning.chat_id == chat_id,
            Warning.issued_at >= start
        ).count()
        
        bans = db.query(Ban).filter(
            Ban.chat_id == chat_id,
            Ban.issued_at >= start
        ).count()
    
    pct = spam / total * 100 if total else 0
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📈 <b>Статистика за 7 дней</b>\n\n"
        f"Всего сообщений: {total}\n"
        f"Спам: {spam} ({pct:.1f}%)\n"
        f"Предупреждений: {warns}\n"
        f"Блокировок: {bans}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("logs_"))
async def show_chat_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    with SessionLocal() as db:
        logs = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id
        ).order_by(
            MessageLog.created_at.desc()
        ).limit(10).all()
    
    if not logs:
        text = "📝 <b>Логов нет</b>"
    else:
        text = "📝 <b>Последние 10 сообщений:</b>\n\n"
        for log in logs:
            em = "🚫" if log.is_spam else "✅"
            content = log.content or ""
            cont = content[:30] + "..." if len(content) > 30 else content
            cont = safe_html_escape(cont)
            tm = log.created_at.strftime("%H:%M")
            text += f"{em} {tm} | User {log.user_id}\n<code>{cont}</code>\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_logs")
async def show_global_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        logs = db.query(MessageLog).order_by(
            MessageLog.created_at.desc()
        ).limit(15).all()
    
    if not logs:
        text = "📋 <b>Логов нет</b>"
    else:
        text = "📋 <b>Последние логи:</b>\n\n"
        for log in logs:
            em = "🚫" if log.is_spam else "✅"
            content = log.content or ""
            cont = content[:25] + "..." if len(content) > 25 else content
            cont = safe_html_escape(cont)
            tm = log.created_at.strftime("%d.%m %H:%M")
            text += f"{em} {tm} | Chat {log.chat_id}\n<code>{cont}</code>\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_info")
async def show_bot_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        total_chats = db.query(Chat).count()
        total_msgs = db.query(MessageLog).count()
        total_spam = db.query(MessageLog).filter(MessageLog.is_spam == True).count()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"ℹ️ <b>Информация о боте</b>\n\n"
        f"Чатов: {total_chats}\n"
        f"Сообщений: {total_msgs}\n"
        f"Спама: {total_spam}\n\n"
        f"Версия: 1.0.0",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_main")
async def back_to_main(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Инфо", callback_data="admin_info")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\nВыберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()