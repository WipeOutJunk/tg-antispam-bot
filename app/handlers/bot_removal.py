# app/handlers/bot_removal.py

import logging
from ..database import SessionLocal
from ..services.caht_cleanup_service import ChatCleanupService

logger = logging.getLogger(__name__)
cleanup_service = ChatCleanupService()


async def handle_bot_removed(event, bot):
    """
    Вызывается, когда бот удалён из чата.
    Делает dry-run очистки, выполняет каскадное удаление и логирует результат.
    """
    chat_id = event.chat.id
    
    try:
        # ВАЖНО: создаём ОДНУ сессию для всех операций
        db = SessionLocal()
        
        try:
            # Dry run: сколько записей будет затронуто
            dry = await cleanup_service.dry_run_cleanup(chat_id, db=db)
            total = dry.get("total", 0)
            logger.info(f"[BotRemoved] chat {chat_id}: will delete {total} records")

            # Полная очистка
            result = await cleanup_service.cleanup_chat_data(
                chat_id=chat_id,
                db=db,
                reason="bot_removed"
            )
            
            if result.get("success"):
                logger.info(f"[BotRemoved] ✅ Chat {chat_id} cleanup succeeded: {result.get('deleted')}")
            else:
                logger.error(f"[BotRemoved] ❌ Chat {chat_id} cleanup failed: {result.get('errors')}")
                
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[BotRemoved] ❌ Error handling removal for chat {chat_id}: {e}", exc_info=True)
