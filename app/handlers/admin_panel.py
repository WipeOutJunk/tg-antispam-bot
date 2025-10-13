# app/handlers/admin_panel.py
import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.chat import Chat
from ..models.message_log import MessageLog
from ..models.warning import Warning
from ..models.ban import Ban
from ..config import ADMIN_IDS  # Список ID админов

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS


@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Главное меню админ-панели"""

    logger.info("Получена команда /admin от %s", message.from_user.id)
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Последние логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Информация", callback_data="admin_info")
    builder.adjust(1)
    
    await message.answer(
        "🔐 *Админ-панель*\n\n"
        "Выберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_chats")
async def show_chats(callback: CallbackQuery):
    """Показать список чатов с ботом"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        chats = db.query(Chat).all()
        
        if not chats:
            await callback.message.edit_text(
                "📊 *Мои чаты*\n\n"
                "Бот пока не добавлен ни в один чат.",
                parse_mode="Markdown"
            )
            return
        
        builder = InlineKeyboardBuilder()
        for chat in chats:
            # Получаем название чата или используем ID
            chat_name = chat.title if chat.title else f"Chat {chat.id}"
            builder.button(
                text=f"💬 {chat_name}",
                callback_data=f"chat_{chat.id}"
            )
        builder.button(text="🔙 Назад", callback_data="admin_main")
        builder.adjust(1)
        
        await callback.message.edit_text(
            "📊 *Список чатов*\n\n"
            "Выберите чат для управления:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("chat_"))
async def show_chat_menu(callback: CallbackQuery):
    """Меню управления конкретным чатом"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    with SessionLocal() as db:
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat:
            await callback.answer("Чат не найден", show_alert=True)
            return
        
        chat_name = chat.title if chat.title else f"Chat {chat_id}"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📈 Статистика", callback_data=f"stats_{chat_id}")
        builder.button(text="📝 Последние логи", callback_data=f"logs_{chat_id}")
        builder.button(text="⚙️ Настройки", callback_data=f"settings_{chat_id}")
        builder.button(text="🔙 К списку чатов", callback_data="admin_chats")
        builder.adjust(1)
        
        await callback.message.edit_text(
            f"💬 *{chat_name}*\n\n"
            f"ID чата: `{chat_id}`\n"
            f"Чувствительность: {chat.sensitivity}/10\n"
            f"Лимит предупреждений: {chat.warn_limit}\n\n"
            "Выберите действие:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("stats_"))
async def show_chat_stats(callback: CallbackQuery):
    """Показать статистику чата"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    with SessionLocal() as db:
        # Статистика за последние 7 дней
        start_date = datetime.now() - timedelta(days=7)
        
        total_messages = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start_date
        ).count()
        
        spam_messages = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start_date,
            MessageLog.is_spam == True
        ).count()
        
        warnings = db.query(Warning).filter(
            Warning.chat_id == chat_id,
            Warning.issued_at >= start_date
        ).count()
        
        bans = db.query(Ban).filter(
            Ban.chat_id == chat_id,
            Ban.issued_at >= start_date
        ).count()
        
        spam_percent = (spam_messages / total_messages * 100) if total_messages > 0 else 0
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
        
        await callback.message.edit_text(
            f"📈 *Статистика за 7 дней*\n\n"
            f"📨 Всего сообщений: {total_messages}\n"
            f"🚫 Спам сообщений: {spam_messages} ({spam_percent:.1f}%)\n"
            f"⚠️ Предупреждений: {warnings}\n"
            f"🔨 Блокировок: {bans}",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("logs_"))
async def show_chat_logs(callback: CallbackQuery):
    """Показать последние логи чата"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    with SessionLocal() as db:
        logs = db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id
        ).order_by(MessageLog.created_at.desc()).limit(10).all()
        
        if not logs:
            text = "📝 *Последние логи*\n\nЛогов пока нет."
        else:
            text = "📝 *Последние 10 сообщений:*\n\n"
            for log in logs:
                spam_emoji = "🚫" if log.is_spam else "✅"
                content = log.content[:30] + "..." if len(log.content) > 30 else log.content
                time_str = log.created_at.strftime("%H:%M")
                text += f"{spam_emoji} {time_str} | User {log.user_id}\n`{content}`\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("settings_"))
async def show_chat_settings(callback: CallbackQuery):
    """Показать настройки чата"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[1])
    
    with SessionLocal() as db:
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔧 Изменить чувствительность", callback_data=f"set_sens_{chat_id}")
        builder.button(text="⚠️ Изменить лимит варнов", callback_data=f"set_warn_{chat_id}")
        builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
        builder.adjust(1)
        
        await callback.message.edit_text(
            f"⚙️ *Настройки чата*\n\n"
            f"Чувствительность: {chat.sensitivity}/10\n"
            f"Лимит предупреждений: {chat.warn_limit}\n"
            f"Карантин новичков: {chat.quarantine_hours} ч\n\n"
            "Выберите параметр для изменения:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data == "admin_logs")
async def show_global_logs(callback: CallbackQuery):
    """Показать последние логи по всем чатам"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        logs = db.query(MessageLog).order_by(
            MessageLog.created_at.desc()
        ).limit(15).all()
        
        if not logs:
            text = "📋 *Последние логи*\n\nЛогов пока нет."
        else:
            text = "📋 *Последние 15 сообщений (все чаты):*\n\n"
            for log in logs:
                spam_emoji = "🚫" if log.is_spam else "✅"
                content = log.content[:25] + "..." if len(log.content) > 25 else log.content
                time_str = log.created_at.strftime("%d.%m %H:%M")
                text += f"{spam_emoji} {time_str} | Chat {log.chat_id}\n`{content}`\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_main")
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data == "admin_info")
async def show_bot_info(callback: CallbackQuery):
    """Показать информацию о боте"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    with SessionLocal() as db:
        total_chats = db.query(Chat).count()
        total_messages = db.query(MessageLog).count()
        total_spam = db.query(MessageLog).filter(MessageLog.is_spam == True).count()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_main")
    
    await callback.message.edit_text(
        f"ℹ️ *Информация о боте*\n\n"
        f"📊 Всего чатов: {total_chats}\n"
        f"📨 Всего сообщений: {total_messages}\n"
        f"🚫 Заблокировано спама: {total_spam}\n\n"
        f"🤖 Версия: 1.0.0\n"
        f"🔍 Детекторы: ML + Links",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    
    await callback.answer()


@router.callback_query(F.data == "admin_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться в главное меню админки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Последние логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Информация", callback_data="admin_info")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "🔐 *Админ-панель*\n\n"
        "Выберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()
