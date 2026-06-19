"""
Обработчик inline-кнопок (слова-ссылки в тексте)
"""
import re
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)


def parse_inline_links(text: str) -> List[Dict]:
    """
    Парсит слова-ссылки из формата: [текст](url)
    Возвращает список: [{"text": "текст", "url": "url"}, ...]
    """
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
    """
    Конвертирует [текст](url) → <a href="url">текст</a>
    """
    logger.info(f"[INLINE-APPLY] Applying inline links to text")
    
    pattern = r'\[(.+?)\]\((https?://[^\s)]+)\)'
    result = re.sub(pattern, r'<a href="\2">\1</a>', text)
    
    if result != text:
        logger.info(f"[INLINE-APPLY] Links applied: '{result[:150]}...'")
    else:
        logger.info(f"[INLINE-APPLY] No links found")
    
    return result


async def handle_inline_text(user_id, text, send, state, max_client=None):
    """Обрабатывает введённые слова-ссылки"""
    logger.info(f"[INLINE-TEXT] user={user_id} text='{text[:100]}...'")
    
    session = state.get_session_data(user_id)
    links = parse_inline_links(text)
    
    if links:
        # Применяем ссылки к тексту
        current_text = session.get('text', '')
        session['text'] = apply_inline_links(current_text)
        session['inline_links'] = links
        logger.info(f"[INLINE-TEXT] Applied {len(links)} inline links")
    else:
        logger.info(f"[INLINE-TEXT] No inline links found in text")
    
    # Переходим к шагу 4 (кнопки под постом)
    state.set_step(user_id, 'post_waiting_buttons')
    await send("✅ Ссылки добавлены\n🔘 Шаг 4/4: Добавьте URL-кнопки\nФормат: Название | https://ссылка\n⏭ /skip | 📋 /btn_use | ❌ /cancel")


async def handle_inline_use(user_id, send, state, max_client=None):
    """Использовать сохранённые шаблоны слов-ссылок"""
    logger.info(f"[INLINE-USE] user={user_id}")
    
    session = state.get_session_data(user_id)
    
    from handlers.templates import load_inline_templates
    templates = load_inline_templates(user_id)
    
    if not templates:
        logger.info(f"[INLINE-USE] No templates found")
        await send("❌ Нет сохранённых шаблонов\nВведите слова-ссылки вручную:")
        return
    
    # Применяем шаблоны
    current_text = session.get('text', '')
    template_text = ' '.join([f'[{t["text"]}]({t["url"]})' for t in templates])
    
    if current_text:
        session['text'] = current_text + '\n\n' + template_text
    else:
        session['text'] = template_text
    
    session['text'] = apply_inline_links(session['text'])
    session['inline_links'] = templates
    
    logger.info(f"[INLINE-USE] Applied {len(templates)} templates")
    
    # Переходим к шагу 4
    state.set_step(user_id, 'post_waiting_buttons')
    await send(f"✅ Применено {len(templates)} шаблонов\n🔘 Шаг 4/4: Добавьте URL-кнопки\n⏭ /skip | 📋 /btn_use | ❌ /cancel")
