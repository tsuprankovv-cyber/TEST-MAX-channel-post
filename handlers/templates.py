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

def load_button_templates(user_id: int) -> List[Dict]:
    """Загружает шаблоны кнопок для пользователя"""
    data = _load(BUTTON_TEMPLATES_FILE)
    user_data = data.get(str(user_id), {})
    templates = user_data.get('templates', [])
    logger.info(f"[TEMPLATES] Loaded {len(templates)} button templates for user={user_id}")
    return templates


def save_button_template(user_id: int, text: str, url: str):
    """Сохраняет шаблон кнопки"""
    data = _load(BUTTON_TEMPLATES_FILE)
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        data[user_id_str] = {'templates': []}
    
    data[user_id_str]['templates'].append({
        "type": "link",
        "text": text,
        "url": url
    })
    _save(BUTTON_TEMPLATES_FILE, data)
    logger.info(f"[TEMPLATES] Added button: '{text}' → {url[:50]}...")


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


# === МЕНЮ ШАБЛОНОВ ===

async def handle_templates_menu(send):
    """Меню управления шаблонами"""
    await send(
        "📋 **Управление шаблонами**\n\n"
        "🔗 **Слова-ссылки:**\n"
        "/inline_add — добавить\n"
        "/inline_list — список\n"
        "/inline_del N — удалить\n\n"
        "🔘 **Кнопки под постом:**\n"
        "/btn_add — добавить\n"
        "/btn_list — список\n"
        "/btn_del N — удалить\n\n"
        "🔙 /start — главное меню"
    )


# === ДОБАВЛЕНИЕ INLINE-ШАБЛОНА (пошагово) ===

async def handle_inline_add_start(user_id, send, state):
    """Шаг 1: запрашивает название ссылки"""
    logger.info(f"[INLINE-ADD] user={user_id} — asking name")
    state.set_step(user_id, 'inline_add_name')
    await send("🔗 Введите **название** ссылки:\n❌ /cancel")


async def handle_inline_add_name(user_id, text, send, state):
    """Шаг 2: сохраняет название и запрашивает URL"""
    name = text.strip()
    if not name:
        await send("❌ Название не может быть пустым\nВведите название:")
        return
    
    logger.info(f"[INLINE-ADD] user={user_id} name='{name}'")
    state.set_step(user_id, 'inline_add_url', {'new_inline_name': name})
    await send(f"🔗 Название: **{name}**\n\nВведите **URL** (https://...):\n❌ /cancel")


async def handle_inline_add_url(user_id, text, send, state):
    """Шаг 3: сохраняет URL и показывает список"""
    session = state.get_session_data(user_id)
    name = session.get('new_inline_name', '')
    url = text.strip()
    
    if not url.startswith(('http://', 'https://')):
        await send("❌ URL должен начинаться с http:// или https://\nВведите URL ещё раз:")
        return
    
    logger.info(f"[INLINE-ADD] user={user_id} url='{url[:50]}...'")
    
    save_inline_template(user_id, name, url)
    state.set_step(user_id, None)  # Сброс шага
    
    # Показать обновлённый список
    templates = load_inline_templates(user_id)
    lines = [f"✅ Добавлено: **{name}**\n"]
    lines.append("📋 **Слова-ссылки:**")
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']}")
    lines.append("\n/inline_add — добавить | /inline_list — список\n🔙 /templates — меню шаблонов")
    
    await send('\n'.join(lines))


# === ДОБАВЛЕНИЕ BUTTON-ШАБЛОНА (пошагово) ===

async def handle_btn_add_start(user_id, send, state):
    """Шаг 1: запрашивает название кнопки"""
    logger.info(f"[BTN-ADD] user={user_id} — asking name")
    state.set_step(user_id, 'btn_add_name')
    await send("🔘 Введите **название** кнопки:\n❌ /cancel")


async def handle_btn_add_name(user_id, text, send, state):
    """Шаг 2: сохраняет название и запрашивает URL"""
    name = text.strip()
    if not name:
        await send("❌ Название не может быть пустым\nВведите название:")
        return
    
    logger.info(f"[BTN-ADD] user={user_id} name='{name}'")
    state.set_step(user_id, 'btn_add_url', {'new_btn_name': name})
    await send(f"🔘 Название: **{name}**\n\nВведите **URL** (https://...):\n❌ /cancel")


