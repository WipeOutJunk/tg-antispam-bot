# app/handlers/admin_panel.py

import logging
from datetime import datetime, timedelta
import html

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, Filter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.orm import Session

from ..services.link_spam_detector import LinkSpamDetector
from ..models.spam_link import SpamLink
from ..database import SessionLocal
from ..models.chat import Chat
from ..models.user import User
from ..models.message_log import MessageLog
from ..models.warning import Warning
from ..models.ban import Ban
from ..models.spam_words import SpamWord
from ..services.settings_service import SettingsService
from ..services.spam_words_service import SpamWordsService

logger = logging.getLogger(__name__)
router = Router()

# State
pending_sensitivity: dict[int, dict] = {}
pending_spam_word: dict[int, dict] = {}
SENS_INPUT_TIMEOUT_SEC = 120
pending_spam_link = {}
class WaitingSpamLink(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(pending_spam_link.get(message.from_user.id) and message.text)
def safe_html_escape(text: str) -> str:
    return html.escape(text or "")

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом в любом чате"""
    with SessionLocal() as db:
        user = db.query(User).filter(
            User.telegram_id == user_id,
            User.is_admin == True
        ).first()
        result = bool(user)
        logger.info(f"is_admin check for {user_id}: {result}")
        return result

async def sync_chat_admins(chat_id: int, bot):
    """Синхронизация админов чата с Telegram API"""
    try:
        admins = await bot.get_chat_administrators(chat_id=chat_id)
        admin_ids = {a.user.id for a in admins}
        
        with SessionLocal() as db:
            # Обновляем всех пользователей этого чата
            db.query(User).filter(User.chat_id == chat_id).update(
                {User.is_admin: False}, synchronize_session=False
            )
            
            # Устанавливаем is_admin=True для реальных админов
            if admin_ids:
                db.query(User).filter(
                    User.chat_id == chat_id,
                    User.telegram_id.in_(admin_ids)
                ).update(
                    {User.is_admin: True}, synchronize_session=False
                )
            
            db.commit()
            logger.info(f"Synced admins for chat {chat_id}: {admin_ids}")
    except Exception as e:
        logger.error(f"Error syncing admins for chat {chat_id}: {e}")

def build_chat_menu(chat: Chat):
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Статистика", callback_data=f"stats_{chat.id}")
    builder.button(text="📝 Логи", callback_data=f"logs_{chat.id}")
    builder.button(text="🔗 Спам-ссылки", callback_data=f"spam_links_{chat.id}")
    builder.button(text="🚫 Спам-слова", callback_data=f"spam_words_{chat.id}")
    builder.button(text="⚙️ Настройки", callback_data=f"settings_{chat.id}")
    builder.button(text="🔙 Назад", callback_data="admin_chats")
    builder.adjust(2, 2, 1)
    
    title = safe_html_escape(chat.title)
    text = (
        f"💬 <b>{title}</b>\n"
        f"ID: <code>{chat.id}</code>  Чувствительность: {chat.sensitivity}/10\n"
        # f"Лимит варнов: {chat.warn_limit}"
    )
    return text, builder.as_markup()

class WaitingSensitivity(Filter):
    async def __call__(self, message: Message) -> bool:
        st = pending_sensitivity.get(message.from_user.id)
        return bool(st and st["chat_context_id"] == message.chat.id and message.text)

class WaitingSpamWord(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(pending_spam_word.get(message.from_user.id) and message.text)

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Это Anti-Spam Bot.\n\n"
        "Команды:\n"
        "/start — справка\n"
        "/clear — очистить чат (личный)\n"
        "/admin — админ-панель"
    )

@router.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.chat.type != "private":
        return
    cid = message.chat.id
    mid = message.message_id
    for m_id in range(mid, max(mid-100, 1), -1):
        try:
            await message.bot.delete_message(cid, m_id)
        except:
            pass
    c = await message.answer("🧹 Чат очищен.")
    await c.delete(delay=3)

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.chat.type != "private" or not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Логи", callback_data="admin_logs")
    builder.button(text="ℹ️ Инфо", callback_data="admin_info")
    builder.adjust(1)
    await message.answer("🔐 <b>Админ-панель</b>\nВыберите:", reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "admin_chats")
async def show_chats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    with SessionLocal() as db:
        chats = db.query(Chat).all()
    if not chats:
        return await callback.message.edit_text("📊 Нет чатов.", parse_mode="HTML")
    b = InlineKeyboardBuilder()
    for c in chats:
        b.button(text=safe_html_escape(c.title), callback_data=f"chat_{c.id}")
    b.button(text="🔙 Назад", callback_data="admin_main")
    b.adjust(1)
    await callback.message.edit_text("📊 Список чатов:", reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("chat_"))
async def show_chat_menu(callback: CallbackQuery):
    chat_id = int(callback.data.split("_")[1])
    # Синхронизируем админов перед проверкой доступа
    await sync_chat_admins(chat_id, callback.bot)
    
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    with SessionLocal() as db:
        chat = db.get(Chat, chat_id)
    if not chat:
        return await callback.answer("Чат не найден", show_alert=True)
        
    text, kb = build_chat_menu(chat)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("settings_"))
async def ask_sensitivity(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    chat_id = int(callback.data.split("_")[1])
    with SessionLocal() as db:
        chat = db.get(Chat, chat_id)
    if not chat:
        return await callback.answer("Чат не найден", show_alert=True)
    
    pending_sensitivity[callback.from_user.id] = {
        "chat_id": chat_id,
        "started_at": datetime.now(),
        "chat_context_id": callback.message.chat.id,
    }
    await callback.message.edit_text(
        f"⚙️ Чувствительность: {chat.sensitivity}/10\nВведите 1–10 или 'отмена'.",
        parse_mode="HTML",
    )
    await callback.answer()

@router.message(WaitingSensitivity())
async def set_sensitivity(message: Message):
    st = pending_sensitivity.pop(message.from_user.id, {})
    if not st:
        return
    if message.text.lower() in ("отмена", "cancel"):
        return await message.answer("❎ Отменено.")
    if not message.text.isdigit() or not (1 <= (v:=int(message.text)) <= 10):
        return await message.answer("❌ Введите число 1–10 или 'отмена'.")
    with SessionLocal() as db:
        svc = SettingsService()
        await svc.update_sensitivity(st["chat_id"], v, db)
        chat = db.get(Chat, st["chat_id"])
    await message.answer(f"✅ Установлено: {v}/10")
    text, kb = build_chat_menu(chat)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("stats_"))
async def show_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    cid = int(callback.data.split("_")[1])
    start = datetime.now() - timedelta(days=7)
    with SessionLocal() as db:
        total = db.query(MessageLog).filter(MessageLog.chat_id==cid, MessageLog.created_at>=start).count()
        spam = db.query(MessageLog).filter(MessageLog.chat_id==cid, MessageLog.is_spam==True, MessageLog.created_at>=start).count()
        warns = db.query(Warning).filter(Warning.chat_id==cid, Warning.issued_at>=start).count()
        bans = db.query(Ban).filter(Ban.chat_id==cid, Ban.issued_at>=start).count()
    pct = (spam/total*100) if total else 0
    text = (
        f"📈 Статистика за 7д:\n"
        f"Всего: {total}\nСпам: {spam} ({pct:.1f}%)\n"
        f"Варны: {warns}\nБаны: {bans}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data=f"chat_{cid}")
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("logs_"))
async def show_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    cid = int(callback.data.split("_")[1])
    with SessionLocal() as db:
        logs = db.query(MessageLog).filter(MessageLog.chat_id==cid).order_by(MessageLog.created_at.desc()).limit(10).all()
    if not logs:
        text = "📝 Нет логов."
    else:
        text = "📝 Последние 10:\n"
        for L in logs:
            mark = "🚫" if L.is_spam else "✅"
            cont = safe_html_escape((L.content or "")[:30])
            tm = L.created_at.strftime("%H:%M")
            text += f"{mark} {tm} | {L.user_id}: <code>{cont}</code>\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data=f"chat_{cid}")
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin_logs")
async def show_global_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    with SessionLocal() as db:
        logs = db.query(MessageLog).order_by(MessageLog.created_at.desc()).limit(15).all()
    text = "📋 Последние логи:\n" + "\n".join(
        f"{'🚫' if L.is_spam else '✅'} {L.created_at.strftime('%d.%m %H:%M')} | C{L.chat_id}"
        for L in logs
    ) or "📋 Нет логов."
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="admin_main")
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin_info")
async def show_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    with SessionLocal() as db:
        total_chats = db.query(Chat).count()
        total_msgs = db.query(MessageLog).count()
        total_spam = db.query(MessageLog).filter(MessageLog.is_spam==True).count()
    text = (
        f"ℹ️ Инфо:\n"
        f"Чатов: {total_chats}\nСообщений: {total_msgs}\nСпама: {total_spam}\nВерсия: 1.0.0"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="admin_main")
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("spam_words_"))
async def show_spam_words(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    cid = int(callback.data.split("_")[-1])
    with SessionLocal() as db:
        words = await SpamWordsService().get_chat_spam_words(cid, db)
        chat = db.query(Chat).get(cid)
        title = safe_html_escape(chat.title if chat else "")
    if not words:
        text = f"🚫 Спам-слова для {title}:\nСписок пуст."
    else:
        text = f"🚫 Спам-слова ({len(words)}):\n"
        for i,w in enumerate(words[:20],1):
            date = w.added_at.strftime("%d.%m.%Y") if w.added_at else "-"
            text += f"{i}. <code>{w.word}</code> ({date})\n"
        if len(words)>20:
            text += f"... ещё {len(words)-20}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить", callback_data=f"add_spam_word_{cid}")
    kb.button(text="🗑️ Управл.", callback_data=f"manage_spam_words_{cid}")
    kb.button(text="🔙 Назад", callback_data=f"chat_{cid}")
    kb.adjust(2,1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("add_spam_word_"))
async def start_add_spam_word(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    cid = int(callback.data.split("_")[-1])
    pending_spam_word[callback.from_user.id] = {"chat_id": cid}
    
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data=f"spam_words_{cid}")
    
    await callback.message.edit_text(
        "✏️ Отправьте слово(а),\nможно через запятую:", 
        reply_markup=kb.as_markup(), 
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(WaitingSpamWord())
async def process_spam_word(message: Message):
    st = pending_spam_word.pop(message.from_user.id, {})
    cid = st.get("chat_id")
    words = [w.strip() for w in message.text.split(",") if w.strip()]
    with SessionLocal() as db:
        svc = SpamWordsService()
        if len(words)==1:
            res = await svc.add_spam_word(cid, words[0], message.from_user.id, db)
            resp = f"✅ Добавлено: {words[0]}" if res else f"⚠️ Уже есть: {words[0]}"
        else:
            a,s = await svc.bulk_add_spam_words(cid, words, message.from_user.id, db)
            resp = f"✅ {a} добавлено, ⚠️ {s} пропущено"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 К списку", callback_data=f"spam_words_{cid}")
    
    await message.answer(resp, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("manage_spam_words_"))
async def manage_spam_words(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    cid = int(callback.data.split("_")[-1])
    with SessionLocal() as db:
        words = await SpamWordsService().get_chat_spam_words(cid, db)
    if not words:
        return await callback.answer("Пусто.", show_alert=True)
    text = "🗑️ Удалите слово:"
    b = InlineKeyboardBuilder()
    for w in words[:15]:
        b.button(text=f"❌ {w.word}", callback_data=f"del_spam_{w.id}_{cid}")
    b.button(text="🗑️ Очистить всё", callback_data=f"clear_spam_{cid}")
    b.button(text="🔙 Назад", callback_data=f"spam_words_{cid}")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("del_spam_"))
async def delete_spam_word(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    _, wid, cid = callback.data.split("_")
    with SessionLocal() as db:
        await SpamWordsService().remove_spam_word(int(cid), int(wid), db)
    await manage_spam_words(callback)

@router.callback_query(F.data.startswith("clear_spam_"))
async def clear_spam(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет doступа", show_alert=True)
    cid = int(callback.data.split("_")[-1])
    with SessionLocal() as db:
        await SpamWordsService().clear_chat_spam_words(cid, db)
    await show_spam_words(callback)

@router.callback_query(F.data == "admin_main")
async def back_to_main(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="📊 Мои чаты", callback_data="admin_chats")
    b.button(text="📋 Логи", callback_data="admin_logs")
    b.button(text="ℹ️ Инфо", callback_data="admin_info")
    b.adjust(1)
    await callback.message.edit_text("🔐 Админ-панель", reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("spam_links_"))
async def show_spam_links(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    cid = int(callback.data.split("_")[-1])
    
    with SessionLocal() as db:
        links = db.query(SpamLink).filter(SpamLink.chat_id == cid).all()
        chat = db.query(Chat).get(cid)
        title = safe_html_escape(chat.title if chat else "")
        
        if not links:
            text = f"🔗 Спам-ссылки для {title}:\nСписок пуст."
        else:
            text = f"🔗 Спам-ссылки ({len(links)}):\n"
            for i, link in enumerate(links[:20], 1):
                date = link.added_at.strftime("%d.%m.%Y") if link.added_at else "-"
                pattern = link.pattern[:50] + "..." if len(link.pattern) > 50 else link.pattern
                text += f"{i}. `{pattern}` ({date})\n"
            if len(links) > 20:
                text += f"... ещё {len(links)-20}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить", callback_data=f"add_spam_link_{cid}")
    kb.button(text="🗑️ Управл.", callback_data=f"manage_spam_links_{cid}")
    kb.button(text="🔙 Назад", callback_data=f"chat_{cid}")
    kb.adjust(2, 1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("add_spam_link_"))
async def start_add_spam_link(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    cid = int(callback.data.split("_")[-1])
    pending_spam_link[callback.from_user.id] = {"chat_id": cid}
    
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data=f"spam_links_{cid}")
    
    await callback.message.edit_text(
        "🔗 Отправьте домен или ссылку:\n\n"
        "Примеры:\n"
        "• `example.com` - блокировка домена\n"
        "• `*.example.com` - блокировка всех поддоменов\n"
        "• `https://bad-site.com/promo` - точная ссылка\n\n"
        "Можно несколько через запятую.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(WaitingSpamLink())
async def process_spam_link(message: Message):
    st = pending_spam_link.pop(message.from_user.id, {})
    cid = st.get("chat_id")
    
    links = [l.strip() for l in message.text.split(",") if l.strip()]
    
    with SessionLocal() as db:
        detector = LinkSpamDetector()
        added_count = 0
        skipped_count = 0
        
        for link in links:
            try:
                # Нормализуем ссылку
                if link.startswith(('http://', 'https://')):
                    from urllib.parse import urlparse
                    parsed = urlparse(link)
                    normalized_link = parsed.netloc.lower()
                    if normalized_link.startswith('www.'):
                        normalized_link = normalized_link[4:]
                else:
                    normalized_link = link.lower()
                
                # Проверяем что не существует уже
                existing = db.query(SpamLink).filter(
                    SpamLink.chat_id == cid,
                    SpamLink.pattern == normalized_link
                ).first()
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Добавляем
                await detector.add_to_blacklist(db, cid, normalized_link, message.from_user.id)
                added_count += 1
                
            except Exception as e:
                logger.error(f"Error adding spam link {link}: {e}")
                skipped_count += 1
        
        if len(links) == 1:
            if added_count > 0:
                resp = f"✅ Добавлено: {links[0]}"
            else:
                resp = f"⚠️ Уже есть: {links[0]}"
        else:
            resp = f"✅ {added_count} добавлено, ⚠️ {skipped_count} пропущено"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 К списку", callback_data=f"spam_links_{cid}")
    
    await message.answer(resp, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("manage_spam_links_"))
async def manage_spam_links(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    cid = int(callback.data.split("_")[-1])
    
    with SessionLocal() as db:
        links = db.query(SpamLink).filter(SpamLink.chat_id == cid).all()
        
        if not links:
            return await callback.answer("Пусто.", show_alert=True)
        
        text = "🗑️ Удалите ссылку:"
        b = InlineKeyboardBuilder()
        
        for link in links[:15]:
            display_text = link.pattern[:30] + "..." if len(link.pattern) > 30 else link.pattern
            b.button(text=f"❌ {display_text}", callback_data=f"del_link_{link.id}_{cid}")
        
        b.button(text="🗑️ Очистить всё", callback_data=f"clear_links_{cid}")
        b.button(text="🔙 Назад", callback_data=f"spam_links_{cid}")
        b.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
        await callback.answer()

@router.callback_query(F.data.startswith("del_link_"))
async def delete_spam_link(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    _, link_id, cid = callback.data.split("_")
    
    with SessionLocal() as db:
        link = db.query(SpamLink).get(int(link_id))
        if link:
            detector = LinkSpamDetector()
            await detector.remove_from_blacklist(db, int(cid), link.pattern)
    
    await manage_spam_links(callback)

@router.callback_query(F.data.startswith("clear_links_"))
async def clear_spam_links(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    cid = int(callback.data.split("_")[-1])
    
    with SessionLocal() as db:
        deleted_count = db.query(SpamLink).filter(SpamLink.chat_id == cid).delete()
        db.commit()
        logger.info(f"Cleared {deleted_count} spam links for chat {cid}")
    
    await show_spam_links(callback)

# 6. ТАКЖЕ ДОБАВИТЬ В ГЛАВНОЕ МЕНЮ АДМИНКИ (в cmd_admin):
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.chat.type != "private" or not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Мои чаты", callback_data="admin_chats")
    builder.button(text="📋 Логи", callback_data="admin_logs")
    builder.button(text="🔗 Все спам-ссылки", callback_data="admin_all_links")  # НОВОЕ
    builder.button(text="ℹ️ Инфо", callback_data="admin_info")
    builder.adjust(1)
    
    await message.answer("🔐 Админ-панель", reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "admin_all_links")
async def show_all_spam_links(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    
    with SessionLocal() as db:
        links = db.query(SpamLink).order_by(SpamLink.added_at.desc()).limit(50).all()
        
        if not links:
            text = "🔗 Спам-ссылки:\nСписок пуст."
        else:
            text = f"🔗 Все спам-ссылки ({len(links)}):\n\n"
            for link in links[:20]:
                date = link.added_at.strftime("%d.%m") if link.added_at else "-"
                chat_info = f"C{link.chat_id}"
                pattern = link.pattern[:40] + "..." if len(link.pattern) > 40 else link.pattern
                text += f"• `{pattern}` | {chat_info} | {date}\n"
            if len(links) > 20:
                text += f"\n... ещё {len(links)-20}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="admin_main")
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()