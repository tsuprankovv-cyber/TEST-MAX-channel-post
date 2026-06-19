"""
Обработчик /start
"""
from core.logger import get_logger

logger = get_logger(__name__)


def help_text() -> str:
    return (
        "📝 /post — создать пост\n"
        "👁 /preview — предпросмотр\n"
        "📊 /stats — статистика\n"
        "⚙️ /settings — настройки\n"
        "❌ /cancel — сброс"
    )


async def handle_start(user_id, chat_id, send, auth, state):
    logger.info(f"[START] user={user_id}")
    
    if auth.require_password and not auth.is_authorized(user_id):
        await send("🔐 Введите пароль:")
        state.set_step(user_id, 'waiting_password')
        return
    
    state.clear_session(user_id)
    await send(f"👋 MAX Channel Poster\n\n{help_text()}")
