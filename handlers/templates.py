"""
Управление шаблонами слов-ссылок и кнопок
"""
import json
from pathlib import Path
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)

# Пути к файлам шаблонов
INLINE_TEMPLATES_FILE = Path('/tmp/max-bot/inline_templates.json')
BUTTON_TEMPLATES_FILE = Path('/tmp/max-bot/button_templates.json')


def _load(file_path: Path) -> Dict:
    """Загружает шаблоны из файла"""
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[TEMPLATES] Load error: {e}")
    return {}


def _save(file_path: Path, data: Dict):
    """Сохраняет шаблоны в файл"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"[TEMPLATES] Saved to {file_path}")
    except Exception as e:
        logger.error(f"[TEMPLATES] Save error: {e}")


# === INLINE-ШАБЛОНЫ (слова-ссылки) ===

def load_inline_templates(user_id: int) -> List[Dict]:
    """Загружает шаблоны слов-ссылок для пользователя"""
    data = _load(INLINE_TEMPLATES_FILE)
    user_data = data.get(str(user_id), {})
    templates = user_data.get('templates', [])
    logger.info(f"[TEMPLATES] Loaded {len(templates)} inline templates for user={user_id}")
    return templates


def save_inline_template(user_id: int, text: str, url: str):
    """Сохраняет шаблон слова-ссылки"""
    data = _load(INLINE_TEMPLATES_FILE)
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        data[user_id_str] = {'templates': []}
    
    data[user_id_str]['templates'].append({"text": text, "url": url})
    _save(INLINE_TEMPLATES_FILE, data)
    logger.info(f"[TEMPLATES] Added inline: '{text}' → {url[:50]}...")


def delete_inline_template(user_id: int, index: int):
    """Удаляет шаблон слова-ссылки по индексу"""
    data = _load(INLINE_TEMPLATES_FILE)
    user_id_str = str(user_id)
    
    if user_id_str in data and 0 <= index < len(data[user_id_str]['templates']):
        deleted = data[user_id_str]['templates'].pop(index)
        _save(INLINE_TEMPLATES_FILE, data)
        logger.info(f"[TEMPLATES] Deleted inline: '{deleted['text']}'")
        return True
    return False


# === BUTTON-ШАБЛОНЫ (кнопки под постом) ===

def load_button_templates(user_id: int) -> List[List[Dict]]:
    """Загружает шаблоны кнопок для пользователя"""
    data = _load(BUTTON_TEMPLATES_FILE)
    user_data = data.get(str(user_id), {})
    templates = user_data.get('templates', [])
    logger.info(f"[TEMPLATES] Loaded {len(templates)} button templates for user={user_id}")
    return templates


def save_button_template(user_id: int, text: str, url: str, style: str = "primary"):
    """Сохраняет шаблон кнопки"""
    data = _load(BUTTON_TEMPLATES_FILE)
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        data[user_id_str] = {'templates': []}
    
    data[user_id_str]['templates'].append({
        "type": "link",
        "text": text,
        "url": url,
        "style": style
    })
    _save(BUTTON_TEMPLATES_FILE, data)
    logger.info(f"[TEMPLATES] Added button: '{text}' → {url[:50]}... style={style}")


def delete_button_template(user_id: int, index: int):
    """Удаляет шаблон кнопки по индексу"""
    data = _load(BUTTON_TEMPLATES_FILE)
    user_id_str = str(user_id)
    
    if user_id_str in data and 0 <= index < len(data[user_id_str]['templates']):
        deleted = data[user_id_str]['templates'].pop(index)
        _save(BUTTON_TEMPLATES_FILE, data)
        logger.info(f"[TEMPLATES] Deleted button: '{deleted['text']}'")
        return True
    return False


async def handle_templates_menu(send):
    """Меню управления шаблонами"""
    await send(
        "📋 **Управление шаблонами**\n\n"
        "🔗 **Слова-ссылки:**\n"
        "/inline_add Название | url — добавить\n"
        "/inline_list — список\n"
        "/inline_del N — удалить\n\n"
        "🔘 **Кнопки под постом:**\n"
        "/btn_add Название | url — добавить\n"
        "/btn_list — список\n"
        "/btn_del N — удалить\n\n"
        "🎨 **Цвет кнопок:**\n"
        "/test_colors — тест цветов"
    )


async def handle_inline_add(user_id, text, send):
    """Добавляет шаблон слова-ссылки"""
    for sep in [' | ', ' - ', ' → ']:
        if sep in text:
            parts = text.split(sep, 1)
            link_text = parts[0].strip()
            link_url = parts[1].strip()
            if link_text and link_url.startswith(('http://', 'https://')):
                save_inline_template(user_id, link_text, link_url)
                await send(f"✅ Добавлено: [{link_text}]({link_url[:40]}...)")
                return
    await send("❌ Формат: /inline_add Название | https://url")


async def handle_inline_list(user_id, send):
    """Показывает список шаблонов слов-ссылок"""
    templates = load_inline_templates(user_id)
    if not templates:
        await send("📋 Список пуст")
        return
    
    lines = ["📋 **Слова-ссылки:**\n"]
    for i, t in enumerate(templates):
        lines.append(f"{i}. [{t['text']}]({t['url'][:40]}...)")
    await send('\n'.join(lines))


async def handle_inline_del(user_id, index_str, send):
    """Удаляет шаблон слова-ссылки"""
    try:
        index = int(index_str)
        if delete_inline_template(user_id, index):
            await send(f"✅ Удалён шаблон #{index}")
        else:
            await send("❌ Неверный номер")
    except ValueError:
        await send("❌ Укажите номер: /inline_del 0")


async def handle_btn_add(user_id, text, send):
    """Добавляет шаблон кнопки"""
    for sep in [' | ', ' - ', ' → ']:
        if sep in text:
            parts = text.split(sep, 1)
            btn_text = parts[0].strip()
            btn_url = parts[1].strip()
            if btn_text and btn_url.startswith(('http://', 'https://')):
                save_button_template(user_id, btn_text, btn_url)
                await send(f"✅ Кнопка: {btn_text} → {btn_url[:40]}...")
                return
    await send("❌ Формат: /btn_add Название | https://url")


async def handle_btn_list(user_id, send):
    """Показывает список шаблонов кнопок"""
    templates = load_button_templates(user_id)
    if not templates:
        await send("📋 Список пуст")
        return
    
    lines = ["🔘 **Кнопки под постом:**\n"]
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    await send('\n'.join(lines))


async def handle_btn_del(user_id, index_str, send):
    """Удаляет шаблон кнопки"""
    try:
        index = int(index_str)
        if delete_button_template(user_id, index):
            await send(f"✅ Удалён шаблон #{index}")
        else:
            await send("❌ Неверный номер")
    except ValueError:
        await send("❌ Укажите номер: /btn_del 0")


async def handle_btn_use(user_id, send, state):
    """Использовать сохранённые шаблоны кнопок"""
    logger.info(f"[BTN-USE] user={user_id}")
    
    templates = load_button_templates(user_id)
    
    if not templates:
        await send("❌ Нет сохранённых кнопок\nВведите кнопки вручную:")
        return
    
    session = state.get_session_data(user_id)
    session['buttons'] = [[t] for t in templates]  # Каждая кнопка в отдельном ряду
    state.save_draft(user_id, session.copy())
    state.set_step(user_id, 'post_ready')
    
    from handlers.preview import send_preview
    from api.client import MAXClient
    
    logger.info(f"[BTN-USE] Applied {len(templates)} button templates")
    await send(f"✅ Применено {len(templates)} кнопок")
