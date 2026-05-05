"""
MAX Channel Poster Bot — CORE FIX v4.0
🔥 Исправлены: кнопки, медиа, форматирование
🔥 Добавлено: редактирование после предпросмотра
"""
import asyncio
import logging
import os
import json
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union, Tuple
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout, FormData
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===================================================================
# 🔧 CONFIG & INIT
# ===================================================================
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG').upper()
MAX_MEDIA_ITEMS = int(os.getenv('MAX_MEDIA_ITEMS', '10'))
SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '120'))

DATA_DIR = Path(os.getenv('DATA_DIR', '/tmp/max-bot'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_FILE = DATA_DIR / 'authorized_users.json'
STATS_FILE = DATA_DIR / 'stats.json'
MEDIA_CACHE_DIR = DATA_DIR / 'media_cache'
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

log_file = DATA_DIR / 'bot.log'
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format='%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding='utf-8', mode='a', delay=True)
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"🔧 LOG_LEVEL={LOG_LEVEL}")

# ===================================================================
# 🎨 MARKUP → HTML КОНВЕРТЕР (из пересыльщика)
# ===================================================================
MAX_TAG_MAP = {
    "strong": "b", "bold": "b",
    "emphasized": "i", "italic": "i", "em": "i",
    "underline": "u", "u": "u", "ins": "u",
    "strikethrough": "s", "strike": "s", "s": "s", "del": "s",
    "code": "code", "inline-code": "code",
    "spoiler": "tg-spoiler",
    "link": "a", "text_link": "a", "url": "a",
}

def normalize_max_offset(text: str, max_offset: int, max_length: int = None) -> Tuple[int, int]:
    """Корректирует offset из UTF-16 (MAX) в Python-индексы"""
    python_offset = 0
    utf16_pos = 0
    for i, char in enumerate(text):
        if utf16_pos >= max_offset:
            python_offset = i
            break
        utf16_pos += len(char.encode('utf-16-le')) // 2
    else:
        python_offset = len(text)
    
    if max_length is not None:
        python_length = 0
        utf16_pos = max_offset
        for i in range(python_offset, len(text)):
            if utf16_pos >= max_offset + max_length:
                break
            utf16_pos += len(text[i].encode('utf-16-le')) // 2
            python_length += 1
        return python_offset, python_length
    
    return python_offset, max_length

def filter_overlapping_same_type(markup: List[Dict]) -> List[Dict]:
    """Убирает вложенные сущности одного типа"""
    if not markup:
        return []
    filtered = []
    for i, entity in enumerate(markup):
        etype = entity.get('type', '')
        offset = entity.get('from', 0)
        length = entity.get('length', 0)
        end = offset + length
        is_nested = False
        for j, other in enumerate(markup):
            if i == j:
                continue
            if other.get('type') != etype:
                continue
            other_offset = other.get('from', 0)
            other_end = other_offset + other.get('length', 0)
            if other_offset <= offset and other_end >= end and (other_offset < offset or other_end > end):
                is_nested = True
                break
        if not is_nested:
            filtered.append(entity)
    return filtered

def apply_markup(text: str, markup: List[Dict]) -> str:
    """
    Конвертирует MAX markup в HTML (как в пересыльщике!)
    🔥 Это ключевая функция для форматирования
    """
    if not markup or not text:
        return text
    
    logger.info(f"[MARKUP] Applying {len(markup)} entities to text (len={len(text)})")
    
    # Фильтруем вложенные
    markup = filter_overlapping_same_type(markup)
    
    # Корректируем offset'ы
    corrected = []
    for entity in markup:
        entity = entity.copy()
        max_offset = entity.get('from', 0)
        max_length = entity.get('length', 0)
        py_offset, py_length = normalize_max_offset(text, max_offset, max_length)
        entity['from'] = py_offset
        entity['length'] = py_length
        corrected.append(entity)
    
    # Сортируем по позиции
    sorted_markup = sorted(corrected, key=lambda m: (m.get('from', 0), -m.get('length', 0)))
    
    # Строим карту тегов
    tag_starts = {}  # позиция → [открывающие теги]
    tag_ends = {}    # позиция → [закрывающие теги]
    
    for entity in sorted_markup:
        offset = entity.get('from', 0)
        length = entity.get('length', 0)
        etype = entity.get('type', '')
        
        if etype not in MAX_TAG_MAP:
            continue
        
        tag_name = MAX_TAG_MAP[etype]
        
        if etype in ('link', 'text_link', 'url'):
            url = entity.get('url', '').replace('"', '&quot;')
            if url:
                open_tag = f'<{tag_name} href="{url}">'
            else:
                open_tag = f'<{tag_name}>'
        else:
            open_tag = f'<{tag_name}>'
        
        close_tag = f'</{tag_name}>'
        
        if offset not in tag_starts:
            tag_starts[offset] = []
        tag_starts[offset].append(open_tag)
        
        end_pos = offset + length
        if end_pos not in tag_ends:
            tag_ends[end_pos] = []
        tag_ends[end_pos].append(close_tag)
        
        logger.debug(f"[MARKUP] {etype} → {open_tag} [{offset}:{end_pos}]")
    
    # Собираем финальный HTML
    result = []
    for i, char in enumerate(text):
        # Сначала закрываем теги на этой позиции (в обратном порядке)
        if i in tag_ends:
            for close_tag in tag_ends[i]:
                result.append(close_tag)
        
        # Потом открываем новые теги
        if i in tag_starts:
            for open_tag in tag_starts[i]:
                result.append(open_tag)
        
        result.append(char)
    
    # Закрываем оставшиеся теги в конце
    last_pos = len(text)
    if last_pos in tag_ends:
        for close_tag in tag_ends[last_pos]:
            result.append(close_tag)
    
    final_text = ''.join(result)
    logger.info(f"[MARKUP] Output: {final_text[:200]}...")
    return final_text

def strip_html_tags(text: str) -> str:
    """Убирает HTML-теги для отображения в превью"""
    clean = re.sub(r'<[^>]+>', '', text)
    return clean

# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    def __init__(self, password: str, auth_file: Path):
        self.password = password
        self.auth_file = auth_file
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] Loaded {len(self.authorized)} users")
            except Exception as e:
                logger.error(f"[AUTH] Load error: {e}")
    
    def _save_to_file(self):
        try:
            data = {
                'users': {str(k): v for k, v in self.authorized.items()},
                'failed': {str(k): v for k, v in self.failed_attempts.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[AUTH] Save error: {e}")
    
    def check_password(self, user_id: int, password: str) -> bool:
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat(),
                'password_hash': hashlib.sha256(self.password.encode()).hexdigest()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save_to_file()
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
    
    def list_authorized(self) -> List[Dict]:
        return [{'user_id': uid, 'auth_time': data['auth_time']} for uid, data in self.authorized.items()]
    
    def change_password(self, new_password: str):
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()

# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
    
    def get_session(self, user_id: int) -> Dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Optional[Dict] = None):
        session = self.get_session(user_id)
        session['step'] = step
        if data is not None:
            session['data'].update(data)
    
    def get_step(self, user_id: int) -> Optional[str]:
        return self.sessions.get(user_id, {}).get('step')
    
    def get_session_data(self, user_id: int) -> Dict:
        return self.sessions.get(user_id, {}).get('data', {})
    
    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
    
    def save_draft(self, user_id: int, draft: Dict):
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]

