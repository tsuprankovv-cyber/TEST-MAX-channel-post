"""
Обработчик inline-кнопок (слова-ссылки в тексте)
"""
import re
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)


def parse_inline_links(text: str) -> List[Dict]:
    """Парсит слова-ссылки из формата: [текст](url)"""
    logger.info(f"[INLINE] Parsing: '{text[:150]}...'")
    
    links = []
    pattern = r'\[(.+?)\]\((https?://[^\s)]+)\)'
    
    for match in re.finditer(pattern, text):
        link_text = match.group(1)
        link_url = match.group(2)
        links.append({"text": link_text, "url": link_url})
        logger.info(f"[INLINE] ✅ '{link_text}' → {link_url[:50]}...")
    
    logger.info(f"[INLINE] Found {len(links)} links")
    return links


def apply_inline_links(text: str) -> str:
    """Конвертирует [текст](url) → <a href="url">текст</a>"""
    logger.info(f"[INLINE-APPLY] Applying inline links to text")
    
    pattern = r'\[(.+?)\]\((https?://[^\s)]+)\)'
    result = re.sub(pattern, r'<a href="\2">\1</a>', text)
    
    if result != text:
        logger.info(f"[INLINE-APPLY] Links applied: '{result[:150]}...'")
    
    return result


def preview_inline_links(templates: List[Dict]) -> str:
    """Показывает как будет выглядеть блок ссылок в посте"""
    preview = "🔗 Полезные ссылки:\n"
    for t in templates:
        preview += f"• {t['text']}\n"
    return preview


async def handle_inline_text(user_id, text, send, state, max_client=None):
    """Обрабатывает введённые слова-ссылки"""
    logger.info(f"[INLINE-TEXT] user={user_id} text='{text[:100]}...'")
    
    session = state.get_session_data(user_id)
    links = parse_inline_links(text)
    
    if links:
        current_text = session.get('text', '')
        inline_block = '\n\n🔗 Полезные ссылки:\n'
        for link in links:
            inline_block += f'• [{link["text"]}]({link["url"]})\n'
        
        session['text'] = current_text + inline_block
        session['text'] = apply_inline_links(session['text'])
        session['inline_links'] = links
        logger.info(f"[INLINE-TEXT] Applied {len(links)} inline links")
    else:
        logger.info(f"[INLINE-TEXT] No inline links found")
    
    state.set_step(user_id, 'post_waiting_buttons')
    await send(
        "<b>✅ Ссылки добавлены</b>\n\n"
        "<b>🔘 Шаг 4/4: Добавьте URL-кнопки</b>\n\n"
        "Формат: <code>Название | https://url</code>\n"
        "📋 /btn_use — шаблоны\n\n"
        "─────────────────\n"
        "⏭ /skip — пропустить\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_use(user_id, send, state, max_client=None):
    """Использовать сохранённые шаблоны слов-ссылок"""
    logger.info(f"[INLINE-USE] user={user_id}")
    
    from handlers.templates import load_inline_templates
    templates = load_inline_templates(user_id)
    
    if not templates:
        await send(
            "❌ Нет сохранённых шаблонов\n\n"
            "Введите слова-ссылки вручную:\n"
            "<code>[слово](https://url)</code>\n\n"
            "─────────────────\n"
            "⏭ /skip | ❌ /cancel"
        )
        return
    
    # Показываем что будет добавлено
    names_list = '\n'.join([f"• {t['text']} → {t['url'][:40]}..." for t in templates])
    preview_block = preview_inline_links(templates)
    
    await send(
        f"<b>🔗 Будут добавлены:</b>\n\n"
        f"{names_list}\n\n"
        f"<b>📋 Так будет выглядеть в посте:</b>\n"
        f"<code>───</code>\n"
        f"{preview_block}\n"
        f"<code>───</code>\n\n"
        "─────────────────\n"
        "✅ /inline_yes — добавить\n"
        "❌ /skip — пропустить"
    )
    
    state.set_step(user_id, 'post_waiting_inline_confirm', {'pending_inline': templates})


async def handle_inline_confirm(user_id, send, state, max_client=None):
    """Подтверждение добавления слов-ссылок"""
    logger.info(f"[INLINE-CONFIRM] user={user_id}")
    
    session = state.get_session_data(user_id)
    templates = session.get('pending_inline', [])
    
    if not templates:
        await send("❌ Нет данных для добавления")
        state.set_step(user_id, 'post_waiting_buttons')
        return
    
    current_text = session.get('text', '')
    
    inline_block = '\n\n🔗 Полезные ссылки:\n'
    for t in templates:
        inline_block += f'• [{t["text"]}]({t["url"]})\n'
    
    if current_text:
        session['text'] = current_text + inline_block
    else:
        session['text'] = inline_block
    
    session['text'] = apply_inline_links(session['text'])
    session['inline_links'] = templates
    session.pop('pending_inline', None)
    
    logger.info(f"[INLINE-CONFIRM] Applied {len(templates)} templates")
    
    state.set_step(user_id, 'post_waiting_buttons')
    await send(
        f"<b>✅ Добавлено {len(templates)} ссылок</b>\n\n"
        "<b>🔘 Шаг 4/4: Добавьте URL-кнопки</b>\n\n"
        "📋 /btn_use — шаблоны\n\n"
        "─────────────────\n"
        "⏭ /skip — пропустить\n"
        "❌ /cancel — отмена"
    )
