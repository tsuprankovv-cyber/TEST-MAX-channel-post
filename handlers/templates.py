"""
Управление шаблонами слов-ссылок и кнопок
"""
import json
from pathlib import Path
from typing import List, Dict
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


# === МЕНЮ ===

async def handle_templates_menu(send):
    await send(
        "<b>📋 Управление шаблонами</b>\n\n"
        "<b>🔗 Слова-ссылки:</b>\n"
        "/inline_add — добавить\n"
        "/inline_list — список\n"
        "/inline_del N — удалить\n\n"
        "<b>🔘 Кнопки под постом:</b>\n"
        "/btn_add — добавить\n"
        "/btn_list — список\n"
        "/btn_del N — удалить\n\n"
        "─────────────────\n"
        "🔙 /start — главное меню"
    )


# === ДОБАВЛЕНИЕ INLINE (пошагово) ===

async def handle_inline_add_start(user_id, send, state):
    logger.info(f"[INLINE-ADD] user={user_id}")
    state.set_step(user_id, 'inline_add_name')
    await send(
        "<b>🔗 Новое слово-ссылка</b>\n\n"
        "Введите <b>название</b>:\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_add_name(user_id, text, send, state):
    name = text.strip()
    if not name:
        await send("❌ Название не может быть пустым\nВведите название:")
        return
    
    state.set_step(user_id, 'inline_add_url', {'new_inline_name': name})
    await send(
        f"🔗 Название: <b>{name}</b>\n\n"
        "Введите <b>URL</b> (https://...):\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_add_url(user_id, text, send, state):
    session = state.get_session_data(user_id)
    name = session.get('new_inline_name', '')
    url = text.strip()
    
    if not url.startswith(('http://', 'https://')):
        await send("❌ URL должен начинаться с http:// или https://\nВведите URL ещё раз:")
        return
    
    save_inline_template(user_id, name, url)
    state.set_step(user_id, None)
    
    templates = load_inline_templates(user_id)
    lines = [f"<b>✅ Добавлено: {name}</b>\n"]
    lines.append("<b>📋 Слова-ссылки:</b>")
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']}")
    lines.append("\n─────────────────")
    lines.append("/inline_add — добавить | /inline_list — список")
    lines.append("🔙 /templates — меню шаблонов")
    
    await send('\n'.join(lines))


# === ДОБАВЛЕНИЕ BUTTON (пошагово) ===

async def handle_btn_add_start(user_id, send, state):
    logger.info(f"[BTN-ADD] user={user_id}")
    state.set_step(user_id, 'btn_add_name')
    await send(
        "<b>🔘 Новая кнопка</b>\n\n"
        "Введите <b>название</b> кнопки:\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_btn_add_name(user_id, text, send, state):
    name = text.strip()
    if not name:
        await send("❌ Название не может быть пустым\nВведите название:")
        return
    
    state.set_step(user_id, 'btn_add_url', {'new_btn_name': name})
    await send(
        f"🔘 Название: <b>{name}</b>\n\n"
        "Введите <b>URL</b> (https://...):\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_btn_add_url(user_id, text, send, state):
    session = state.get_session_data(user_id)
    name = session.get('new_btn_name', '')
    url = text.strip()
    
    if not url.startswith(('http://', 'https://')):
        await send("❌ URL должен начинаться с http:// или https://\nВведите URL ещё раз:")
        return
    
    save_button_template(user_id, name, url)
    state.set_step(user_id, None)
    
    templates = load_button_templates(user_id)
    lines = [f"<b>✅ Кнопка добавлена: {name}</b>\n"]
    lines.append("<b>🔘 Кнопки:</b>")
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']}")
    lines.append("\n─────────────────")
    lines.append("/btn_add — добавить | /btn_list — список")
    lines.append("🔙 /templates — меню шаблонов")
    
    await send('\n'.join(lines))


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
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    lines.append("\n─────────────────")
    lines.append("/inline_add | /inline_del N | 🔙 /templates")
    await send('\n'.join(lines))


async def handle_inline_del(user_id, index_str, send):
    try:
        index = int(index_str)
        if delete_inline_template(user_id, index):
            templates = load_inline_templates(user_id)
            lines = [f"<b>✅ Удалён шаблон #{index}</b>\n"]
            if templates:
                lines.append("<b>📋 Остались:</b>")
                for i, t in enumerate(templates):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("📋 Список пуст")
            lines.append("\n─────────────────")
            lines.append("/inline_add | /inline_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/inline_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /inline_del 0")


async def handle_btn_list(user_id, send):
    templates = load_button_templates(user_id)
    if not templates:
        await send(
            "📋 Список пуст\n\n"
            "─────────────────\n"
            "/btn_add — добавить | 🔙 /templates"
        )
        return
    
    lines = ["<b>🔘 Кнопки под постом:</b>\n"]
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    lines.append("\n─────────────────")
    lines.append("/btn_add | /btn_del N | 🔙 /templates")
    await send('\n'.join(lines))


async def handle_btn_del(user_id, index_str, send):
    try:
        index = int(index_str)
        if delete_button_template(user_id, index):
            templates = load_button_templates(user_id)
            lines = [f"<b>✅ Удалён шаблон #{index}</b>\n"]
            if templates:
                lines.append("<b>🔘 Остались:</b>")
                for i, t in enumerate(templates):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("🔘 Список пуст")
            lines.append("\n─────────────────")
            lines.append("/btn_add | /btn_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/btn_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /btn_del 0")


# === ИСПОЛЬЗОВАНИЕ ШАБЛОНОВ ===

async def handle_btn_use(user_id, send, state):
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
    
    names_list = '\n'.join([f"{i+1}. {t['text']} → {t['url'][:40]}..." for i, t in enumerate(templates)])
    
    await send(
        f"<b>🔘 Будут добавлены кнопки:</b>\n\n"
        f"{names_list}\n\n"
        f"<b>📋 Так будут выглядеть:</b>\n"
        f"<code>┌─────────────────┐</code>\n"
        + ''.join([f"<code>│ {t['text']} │</code>\n" for t in templates]) +
        f"<code>└─────────────────┘</code>\n\n"
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