async def handle_btn_add_url(user_id, text, send, state):
    """Шаг 3: сохраняет URL и показывает список"""
    session = state.get_session_data(user_id)
    name = session.get('new_btn_name', '')
    url = text.strip()
    
    if not url.startswith(('http://', 'https://')):
        await send("❌ URL должен начинаться с http:// или https://\nВведите URL ещё раз:")
        return
    
    logger.info(f"[BTN-ADD] user={user_id} url='{url[:50]}...'")
    
    save_button_template(user_id, name, url)
    state.set_step(user_id, None)  # Сброс шага
    
    # Показать обновлённый список
    templates = load_button_templates(user_id)
    lines = [f"✅ Кнопка добавлена: **{name}**\n"]
    lines.append("🔘 **Кнопки:**")
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']}")
    lines.append("\n/btn_add — добавить | /btn_list — список\n🔙 /templates — меню шаблонов")
    
    await send('\n'.join(lines))


# === ПРОСМОТР И УДАЛЕНИЕ ===

async def handle_inline_list(user_id, send):
    """Показывает список шаблонов слов-ссылок"""
    templates = load_inline_templates(user_id)
    if not templates:
        await send("📋 Список пуст\n\n/inline_add — добавить | 🔙 /templates")
        return
    
    lines = ["📋 **Слова-ссылки:**\n"]
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    lines.append("\n/inline_add — добавить | /inline_del N — удалить\n🔙 /templates")
    await send('\n'.join(lines))


async def handle_inline_del(user_id, index_str, send):
    """Удаляет шаблон слова-ссылки"""
    try:
        index = int(index_str)
        if delete_inline_template(user_id, index):
            templates = load_inline_templates(user_id)
            lines = [f"✅ Удалён шаблон #{index}\n"]
            if templates:
                lines.append("📋 Остались:")
                for i, t in enumerate(templates):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("📋 Список пуст")
            lines.append("\n/inline_add | /inline_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/inline_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /inline_del 0\n/inline_list — посмотреть список")


async def handle_btn_list(user_id, send):
    """Показывает список шаблонов кнопок"""
    templates = load_button_templates(user_id)
    if not templates:
        await send("📋 Список пуст\n\n/btn_add — добавить | 🔙 /templates")
        return
    
    lines = ["🔘 **Кнопки под постом:**\n"]
    for i, t in enumerate(templates):
        lines.append(f"{i}. {t['text']} → {t['url'][:40]}...")
    lines.append("\n/btn_add — добавить | /btn_del N — удалить\n🔙 /templates")
    await send('\n'.join(lines))


async def handle_btn_del(user_id, index_str, send):
    """Удаляет шаблон кнопки"""
    try:
        index = int(index_str)
        if delete_button_template(user_id, index):
            templates = load_button_templates(user_id)
            lines = [f"✅ Удалён шаблон #{index}\n"]
            if templates:
                lines.append("🔘 Остались:")
                for i, t in enumerate(templates):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("🔘 Список пуст")
            lines.append("\n/btn_add | /btn_list | 🔙 /templates")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер\n/btn_list — посмотреть список")
    except ValueError:
        await send("❌ Укажите номер: /btn_del 0\n/btn_list — посмотреть список")


# === ИСПОЛЬЗОВАНИЕ ШАБЛОНОВ ===

async def handle_btn_use(user_id, send, state):
    """Использовать сохранённые шаблоны кнопок — с подтверждением"""
    logger.info(f"[BTN-USE] user={user_id}")
    
    templates = load_button_templates(user_id)
    
    if not templates:
        await send("❌ Нет сохранённых кнопок\nВведите кнопки вручную или /skip")
        return
    
    # Показываем что будет добавлено
    preview = "🔘 Будут добавлены кнопки:\n"
    for i, t in enumerate(templates):
        preview += f"{i+1}. {t['text']} → {t['url'][:40]}...\n"
    preview += "\n✅ /btn_yes — добавить\n❌ /skip — пропустить"
    
    # Сохраняем во временные данные
    state.set_step(user_id, 'post_waiting_buttons_confirm', {'pending_buttons': templates})
    await send(preview)


async def handle_btn_confirm(user_id, send, state, max_client=None):
    """Подтверждение добавления кнопок и показ предпросмотра"""
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
    
    logger.info(f"[BTN-CONFIRM] Applied {len(templates)} buttons")
    
    from handlers.preview import send_preview
    await send_preview(user_id, send, state, max_client)
