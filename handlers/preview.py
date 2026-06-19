"""
Предпросмотр поста
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def send_preview(user_id, send, state, max_client=None):
    logger.info(f"[PREVIEW] user={user_id}")
    
    draft = state.get_draft(user_id)
    if draft is None:
        logger.warning(f"[PREVIEW] No draft")
        await send("❌ Нет черновика")
        return
    
    text = draft.get('text', '')
    buttons = draft.get('buttons', [])
    attachments = draft.get('attachments', [])
    
    logger.info(f"[PREVIEW] text='{text[:50]}...' buttons={len(buttons)} attachments={len(attachments)}")
    
    chat_id = state.get_session(user_id).get('chat_id', user_id)
    
    # Если есть max_client — отправляем полноценный предпросмотр с медиа
    if max_client:
        logger.info(f"[PREVIEW] Sending full preview with media")
        await max_client.send_message(
            chat_id=chat_id,
            text=text or "Предпросмотр",
            buttons=buttons,
            attachments=[{'type': a['type'], 'payload': a['payload']} for a in attachments if a.get('payload')],
            use_html_format=bool(draft.get('markup'))
        )
    else:
        logger.info(f"[PREVIEW] No max_client, sending text only")
        if text:
            await send(text)
    
    await send("📝 /edit | 🚀 /publish | ❌ /cancel")
