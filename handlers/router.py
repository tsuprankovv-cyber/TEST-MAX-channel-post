"""
Главный роутер команд
"""
import json
import asyncio
from core.logger import get_logger

logger = get_logger(__name__)


def create_router(auth, state, max_client, media_mgr, scheduler, stats, channel_id):
    """Создаёт функцию-роутер с переданными зависимостями"""
    
    async def send_message(chat_id, text, buttons=None):
        return await max_client.send_message(chat_id=chat_id, text=text, buttons=buttons)
    
    async def router(msg):
        """Обрабатывает входящее сообщение"""
        logger.info("=" * 60)
        
        rec = msg.get('recipient', {})
        sender = msg.get('sender', {})
        user_id = rec.get('user_id') or sender.get('user_id')
        chat_id = rec.get('chat_id')
        
        if not user_id:
            logger.error("[ROUTER] No user_id")
            return
        
        logger.info(f"[ROUTER] user={user_id} chat={chat_id}")
        
        state.get_session(user_id)['chat_id'] = chat_id
        
        async def send(text, buttons=None):
            logger.info(f"[SEND] '{text[:50]}...'")
            return await max_client.send_message(
                chat_id=chat_id or user_id,
                text=text,
                buttons=buttons
            )
        
        body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
        text = body.get('text', '') or msg.get('text', '')
        markup = body.get('markup', []) or msg.get('markup', [])
        raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
        
        logger.info(f"[ROUTER] text='{text[:80]}...' markup={len(markup)} attachments={len(raw_attachments)}")
        
        step = state.get_step(user_id)
        logger.info(f"[ROUTER] step={step}")
        
        cmd = text.strip()
        
        # Импорты handlers
        from handlers.start import handle_start, help_text
        from handlers.auth_handler import handle_password
        from handlers.post_create import (
            handle_post_command, handle_post_photo, handle_post_text,
            handle_post_buttons, handle_skip
        )
        from handlers.post_edit import (
            handle_edit, handle_edit_photo, handle_edit_text, handle_edit_buttons
        )
        from handlers.post_publish import handle_publish
        from handlers.preview import send_preview
        from handlers.settings_handler import (
            handle_stats, handle_settings, handle_set_channel,
            handle_set_password, handle_list_admins
        )
        from handlers.inline_buttons import (
            handle_inline_text, handle_inline_use, handle_inline_confirm
        )
        from handlers.templates import (
            handle_templates_menu,
            handle_inline_add_start, handle_inline_add_name, handle_inline_add_url,
            handle_inline_list, handle_inline_del,
            handle_btn_add_start, handle_btn_add_name, handle_btn_add_url,
            handle_btn_list, handle_btn_del,
            handle_btn_use, handle_btn_confirm
        )
        
        # === РОУТИНГ КОМАНД ===
        
        if cmd == '/start':
            await handle_start(user_id, chat_id, send, auth, state)
        
        elif cmd == '/post':
            await handle_post_command(user_id, send, auth, state)
        
        elif cmd == '/skip':
            await handle_skip(user_id, send, state)
        
        elif cmd == '/preview':
            await send_preview(user_id, send, state, max_client)
        
        elif cmd == '/edit':
            await handle_edit(user_id, send, state)
        
        elif cmd == '/edit_photo':
            await handle_edit_photo(user_id, send, state)
        
        elif cmd == '/edit_text':
            await handle_edit_text(user_id, send, state)
        
        elif cmd == '/edit_buttons':
            await handle_edit_buttons(user_id, send, state)
        
        elif cmd == '/inline_yes':
            await handle_inline_confirm(user_id, send, state, max_client)
        
        elif cmd == '/btn_yes':
            await handle_btn_confirm(user_id, send, state, max_client)
        
        elif cmd == '/publish':
            await handle_publish(user_id, send, state, max_client, scheduler, stats, channel_id)
        
        elif cmd.startswith('/schedule '):
            time_str = cmd.replace('/schedule ', '')
            await handle_publish(user_id, send, state, max_client, scheduler, stats, channel_id,
                               immediate=False, schedule_time=time_str)
        
        elif cmd == '/cancel':
            state.clear_draft(user_id)
            state.clear_session(user_id)
            await send(f"🗑️ Сброшено.\n\n{help_text()}")
        
        elif cmd == '/stats':
            await handle_stats(send, stats)
        
        elif cmd == '/settings':
            await handle_settings(send)
        
        elif cmd.startswith('/set_channel '):
            await handle_set_channel(user_id, cmd.split()[1], send)
        
        elif cmd.startswith('/set_password '):
            await handle_set_password(user_id, cmd.split()[1], send, auth)
        
        elif cmd == '/list_admins':
            await handle_list_admins(send, auth)
        
        # === ШАБЛОНЫ ===
        elif cmd == '/templates':
            await handle_templates_menu(send)
        
        elif cmd == '/inline_add':
            await handle_inline_add_start(user_id, send, state)
        
        elif cmd == '/inline_list':
            await handle_inline_list(user_id, send)
        
        elif cmd.startswith('/inline_del '):
            await handle_inline_del(user_id, cmd.replace('/inline_del ', ''), send)
        
        elif cmd == '/btn_add':
            await handle_btn_add_start(user_id, send, state)
        
        elif cmd == '/btn_list':
            await handle_btn_list(user_id, send)
        
        elif cmd.startswith('/btn_del '):
            await handle_btn_del(user_id, cmd.replace('/btn_del ', ''), send)
        
        # === ОБРАБОТКА ПО ШАГАМ ===
        elif step == 'waiting_password':
            await handle_password(user_id, text.strip(), send, auth, state)
        
        elif step == 'post_waiting_photo':
            if raw_attachments:
                await handle_post_photo(user_id, raw_attachments, send, state, media_mgr)
            else:
                await send("📸 Отправьте фото или /skip")
        
        elif step == 'post_waiting_text':
            await handle_post_text(user_id, text, markup, raw_attachments, send, state, media_mgr)
        
        elif step == 'post_waiting_inline':
            if cmd == '/inline_use':
                await handle_inline_use(user_id, send, state, max_client)
            elif cmd == '/skip':
                await handle_skip(user_id, send, state)
            else:
                await handle_inline_text(user_id, text, send, state, max_client)
        
        elif step == 'post_waiting_inline_confirm':
            if cmd == '/inline_yes':
                await handle_inline_confirm(user_id, send, state, max_client)
            elif cmd == '/skip':
                state.set_step(user_id, 'post_waiting_buttons')
                await send("🔘 Шаг 4/4: Добавьте URL-кнопки\n⏭ /skip | 📋 /btn_use | ❌ /cancel")
            else:
                await send("✅ /inline_yes — подтвердить\n❌ /skip — пропустить")
        
        elif step == 'post_waiting_buttons':
            if cmd == '/btn_use':
                await handle_btn_use(user_id, send, state)
            elif cmd == '/skip':
                await handle_skip(user_id, send, state)
            else:
                await handle_post_buttons(user_id, text, send, state, max_client)
        
        elif step == 'post_waiting_buttons_confirm':
            if cmd == '/btn_yes':
                await handle_btn_confirm(user_id, send, state, max_client)
            elif cmd == '/skip':
                session = state.get_session_data(user_id)
                session['buttons'] = []
                state.save_draft(user_id, session.copy())
                state.set_step(user_id, 'post_ready')
                await send_preview(user_id, send, state, max_client)
            else:
                await send("✅ /btn_yes — подтвердить\n❌ /skip — пропустить")
        
        elif step == 'post_ready':
            await handle_post_text(user_id, text, markup, raw_attachments, send, state, media_mgr)
            await send_preview(user_id, send, state, max_client)
        
        # 🔥 Новые шаги для добавления шаблонов
        elif step == 'inline_add_name':
            await handle_inline_add_name(user_id, text, send, state)
        
        elif step == 'inline_add_url':
            await handle_inline_add_url(user_id, text, send, state)
        
        elif step == 'btn_add_name':
            await handle_btn_add_name(user_id, text, send, state)
        
        elif step == 'btn_add_url':
            await handle_btn_add_url(user_id, text, send, state)
        
        else:
            if auth.is_authorized(user_id):
                await send(help_text())
            else:
                await send("🔐 /start")
        
        logger.info("=" * 60)
    
    return router