# ===================================================================
# 📡 MAX API CLIENT (ИСПРАВЛЕНО)
# ===================================================================
class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
    
    async def init(self):
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
    
    async def close(self):
        if self.session is not None:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                       max_retries: int = 3) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/4.0"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.debug(f"[MAX] Body: {json.dumps(data, ensure_ascii=False)[:300] if data else 'None'}")
        
        for attempt in range(max_retries):
            try:
                async with self.session.request(
                    method=method, url=url, headers=headers,
                    json=data, timeout=self.timeout
                ) as response:
                    text = await response.text()
                    logger.info(f"[MAX] ← {response.status} | {text[:200]}")
                    
                    if response.status == 200:
                        try:
                            return json.loads(text) if text.strip() else {}
                        except json.JSONDecodeError:
                            return {"raw": text}
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 30))
                        await asyncio.sleep(retry_after)
                        continue
                    
                    return {"error": f"HTTP_{response.status}", "detail": text}
                    
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "timeout"}
            except Exception as e:
                logger.error(f"[MAX] Error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "exception", "detail": str(e)}
        
        return {"error": "max_retries_exceeded"}
    
    # 🔥 ИСПРАВЛЕНО: Правильная отправка сообщений
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          reply_markup: Optional[Dict] = None,
                          attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Отправляет сообщение в MAX.
        🔥 reply_markup — правильное поле для кнопок!
        🔥 attachments — оригинальный формат MAX (payload)
        """
        logger.info(f"[MAX] 📤 send_message(chat_id={chat_id}, text_len={len(text)})")
        
        payload = {"text": text}
        
        # Кнопки через reply_markup (как в оригинальном MAX API!)
        if reply_markup is not None and reply_markup.get('inline_keyboard'):
            payload["reply_markup"] = reply_markup
            logger.debug(f"[MAX] reply_markup: {len(reply_markup['inline_keyboard'])} rows")
        
        # Медиа через attachments (оригинальный формат)
        if attachments is not None and len(attachments) > 0:
            payload["attachments"] = attachments
            logger.debug(f"[MAX] attachments: {len(attachments)} items")
        
        endpoint = f"/messages?chat_id={chat_id}"
        return await self._request("POST", endpoint, data=payload)
    
    async def edit_message(self, message_id: str, text: Optional[str] = None,
                          reply_markup: Optional[Dict] = None) -> Dict:
        logger.info(f"[MAX] ✏️ edit_message(message_id={message_id})")
        
        payload = {}
        if text is not None:
            payload["text"] = text
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        
        endpoint = f"/messages/{message_id}"
        return await self._request("PUT", endpoint, data=payload)
    
    async def get_message_stats(self, message_id: str) -> Dict:
        endpoint = f"/messages/{message_id}/stats"
        return await self._request("GET", endpoint)
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        body = {
            "url": webhook_url,
            "chat_id": chat_id,
            "update_types": ["message_created"]
        }
        result = await self._request("POST", "/subscriptions", data=body)
        return "error" not in result

# ===================================================================
# 🖼 MEDIA MANAGER (ИСПРАВЛЕНО)
# ===================================================================
class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
    
    # 🔥 ИСПРАВЛЕНО: Сохраняем оригинальный payload
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """
        Парсит вложения из сообщения MAX.
        🔥 Сохраняет оригинальный payload для обратной отправки!
        """
        logger.info(f"[MEDIA] Parsing {len(attachments)} attachments")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            # Сохраняем все типы с оригинальным payload
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                result.append({
                    'type': att_type,
                    'payload': payload.copy(),  # Сохраняем копию payload
                    'url': payload.get('url') or att.get('url', ''),
                    'filename': payload.get('filename') or att.get('title', f'file_{i}'),
                    'index': i
                })
                logger.debug(f"[MEDIA] #{i}: type={att_type}, filename={payload.get('filename', 'N/A')}")
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} items")
        return result

# ===================================================================
# 📊 STATS MODULE
# ===================================================================
class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        self._load_from_file()
    
    def _load_from_file(self):
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.stats = data.get('messages', {})
            except Exception:
                pass
    
    def _save_to_file(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump({'messages': self.stats, 'updated_at': datetime.now().isoformat()}, f, indent=2)
        except Exception:
            pass
    
    def record_message(self, message_id: str, chat_id: str, text: str, published_at: str):
        self.stats[message_id] = {
            'chat_id': chat_id,
            'text_preview': text[:100],
            'published_at': published_at,
            'views': 0
        }
        self._save_to_file()
    
    def get_stats(self, message_id: Optional[str] = None):
        if message_id:
            return self.stats.get(message_id, {})
        return [{'message_id': mid, **data} for mid, data in self.stats.items()]

# ===================================================================
# ⏰ SCHEDULER
# ===================================================================
class PublishScheduler:
    def __init__(self, max_client: MAXClient, channel_id: str):
        self.max_client = max_client
        self.channel_id = channel_id
        self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        self.scheduled_posts: Dict[str, Dict] = {}
    
    def start(self):
        self.scheduler.start()
    
    def stop(self):
        self.scheduler.shutdown()
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id: int, post_data: Dict, publish_at: str) -> Optional[str]:
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def publish_job():
            logger.info(f"[SCHEDULER] Publishing {job_id}")
            await self.max_client.send_message(
                chat_id=self.channel_id,
                text=post_data.get('text', ''),
                reply_markup=post_data.get('reply_markup'),
                attachments=post_data.get('attachments')
            )
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(publish_job, trigger=trigger, id=job_id, replace_existing=True)
        self.scheduled_posts[job_id] = {
            'user_id': user_id,
            'publish_at': publish_at,
            'scheduled_at': datetime.now().isoformat()
        }
        return job_id

# ===================================================================
# 🎮 COMMAND HANDLERS (ИСПРАВЛЕНО)
# ===================================================================
class CommandHandlers:
    def __init__(self, auth: AuthManager, state: StateManager, 
                 max_client: MAXClient, media_mgr: MediaManager,
                 scheduler: PublishScheduler, stats: StatsCollector,
                 channel_id: str):
        self.auth = auth
        self.state = state
        self.max_client = max_client
        self.media_mgr = media_mgr
        self.scheduler = scheduler
        self.stats = stats
        self.channel_id = channel_id
    
    async def handle_start(self, user_id: int, chat_id: int, send_callback):
        logger.info(f"[CMD] /start from user={user_id}")
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль для доступа:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        # 🔥 Главное меню с кнопками
        menu_keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "url": "max://new_post"}],
                [{"text": "📊 Статистика", "url": "max://stats"}],
                [{"text": "⚙️ Настройки", "url": "max://settings"}]
            ]
        }
        
        await send_callback(
            "👋 **MAX Channel Poster**\n\n"
            "📝 `/post` — создать новый пост\n"
            "👁 `/preview` — предпросмотр\n"
            "🚀 `/publish` — опубликовать\n"
            "❌ `/cancel` — отменить",
            reply_markup=menu_keyboard
        )
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            session = self.state.get_session(user_id)
            chat_id = session.get('chat_id', user_id)
            await self.handle_start(user_id, chat_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много попыток. Попробуйте позже.")
    
    async def handle_post_command(self, user_id: int, send_callback):
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала /start")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        await send_callback(
            "📝 **Создание поста**\n\n"
            "1. Отправьте текст (можно с форматированием)\n"
            "2. Прикрепите фото/видео/файлы (до 10 шт)\n"
            "3. Добавьте кнопки в формате:\n"
            "   `Название кнопки | https://ссылка`\n\n"
            "После отправки текста перейдём к кнопкам 👇"
        )
    
    # 🔥 ИСПРАВЛЕНО: Сохраняем markup и конвертируем в HTML
    async def handle_post_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        logger.info(f"[CMD] Got post text (len={len(text)}, markup={len(markup)}, attachments={len(raw_attachments)})")
        
        session = self.state.get_session_data(user_id)
        
        # Конвертируем markup в HTML
        if markup:
            formatted_text = apply_markup(text, markup)
        else:
            formatted_text = text
        
        # Сохраняем всё
        session['text'] = formatted_text
        session['raw_text'] = text
        session['markup'] = markup
        
        # 🔥 Парсим вложения и сохраняем оригинальный payload
        attachments = self.media_mgr.parse_attachments(raw_attachments)
        session['raw_attachments'] = raw_attachments  # Оригинальные
        session['attachments'] = attachments           # Распарсенные
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        
        await send_callback(
            "🔘 **Добавьте кнопки**\n\n"
            "Формат (каждая кнопка с новой строки):\n"
            "`Название | https://ссылка`\n\n"
            "Пример:\n"
            "Купить | https://shop.ru\n"
            "Подробнее | https://info.ru\n\n"
            "Напишите `пропустить` если кнопки не нужны"
        )
    
    # 🔥 ИСПРАВЛЕНО: Кнопки в reply_markup формате
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        logger.info(f"[CMD] Got buttons: '{buttons_text[:100]}...'")
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            button_rows = []
        else:
            button_rows = self.parse_buttons(buttons_text)
        
        # Формируем reply_markup
        reply_markup = None
        if button_rows:
            reply_markup = {"inline_keyboard": button_rows}
        
        session['reply_markup'] = reply_markup
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        # 🔥 ОТПРАВЛЯЕМ ПРЕДПРОСМОТР
        await self.send_preview(user_id, send_callback, session)
    
    def parse_buttons(self, text: str) -> List[List[Dict]]:
        """Парсит кнопки из текста в формат inline_keyboard"""
        rows = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            btn = None
            for sep in [' | ', ' - ', ' → ', ' -> ', ' — ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max://')):
                        btn = {'text': btn_text, 'url': btn_url}
                        break
            
            if btn is not None:
                rows.append([btn])
                logger.debug(f"[BUTTONS] Parsed: '{btn['text']}' → {btn['url']}")
        
        return rows
    
    # 🔥 НОВОЕ: Отправка предпросмотра
    async def send_preview(self, user_id: int, send_callback, draft: Optional[Dict] = None):
        """Отправляет предпросмотр поста с кнопками"""
        if draft is None:
            draft = self.state.get_draft(user_id)
        
        if draft is None or 'text' not in draft:
            await send_callback("❌ Нет черновика для предпросмотра")
            return
        
        text = draft['text']
        reply_markup = draft.get('reply_markup')
        attachments = draft.get('attachments', [])
        
        # Формируем превью
        preview_parts = ["👁 **ПРЕДПРОСМОТР ПОСТА**\n"]
        preview_parts.append("─" * 30)
        
        # Текст (с форматированием)
        preview_parts.append(f"\n{text}")
        
        # Медиа
        if attachments:
            preview_parts.append(f"\n📎 **Вложения ({len(attachments)}):**")
            for i, att in enumerate(attachments, 1):
                att_type = att.get('type', 'файл')
                filename = att.get('filename', f'файл_{i}')
                preview_parts.append(f"  {i}. [{att_type}] {filename}")
        
        # Кнопки
        if reply_markup and reply_markup.get('inline_keyboard'):
            preview_parts.append("\n🔘 **Кнопки:**")
            for i, row in enumerate(reply_markup['inline_keyboard'], 1):
                for btn in row:
                    preview_parts.append(f"  {i}. {btn['text']} → {btn['url'][:50]}...")
        
        preview_parts.append("\n" + "─" * 30)
        preview_parts.append("\n✅ `/publish` — опубликовать")
        preview_parts.append("✏️ `/edit` — редактировать")
        preview_parts.append("📅 `/schedule ГГГГ-ММ-ДД ЧЧ:ММ` — отложить")
        preview_parts.append("❌ `/cancel` — отменить")
        
        # Отправляем превью С КНОПКАМИ
        await send_callback('\n'.join(preview_parts), reply_markup=reply_markup)
        
        # Отправляем медиа отдельно для визуального превью
        for att in attachments:
            url = att.get('url')
            if url and att.get('type') in ('image', 'photo'):
                await send_callback(f"🖼 {att.get('filename', 'Фото')}: {url}")
    
    async def handle_preview(self, user_id: int, send_callback):
        """Показать превью ещё раз"""
        await self.send_preview(user_id, send_callback)
    
    # 🔥 НОВОЕ: Команда редактирования
    async def handle_edit(self, user_id: int, send_callback):
        """Возвращает к редактированию после предпросмотра"""
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send_callback("❌ Нет черновика. Создайте новый пост: /post")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        edit_keyboard = {
            "inline_keyboard": [
                [{"text": "📝 Редактировать текст", "url": "max://edit_text"}],
                [{"text": "🖼 Редактировать медиа", "url": "max://edit_media"}],
                [{"text": "🔘 Редактировать кнопки", "url": "max://edit_buttons"}]
            ]
        }
        
        await send_callback(
            "✏️ **Редактирование поста**\n\n"
            "Что хотите изменить?\n\n"
            "• Отправьте новый текст — заменит текст\n"
            "• Отправьте новое фото — добавит к вложениям\n"
            "• `/buttons` — перейти к редактированию кнопок\n"
            "• `/preview` — посмотреть результат",
            reply_markup=edit_keyboard
        )
    
    async def handle_edit_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        """Замена текста при редактировании"""
        session = self.state.get_session_data(user_id)
        
        if markup:
            session['text'] = apply_markup(text, markup)
        else:
            session['text'] = text
        
        session['raw_text'] = text
        session['markup'] = markup
        
        # Обновляем вложения если прислали новые
        if raw_attachments:
            new_attachments = self.media_mgr.parse_attachments(raw_attachments)
            existing = session.get('attachments', [])
            session['attachments'] = existing + new_attachments
            session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
        
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        await send_callback("✅ Текст обновлён!")
        await self.send_preview(user_id, send_callback, session)
    
    # 🔥 ИСПРАВЛЕНО: Публикация с правильными форматами
    async def handle_publish(self, user_id: int, send_callback, 
                            immediate: bool = True, schedule_time: Optional[str] = None):
        logger.info(f"[CMD] 🚀 Publish (immediate={immediate})")
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден. Создайте: /post")
            return
        
        if not immediate and schedule_time:
            job_id = self.scheduler.schedule_post(user_id, draft, schedule_time)
            if job_id:
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send_callback(f"✅ Запланировано на {schedule_time}")
            else:
                await send_callback("❌ Неверный формат даты (ГГГГ-ММ-ДД ЧЧ:ММ)")
            return
        
        await send_callback("⏳ Публикую...")
        
        # 🔥 Используем оригинальные attachments (с payload!)
        attachments = []
        for att in draft.get('raw_attachments', []):
            if isinstance(att, dict) and att.get('type') and att.get('payload'):
                attachments.append({
                    'type': att['type'],
                    'payload': att['payload']
                })
        
        # Отправляем в MAX API
        result = await self.max_client.send_message(
            chat_id=self.channel_id,
            text=draft['text'],
            reply_markup=draft.get('reply_markup'),
            attachments=attachments if attachments else None
        )
        
        if "error" not in result:
            message_id = result.get('message', {}).get('body', {}).get('mid')
            if message_id is not None:
                self.stats.record_message(
                    message_id, self.channel_id, 
                    draft['text'], datetime.now().isoformat()
                )
            
            self.state.clear_draft(user_id)
            self.state.clear_session(user_id)
            
            await send_callback(
                "✅ **Пост опубликован!** 🎉\n\n"
                "Новый пост: /post\n"
                "Статистика: /stats"
            )
        else:
            error_detail = result.get('detail', 'неизвестная ошибка')
            await send_callback(f"❌ Ошибка публикации:\n{error_detail[:200]}")
            logger.error(f"[CMD] Publish failed: {result}")
    
    async def handle_cancel(self, user_id: int, send_callback):
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback("🗑️ Черновик удалён. /post — новый пост")
    
    async def handle_stats(self, user_id: int, send_callback):
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пока пуста")
            return
        report = ["📊 **Последние посты:**\n"]
        for item in all_stats[-10:]:
            mid = item['message_id'][:12]
            report.append(f"• `{mid}...` | 👁 {item.get('views', 0)}")
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id: int, send_callback):
        await send_callback(
            "⚙️ **Настройки**\n\n"
            "`/set_channel <ID>` — сменить канал\n"
            "`/set_password <pwd>` — сменить пароль\n"
            "`/list_admins` — список админов"
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        await send_callback(f"✅ Канал: `{new_channel_id}` (нужен перезапуск)")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        self.auth.change_password(new_password)
        await send_callback("✅ Пароль изменён. Все должны переавторизоваться.")
    
    async def handle_list_admins(self, user_id: int, send_callback):
        admins = self.auth.list_authorized()
        if not admins:
            await send_callback("👥 Нет авторизованных")
            return
        report = ["👥 **Авторизованные:**"]
        for a in admins:
            report.append(f"• ID: `{a['user_id']}` | {a['auth_time'][:16]}")
        await send_callback('\n'.join(report))

# ===================================================================
# 🌐 WEBHOOK HANDLER
# ===================================================================
async def webhook_handler(request, handlers: CommandHandlers):
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    if request.method != 'POST':
        return web.Response(status=405)
    
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 {json.dumps(body, ensure_ascii=False)[:500]}")
        
        if body.get('update_type') == 'message_created' and (msg := body.get('message')):
            await handle_incoming_message(msg, handlers)
        
        return web.Response(status=200)
    except Exception as e:
        logger.exception(f"[WEBHOOK] Error: {e}")
        return web.Response(status=500)

async def handle_incoming_message(msg: Dict, handlers: CommandHandlers):
    logger.info("="*80)
    logger.info("[MSG] Processing incoming message")
    
    rec = msg.get('recipient', {})
    user_id = rec.get('user_id') or msg.get('sender', {}).get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        logger.error("[MSG] Cannot determine user_id")
        return
    
    logger.info(f"[MSG] 👤 user_id={user_id} | chat_id={chat_id}")
    
    # Сохраняем chat_id
    session = handlers.state.get_session(user_id)
    session['chat_id'] = chat_id
    
    # 🔥 send_callback с правильными параметрами
    async def send_callback(text: str, reply_markup: Optional[Dict] = None):
        logger.info(f"[SEND] 📤 To {chat_id or user_id}: '{text[:50]}...'")
        result = await handlers.max_client.send_message(
            chat_id=chat_id or user_id,
            text=text,
            reply_markup=reply_markup
        )
        logger.info(f"[SEND] ← {json.dumps(result, ensure_ascii=False)[:200]}")
        return result
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    logger.info(f"[MSG] 💬 '{text[:100]}...' | markup={len(markup)} | attachments={len(raw_attachments)}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 Step: {step}")
    
    cmd = text.strip()
    
    # 🔥 Маршрутизация команд
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send_callback)
    
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send_callback)
    
    elif cmd == '/edit':
        await handlers.handle_edit(user_id, send_callback)
    
    elif cmd == '/buttons':
        # Переход к редактированию кнопок
        handlers.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback("🔘 Отправьте кнопки (или `пропустить`):")
    
    elif cmd == '/publish':
        await handlers.handle_publish(user_id, send_callback)
    
    elif cmd.startswith('/schedule '):
        time_str = cmd.replace('/schedule ', '').strip()
        await handlers.handle_publish(user_id, send_callback, immediate=False, schedule_time=time_str)
    
    elif cmd == '/cancel':
        await handlers.handle_cancel(user_id, send_callback)
    
    elif cmd == '/stats':
        await handlers.handle_stats(user_id, send_callback)
    
    elif cmd == '/settings':
        await handlers.handle_settings(user_id, send_callback)
    
    elif cmd.startswith('/set_channel '):
        await handlers.handle_set_channel(user_id, cmd.split()[1], send_callback)
    
    elif cmd.startswith('/set_password '):
        await handlers.handle_set_password(user_id, cmd.split()[1], send_callback)
    
    elif cmd == '/list_admins':
        await handlers.handle_list_admins(user_id, send_callback)
    
    # Обработка по шагам
    elif step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send_callback)
    
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    
    elif step == 'post_ready':
        # Если прислали новый текст — редактируем
        await handlers.handle_edit_text(user_id, text, markup, raw_attachments, send_callback)
    
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback(
                "👋 **MAX Channel Poster**\n\n"
                "`/post` — создать пост\n"
                "`/preview` — предпросмотр\n"
                "`/edit` — редактировать\n"
                "`/publish` — опубликовать\n"
                "`/help` — помощь"
            )
        else:
            await send_callback("🔐 `/start` для авторизации")
    
    logger.info("="*80)

# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "version": "4.0-core-fix"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "4.0"})

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER v4.0 (CORE FIX)")
    logger.info("🚀" * 40)
    
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE)
    app['state'] = StateManager()
    app['max_client'] = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    app['media_mgr'] = MediaManager(MEDIA_CACHE_DIR, MAX_MEDIA_ITEMS)
    app['stats'] = StatsCollector(STATS_FILE)
    
    app['scheduler'] = PublishScheduler(app['max_client'], CHANNEL_ID)
    app['scheduler'].start()
    
    app['handlers'] = CommandHandlers(
        app['auth'], app['state'], app['max_client'],
        app['media_mgr'], app['scheduler'], app['stats'], CHANNEL_ID
    )
    
    if RENDER_EXTERNAL_URL:
        await app['max_client'].register_webhook(
            f"{RENDER_EXTERNAL_URL}/webhook", CHANNEL_ID
        )
    
    logger.info("✅ All components initialized")

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if 'scheduler' in app:
        app['scheduler'].stop()
    if 'max_client' in app:
        await app['max_client'].close()
    logger.info("🔚 Cleanup complete")

def create_app():
    app = web.Application()
    
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_post('/webhook', lambda req: webhook_handler(req, app['handlers']))
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Starting server on port {port}")
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
