"""
Управление шаблонами слов-ссылок и кнопок
"""
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from core.logger import get_logger

logger = get_logger(__name__)

INLINE_TEMPLATES_FILE = Path('/tmp/max-bot/inline_templates.json')
BUTTON_TEMPLATES_FILE = Path('/tmp/max-bot/button_templates.json')


def _load(file_path: Path) -> Dict:
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[TEMPLATES] Load error: {e}")
    return {}


def _save(file_path: Path, data: Dict):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[TEMPLATES] Save error: {e}")


def parse_name_url(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Умный парсер: Название | https://url
    Разделители: |, -, —, →, табуляция, пробел
    """
    separators = [' | ', ' - ', ' — ', ' → ', '\t', ' |', '| ', ' -', '- ', ' —', '— ', ' →', '→ ']
    
    for sep in separators:
        if sep in text:
            parts = text.split(sep, 1)
            name = parts[0].strip()
            url = parts[1].strip()
            if url.startswith(('http://', 'https://')):
                return name, url
    
    # Ищем URL в тексте
    words = text.split()
    for word in words:
        if word.startswith(('http://', 'https://')):
            name = text.replace(word, '').strip()
            return name, word
    
    return None, None


# === INLINE-ШАБЛОНЫ ===

def load_inline_templates(user_id: int) -> List[Dict]:
    data = _load(INLINE_TEMPLATES_FILE)
    return data.get(str(user_id), {}).get('templates', [])


def save_inline_template(user_id: int, text: str, url: str):
    data = _load(INLINE_TEMPLATES_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {'templates': []}
    data[uid]['templates'].append({"text": text, "url": url})
    _save(INLINE_TEMPLATES_FILE, data)


def delete_inline_template(user_id: int, index: int):
    data = _load(INLINE_TEMPLATES_FILE)
    uid = str(user_id)
    if uid in data and 0 <= index < len(data[uid]['templates']):
        data[uid]['templates'].pop(index)
        _save(INLINE_TEMPLATES_FILE, data)
        return True
    return False


def find_duplicate_inline(user_id: int, url: str) -> Optional[Dict]:
    """Проверяет есть ли уже шаблон с таким URL"""
    templates = load_inline_templates(user_id)
    for t in templates:
        if t['url'] == url:
            return t
    return None


# === BUTTON-ШАБЛОНЫ ===

def load_button_templates(user_id: int) -> List[Dict]:
    data = _load(BUTTON_TEMPLATES_FILE)
    return data.get(str(user_id), {}).get('templates', [])


def save_button_template(user_id: int, text: str, url: str):
    data = _load(BUTTON_TEMPLATES_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {'templates': []}
    data[uid]['templates'].append({"type": "link", "text": text, "url": url})
    _save(BUTTON_TEMPLATES_FILE, data)


def delete_button_template(user_id: int, index: int):
    data = _load(BUTTON_TEMPLATES_FILE)
    uid = str(user_id)
    if uid in data and 0 <= index < len(data[uid]['templates']):
        data[uid]['templates'].pop(index)
        _save(BUTTON_TEMPLATES_FILE, data)
        return True
    return False


def find_duplicate_button(user_id: int, url: str) -> Optional[Dict]:
    """Проверяет есть ли уже кнопка с таким URL"""
    templates = load_button_templates(user_id)
    for t in templates:
        if t['url'] == url:
            return t
    return None


# === МЕНЮ ===

async def handle_templates_menu(send):
    await send(
        "<b>📋 Управление шаблонами</b>\n\n"
        "<b>🔗 Слова-ссылки:</b>\n"
        "/inline_add — добавить\n"
        "/inline_list — список (с предпросмотром)\n"
        "/inline_del N — удалить\n\n"
        "<b>🔘 Кнопки под постом:</b>\n"
        "/btn_add — добавить\n"
        "/btn_list — список (с предпросмотром)\n"
        "/btn_del N — удалить\n\n"
        "─────────────────\n"
        "📝 /post | 👁 /preview | 🔙 /start"
    )


# === ДОБАВЛЕНИЕ INLINE (пошагово) ===

async def handle_inline_add_start(user_id, send, state):
    """Шаг 1: принимает название и ссылку (можно несколько)"""
    logger.info(f"[INLINE-ADD] user={user_id}")
    state.set_step(user_id, 'inline_add_name')
    await send(
        "<b>🔗 Новые слова-ссылки</b>\n\n"
        "Отправьте названия и ссылки:\n"
        "<code>Название | https://url</code>\n"
        "<code>Название2 | https://url2</code>\n\n"
        "Разделители: <code>|</code> <code>-</code> <code>—</code> <code>→</code>\n"
        "По одной или несколько в одном сообщении.\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_add_name(user_id, text, send, state):
    """Обрабатывает названия и ссылки"""
    logger.info(f"[INLINE-ADD] user={user_id} text='{text[:100]}...'")
    
    added = []
    duplicates = []
    errors = []
    
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        name, url = parse_name_url(line)
        
        if not name or not url:
            errors.append(line[:50])
            continue
        
        # Проверка дубликата
        dup = find_duplicate_inline(user_id, url)
        if dup:
            duplicates.append((name, url, dup['text']))
            continue
        
        save_inline_template(user_id, name, url)
        added.append((name, url))
    
    state.set_step(user_id, None)
    
    # Формируем ответ
    response = []
    
    if added:
        response.append(f"<b>✅ Добавлено ({len(added)}):</b>")
        for name, url in added:
            response.append(f"• {name} → {url[:50]}...")
    
    if duplicates:
        response.append(f"\n<b>⚠️ Уже есть ({len(duplicates)}):</b>")
        for name, url, existing in duplicates:
            response.append(f"• {name} → уже сохранено как «{existing}»")
    
    if errors:
        response.append(f"\n<b>❌ Не распознано ({len(errors)}):</b>")
        for e in errors:
            response.append(f"• {e}")
    
    # Показать полный список
    templates = load_inline_templates(user_id)
    if templates:
        response.append(f"\n<b>📋 Все ссылки ({len(templates)}):</b>")
        for i, t in enumerate(templates, 1):
            response.append(f"{i}. {t['text']} → {t['url'][:40]}...")
        # Предпросмотр
        response.append(f"\n<b>👁 Предпросмотр:</b>")
        response.append("🔗 Полезные ссылки:")
        for i, t in enumerate(templates, 1):
            response.append(f"{i}. {t['text']}")
    
    response.append("\n─────────────────")
    response.append("/inline_add — добавить | /inline_list — список")
    response.append("🔙 /templates — меню шаблонов")
    
    await send('\n'.join(response))


# === ДОБАВЛЕНИЕ BUTTON (пошагово) ===

async def handle_btn_add_start(user_id, send, state):
    """Шаг 1: принимает названия и ссылки кнопок"""
    logger.info(f"[BTN-ADD] user={user_id}")
    state.set_step(user_id, 'btn_add_name')
    await send(
        "<b>🔘 Новые кнопки</b>\n\n"
        "Отправьте названия и ссылки:\n"
        "<code>Название | https://url</code>\n"
        "<code>Название2 | https://url2</code>\n\n"
        "Разделители: <code>|</code> <code>-</code> <code>—</code> <code>→</code>\n"
        "По одной или несколько в одном сообщении.\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_btn_add_name(user_id, text, send, state):
    """Обрабатывает названия и ссылки кнопок"""
    logger.info(f"[BTN-ADD] user={user_id} text='{text[:100]}...'")
    
    added = []
    duplicates = []
    errors = []
    
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        name, url = parse_name_url(line)
        
        if not name or not url:
            errors.append(line[:50])
            continue
        
        # Проверка дубликата
        dup = find_duplicate_button(user_id, url)
        if dup:
            duplicates.append((name, url, dup['text']))
            continue
        
        save_button_template(user_id, name, url)
        added.append((name, url))
    
    state.set_step(user_id, None)
    
    # Формируем ответ
    response = []
    
    if added:
        response.append(f"<b>✅ Добавлено ({len(added)}):</b>")
        for name, url in added:
            response.append(f"• {name}")
    
    if duplicates:
        response.append(f"\n<b>⚠️ Уже есть ({len(duplicates)}):</b>")
        for name, url, existing in duplicates:
            response.append(f"• {name} → уже сохранено как «{existing}»")
    
    if errors:
        response.append(f"\n<b>❌ Не распознано ({len(errors)}):</b>")
        for e in errors:
            response.append(f"• {e}")
    
    # Показать полный список
    templates = load_button_templates(user_id)
    if templates:
        response.append(f"\n<b>🔘 Все кнопки ({len(templates)}):</b>")
        for i, t in enumerate(templates, 1):
            response.append(f"{i}. {t['text']}")
    
    response.append("\n─────────────────")
    response.append("/btn_add — добавить | /btn_list — список")
    response.append("🔙 /templates — меню шаблонов")
    
    await send('\n'.join(response))


# === ПРОСМОТР И УДАЛЕНИЕ ===

async def handle_inline_list(user_id, send):
    templates = load_inline_templates(user_id)
    if not templates:
        await send(
            "📋 Список пуст\n\n"
            "─────────────────\n"
            "/inline_add — добавить | 🔙 /templates"
        )
        return
    
    lines = ["<b>📋 Слова-ссылки:</b>\n"]
    for i, t in enumerate(templates, 1):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    
    # Предпросмотр готового вида
    lines.append(f"\n<b>👁 Предпросмотр:</b>")
    lines.append("🔗 Полезные ссылки:")
    for i, t in enumerate(templates, 1):
        lines.append(f"{i}. {t['text']}")
    
    lines.append("\n─────────────────")
    lines.append("/inline_add | /inline_del N | 🔙 /templates")
    await send('\n'.join(lines))


async def handle_inline_del(user_id, index_str, send):
    try:
        index = int(index_str) - 1  # Пользователь вводит с 1
        if delete_inline_template(user_id, index):
            templates = load_inline_templates(user_id)
            lines = [f"<b>✅ Удалён шаблон #{index + 1}</b>\n"]
            if templates:
                lines.append("<b>📋 Остались:</b>")
                for i, t in enumerate(templates, 1):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("📋 Список пуст")
            lines.append("\n─────────────────")
            lines.append("/inline_add | /inline_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/inline_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /inline_del 1\n/inline_list — посмотреть список")


async def handle_btn_list(user_id, send, max_client=None):
    templates = load_button_templates(user_id)
    if not templates:
        await send(
            "📋 Список пуст\n\n"
            "─────────────────\n"
            "/btn_add — добавить | 🔙 /templates"
        )
        return
    
    lines = ["<b>🔘 Кнопки под постом:</b>\n"]
    for i, t in enumerate(templates, 1):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    
    lines.append("\n─────────────────")
    lines.append("/btn_add | /btn_del N | 🔙 /templates")
    await send('\n'.join(lines))


async def handle_btn_del(user_id, index_str, send):
    try:
        index = int(index_str) - 1  # Пользователь вводит с 1
        if delete_button_template(user_id, index):
            templates = load_button_templates(user_id)
            lines = [f"<b>✅ Удалён шаблон #{index + 1}</b>\n"]
            if templates:
                lines.append("<b>🔘 Остались:</b>")
                for i, t in enumerate(templates, 1):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("🔘 Список пуст")
            lines.append("\n─────────────────")
            lines.append("/btn_add | /btn_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/btn_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /btn_del 1\n/btn_list — посмотреть список")


# === ИСПОЛЬЗОВАНИЕ ШАБЛОНОВ ===

async def handle_btn_use(user_id, send, state, max_client=None):
    logger.info(f"[BTN-USE] user={user_id}")
    
    templates = load_button_templates(user_id)
    
    if not templates:
        await send(
            "❌ Нет сохранённых кнопок\n\n"
            "Введите кнопки вручную:\n"
            "<code>Название | https://url</code>\n\n"
            "─────────────────\n"
            "⏭ /skip | ❌ /cancel"
        )
        return
    
    names_list = '\n'.join([f"{i}. {t['text']}" for i, t in enumerate(templates, 1)])
    
    # Отправляем сообщение с НАСТОЯЩИМИ кнопками для предпросмотра
    chat_id = state.get_session(user_id).get('chat_id', user_id)
    if max_client:
        await max_client.send_message(
            chat_id=chat_id,
            text=f"<b>🔘 Предпросмотр кнопок:</b>",
            buttons=[[t] for t in templates],
            use_html_format=True
        )
    
    await send(
        f"<b>🔘 Будут добавлены кнопки ({len(templates)}):</b>\n\n"
        f"{names_list}\n\n"
        "─────────────────\n"
        "✅ /btn_yes — добавить\n"
        "❌ /skip — пропустить"
    )
    
    state.set_step(user_id, 'post_waiting_buttons_confirm', {'pending_buttons': templates})


async def handle_btn_confirm(user_id, send, state, max_client=None):
    logger.info(f"[BTN-CONFIRM] user={user_id}")
    
    session = state.get_session_data(user_id)
    templates = session.get('pending_buttons', [])
    
    if not templates:
        await send("❌ Нет данных для добавления")
        state.set_step(user_id, 'post_waiting_buttons')
        return
    
    session['buttons'] = [[t] for t in templates]
    session.pop('pending_buttons', None)
    state.save_draft(user_id, session.copy())
    state.set_step(user_id, 'post_ready')
    
    from handlers.preview import send_preview
    await send_preview(user_id, send, state, max_client)
