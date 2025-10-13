import logging
from datetime import datetime, timedelta
from typing import Dict

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
from ..config import ADMIN_IDS
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = Router()

# Словарь ожидания ввода: admin_user_id -> chat_id
pending_sensitivity: Dict[int, int] = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
    await message.answer("🔐 *Админ-панель*\nВыберите действие:",
                         reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "admin_chats")
async def show_chats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with SessionLocal() as db:
        chats = db.query(Chat).all()
    if not chats:
        await callback.message.edit_text("📊 *Мои чаты*\nНет чатов.", parse_mode="Markdown")
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for c in chats:
        builder.button(text=f"💬 {c.title or f'Chat {c.id}'}", callback_data=f"chat_{c.id}")
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    await callback.message.edit_text("📊 *Список чатов*\nВыберите чат:",
                                     reply_markup=builder.as_markup(), parse_mode="Markdown")
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
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Статистика", callback_data=f"stats_{chat_id}")
    builder.button(text="📝 Логи", callback_data=f"logs_{chat_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"settings_{chat_id}")
    builder.button(text="🔙 Назад", callback_data="admin_chats")
    builder.adjust(1)
    await callback.message.edit_text(
        f"💬 *{chat.title or f'Chat {chat_id}'}*\n"
        f"ID: `{chat_id}`  Чувствительность: {chat.sensitivity}/10\n"
        f"Лимит варнов: {chat.warn_limit}",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings_"))
async def ask_sensitivity(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    chat_id = int(callback.data.split("_")[1])
    pending_sensitivity[callback.from_user.id] = chat_id
    await callback.message.edit_text(
        f"Введите число 1–10 для чувствительности чата {chat_id}:",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(lambda m: m.from_user.id in pending_sensitivity and m.text and m.text.isdigit())
async def set_sensitivity_value(message: Message):
    admin_id = message.from_user.id
    chat_id = pending_sensitivity.pop(admin_id)
    new_sens = int(message.text)
    if not 1 <= new_sens <= 10:
        await message.answer("Ошибка: введите число от 1 до 10.")
        return
    with SessionLocal() as db:
        svc = SettingsService(logger=logging.getLogger(__name__))
        await svc.update_sensitivity(chat_id, new_sens, db)
    await message.answer(f"✅ Чувствительность чата {chat_id} установлена: {new_sens}/10.")
    # Вернуться в меню чата
    callback = CallbackQuery(type="callback_query", data=f"chat_{chat_id}", message=message)
    await show_chat_menu(callback)


@router.callback_query(F.data.startswith("stats_"))
async def show_chat_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    chat_id = int(callback.data.split("_")[1])
    start = datetime.now() - timedelta(days=7)
    with SessionLocal() as db:
        total = db.query(MessageLog).filter(MessageLog.chat_id==chat_id, MessageLog.created_at>=start).count()
        spam = db.query(MessageLog).filter(MessageLog.chat_id==chat_id, MessageLog.created_at>=start, MessageLog.is_spam).count()
        warns = db.query(Warning).filter(Warning.chat_id==chat_id, Warning.issued_at>=start).count()
        bans = db.query(Ban).filter(Ban.chat_id==chat_id, Ban.issued_at>=start).count()
    pct = spam/total*100 if total else 0
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
    builder.adjust(1)
    await callback.message.edit_text(
        f"📈 *Статистика за 7 дней*\nВсего: {total}\nСпам: {spam} ({pct:.1f}%)\n"
        f"Предупреждений: {warns}\nБлокировок: {bans}",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("logs_"))
async def show_chat_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    chat_id = int(callback.data.split("_")[1])
    with SessionLocal() as db:
        logs = db.query(MessageLog).filter(MessageLog.chat_id==chat_id).order_by(MessageLog.created_at.desc()).limit(10).all()
    text = "📝 *Последние 10 сообщений:*\n\n" if logs else "📝 *Логов нет*"
    for log in logs:
        em = "🚫" if log.is_spam else "✅"
        cont = (log.content[:30]+"...") if len(log.content)>30 else log.content
        tm = log.created_at.strftime("%H:%M")
        text += f"{em} {tm} | User {log.user_id}\n`{cont}`\n\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"chat_{chat_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "admin_logs")
async def show_global_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with SessionLocal() as db:
        logs = db.query(MessageLog).order_by(MessageLog.created_at.desc()).limit(15).all()
    text = "📋 *Последние логи:*\n\n" if logs else "📋 *Логов нет*"
    for log in logs:
        em = "🚫" if log.is_spam else "✅"
        cont = (log.content[:25]+"...") if len(log.content)>25 else log.content
        tm = log.created_at.strftime("%d.%m %H:%M")
        text += f"{em} {tm} | Chat {log.chat_id}\n`{cont}`\n\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "admin_info")
async def show_bot_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with SessionLocal() as db:
        total_chats = db.query(Chat).count()
        total_msgs = db.query(MessageLog).count()
        total_spam = db.query(MessageLog).filter(MessageLog.is_spam).count()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_main")
    builder.adjust(1)
    await callback.message.edit_text(
        f"ℹ️ *Информация о боте*\nЧатов: {total_chats}\nСообщений: {total_msgs}\nСпама: {total_spam}\n\nВерсия:1.0.0",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_main")
async def back_to_main(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Инфо", callback_data="admin_info")
    builder.adjust(1)
    await callback.message.edit_text("🔐 *Админ-панель*\nВыберите действие:",
                                     reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()
