"""
Публикация поста
"""
from datetime import datetime
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_publish(user_id, send, state, max_client, scheduler, stats, channel_id, 
                        immediate=True, schedule_time=None):
    logger.info(f"[PUBLISH] user={user_id} immediate={immediate}")
    
    draft = state.get_draft(user_id)
    if draft is None:
        logger.warning(f"[PUBLISH] No draft for user={user_id}")
        await send("❌ Нет черновика")
        return
    
    logger.info(f"[PUBLISH] text='{draft.get('text', '')[:50]}...' buttons={len(draft.get('buttons', []))} attachments={len(draft.get('attachments', []))}")
    
    if not immediate and schedule_time:
        job_id = scheduler.schedule_post(user_id, draft, schedule_time)
        if job_id:
            state.clear_draft(user_id)
            state.clear_session(user_id)
            logger.info(f"[PUBLISH] Scheduled: {job_id}")
            await send(f"✅ Запланировано на {schedule_time}")
        else:
            await send("❌ Неверная дата (ГГГГ-ММ-ДД ЧЧ:ММ)")
        return
    
    await send("⏳ Публикую...")
    
    attachments = []
    for att in draft.get('raw_attachments', []):
        if isinstance(att, dict) and att.get('type'):
            attachments.append({'type': att['type'], 'payload': att.get('payload', {})})
    
    logger.info(f"[PUBLISH] Sending to channel={channel_id}")
    
    result = await max_client.send_message(
        chat_id=channel_id,
        text=draft.get('text', ''),
        buttons=draft.get('buttons'),
        attachments=attachments if attachments else None,
        use_html_format=True
    )
    
    if "error" not in result:
        message_id = result.get('message', {}).get('body', {}).get('mid')
        if message_id:
            stats.record_message(message_id, channel_id, draft.get('text', ''), datetime.now().isoformat())
            logger.info(f"[PUBLISH] ✅ msg_id={message_id}")
        
        state.clear_draft(user_id)
        state.clear_session(user_id)
        
        from handlers.start import help_text
        await send(f"✅ Опубликовано!\n\n{help_text()}")
    else:
        error_detail = result.get('detail', '')[:200]
        logger.error(f"[PUBLISH] ❌ {error_detail}")
        await send(f"❌ Ошибка: {error_detail}")
