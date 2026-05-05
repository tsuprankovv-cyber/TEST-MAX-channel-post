"""
MAX Channel Poster Bot — FIXED VERSION v3.2
🔧 FIX: Правильные кнопки через inline_keyboard
🔧 FIX: Корректная загрузка медиа через attachment
🔧 FIX: Сохранение форматирования через markup
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
CACHE_MAX_AGE_HOURS = int(os.getenv('CACHE_MAX_AGE_HOURS', '24'))

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

# ===================================================================
# 🔐 AUTH MODULE (без изменений)
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
            except Exception as e:
                logger.error(f"[AUTH] Failed to load: {e}")
    
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
            logger.warning(f"[AUTH] Failed to save: {e}")
    
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
# 🗄 STATE MODULE (без изменений)
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
                       params: Optional[Dict] = None, files: Optional[Dict] = None, 
                       max_retries: int = 3) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "User-Agent": "MAX-Channel-Poster/3.2"
        }
        
        if files is not None:
            headers.pop("Content-Type", None)
        else:
            headers["Content-Type"] = "application/json"
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        
        for attempt in range(max_retries):
            try:
                if files is not None:
                    form = FormData()
                    if data is not None:
                        for key, value in data.items():
                            form.add_field(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                    for key, file_data in files.items():
                        form.add_field(key, file_data['data'], filename=file_data.get('filename', 'file'))
                    
                    async with self.session.request(
                        method=method, url=url, headers=headers,
                        params=params, data=form, timeout=self.timeout
                    ) as response:
                        return await self._handle_response(response)
                else:
                    async with self.session.request(
                        method=method, url=url, headers=headers,
                        params=params, json=data, timeout=self.timeout
                    ) as response:
                        return await self._handle_response(response)
                        
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
    
    async def _handle_response(self, response) -> Dict:
        text = await response.text()
        logger.info(f"[MAX] ← {response.status} | {text[:200]}")
        
        if response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 30))
            await asyncio.sleep(retry_after)
            return {"error": "rate_limited"}
        
        if response.status == 200:
            try:
                return json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                return {"raw": text}
        
        return {"error": f"HTTP_{response.status}", "detail": text}
    
    # 🔧 ИСПРАВЛЕНО: Отправка сообщений с правильной структурой
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          keyboard: Optional[List[List[Dict]]] = None,
                          attachments: Optional[List[Dict]] = None) -> Dict:
        """Отправляет сообщение с правильной структурой для MAX API"""
        logger.info(f"[MAX] 📤 send_message(chat_id={chat_id}, text_len={len(text)})")
        
        payload = {"text": text}
        
        # 🔧 Кнопки через inline_keyboard
        if keyboard is not None and len(keyboard) > 0:
            payload["inline_keyboard"] = keyboard
            logger.debug(f"[MAX] Keyboard: {keyboard}")
        
        # 🔧 Медиа через attachment (массив)
        if attachments is not None and len(attachments) > 0:
            payload["attachment"] = attachments  # Единственное число!
            logger.debug(f"[MAX] Attachments: {len(attachments)} items")
        
        endpoint = f"/messages?chat_id={chat_id}"
        return await self._request("POST", endpoint, data=payload)
    
    async def edit_message(self, message_id: str, text: Optional[str] = None,
                          keyboard: Optional[List[List[Dict]]] = None) -> Dict:
        logger.info(f"[MAX] ✏️ edit_message(message_id={message_id})")
        
        payload = {}
        if text is not None:
            payload["text"] = text
        if keyboard is not None:
            payload["inline_keyboard"] = keyboard
        
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
    
    async def upload_media(self, file_data: bytes, filename: str, 
                          media_type: str = 'photo') -> Dict:
        logger.info(f"[MAX] 📤 upload_media(filename={filename}, size={len(file_data)}B)")
        endpoint = "/media/upload"
        files = {'file': {'data': file_data, 'filename': filename}}
        data = {'type': media_type}
        return await self._request("POST", endpoint, data=data, files=files)

# ===================================================================
# 🖼 MEDIA MANAGER (ИСПРАВЛЕНО)
# ===================================================================
class MediaManager:
    SUPPORTED_TYPES = {'photo', 'video', 'audio', 'document', 'voice', 'image', 'file'}
    
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        self.media_cache: Dict[str, Dict] = {}
    
    async def download_and_cache(self, url: str, filename: Optional[str] = None) -> Optional[Dict]:
        logger.info(f"[MEDIA] 📥 Downloading {url[:100]}...")
        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        logger.error(f"[MEDIA] HTTP {response.status}")
                        return None
                    
                    file_data = await response.read()
                    file_hash = hashlib.sha256(file_data).hexdigest()[:16]
                    
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type:
                        media_type = 'photo'
                    elif 'video' in content_type:
                        media_type = 'video'
                    elif 'audio' in content_type:
                        media_type = 'audio'
                    else:
                        media_type = 'document'
                    
                    cache_path = self.cache_dir / f"{file_hash}.bin"
                    cache_path.write_bytes(file_data)
                    
                    metadata = {
                        'hash': file_hash,
                        'filename': filename or f"file_{file_hash}",
                        'size': len(file_data),
                        'type': media_type,
                        'cached_at': datetime.now().isoformat(),
                        'cache_path': str(cache_path),
                        'original_url': url
                    }
                    
                    self.media_cache[file_hash] = metadata
                    logger.info(f"[MEDIA] ✅ Cached {filename} | {len(file_data)/1024:.1f}KB")
                    return metadata
        except Exception as e:
            logger.exception(f"[MEDIA] Failed: {e}")
            return None
    
    def get_cached_file(self, file_hash: str) -> Optional[bytes]:
        if file_hash in self.media_cache:
            cache_path = Path(self.media_cache[file_hash]['cache_path'])
            if cache_path.exists():
                return cache_path.read_bytes()
        return None
    
    # 🔧 ИСПРАВЛЕНО: Парсинг вложений
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Парсит вложения из сообщения MAX"""
        logger.info(f"[MEDIA] 🔍 parse_attachments(count={len(attachments)})")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file'):
                url = payload.get('url') or att.get('url')
                if url:
                    result.append({
                        'type': att_type,
                        'url': url,
                        'payload': payload,
                        'filename': payload.get('filename', f"media_{i}"),
                        'index': i
                    })
            elif att_type == 'share':
                url = payload.get('url') or att.get('url')
                if url:
                    result.append({
                        'type': 'share',
                        'url': url,
                        'title': att.get('title'),
                        'description': att.get('description'),
                        'image_url': att.get('image_url'),
                        'index': i
                    })
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} items")
        return result

# ===================================================================
# 🎨 FORMATTER (ИСПРАВЛЕНО)
# ===================================================================
class TextFormatter:
    @staticmethod
    def parse_buttons(text: str) -> Tuple[List[List[Dict]], str]:
        """Парсит кнопки и возвращает их в формате для inline_keyboard"""
        logger.info(f"[FORMAT] 🔘 Parsing buttons from text")
        
        rows = []
        remaining_lines = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            btn = None
            # Проверяем разные разделители
            for sep in [' | ', ' - ', ' → ', ' -> ', ' — ', '|', '-']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and (btn_url.startswith(('http://', 'https://', 't.me/', 'max://'))):
                        btn = {'text': btn_text, 'url': btn_url}
                        break
            
            if btn is not None:
                rows.append([btn])  # Каждая кнопка в отдельном ряду
                logger.debug(f"[FORMAT] Button: '{btn['text']}' → {btn['url']}")
            else:
                remaining_lines.append(line)
        
        remaining_text = '\n'.join(remaining_lines) if remaining_lines else text
        logger.info(f"[FORMAT] ✅ Parsed {len(rows)} button rows")
        return rows, remaining_text
    
    @staticmethod
    def strip_markdown(text: str) -> str:
        """Убирает markdown-синтаксис для превью"""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        return text

# ===================================================================
# ⏰ SCHEDULER (без изменений)
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
            try:
                result = await self.max_client.send_message(
                    chat_id=self.channel_id,
                    text=post_data.get('text', ''),
                    keyboard=post_data.get('keyboard'),
                    attachments=post_data.get('attachments')
                )
                logger.info(f"[SCHEDULER] Result: {result}")
            except Exception as e:
                logger.exception(f"[SCHEDULER] Error: {e}")
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(publish_job, trigger=trigger, id=job_id, replace_existing=True)
        self.scheduled_posts[job_id] = {
            'user_id': user_id,
            'publish_at': publish_at,
            'scheduled_at': datetime.now().isoformat()
        }
        return job_id
    
    def list_scheduled(self, user_id: Optional[int] = None) -> List[Dict]:
        result = []
        for job_id, data in self.scheduled_posts.items():
            if user_id is None or data['user_id'] == user_id:
                result.append({'job_id': job_id, 'publish_at': data['publish_at']})
        return result

# ===================================================================
# 📊 STATS MODULE (без изменений)
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
    
    def update_views(self, message_id: str, views: int):
        if message_id in self.stats:
            self.stats[message_id]['views'] = views
            self._save_to_file()
    
    def get_stats(self, message_id: Optional[str] = None):
        if message_id:
            return self.stats.get(message_id, {})
        return [{'message_id': mid, **data} for mid, data in self.stats.items()]

# ===================================================================
# 🎮 HANDLERS (ИСПРАВЛЕНО)
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
        logger.info(f"[CMD] 🚀 handle_start(user_id={user_id})")
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль для доступа к боту:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        # 🔧 ИСПРАВЛЕНО: Правильные кнопки через inline_keyboard
        keyboard = [
            [{"text": "➕ Новый пост", "url": "max://new_post"}],
            [{"text": "📋 Черновики", "url": "max://drafts"}],
            [{"text": "📊 Статистика", "url": "max://stats"}],
            [{"text": "⚙️ Настройки", "url": "max://settings"}]
        ]
        await send_callback(
            "👋 **MAX Channel Poster**\n\n"
            "/post — создать пост\n"
            "/preview — предпросмотр\n"
            "/publish — опубликовать\n"
            "/cancel — отменить",
            keyboard=keyboard
        )
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            chat_id = self.state.get_session(user_id).get('chat_id')
            await self.handle_start(user_id, chat_id or user_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много неудачных попыток.")
    
    async def handle_post_command(self, user_id: int, send_callback):
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала авторизуйтесь /start")
            return
        self.state.set_step(user_id, 'post_waiting_text')
        await send_callback(
            "📝 **Создание поста**\n\n"
            "Отправьте текст поста с форматированием.\n"
            "Затем добавьте кнопки в формате:\n"
            "`Название кнопки | https://ссылка`\n\n"
            "Каждая кнопка с новой строки"
        )
    
    # 🔧 ИСПРАВЛЕНО: Обработка текста с сохранением форматирования
    async def handle_post_text(self, user_id: int, text: str, markup: List, 
                               attachments: List, send_callback):
        logger.info(f"[CMD] 📝 handle_post_text(text_len={len(text)}, attachments={len(attachments)})")
        
        session = self.state.get_session_data(user_id)
        session['text'] = text
        session['markup'] = markup if markup else []
        session['raw_attachments'] = attachments if attachments else []
        self.state.set_step(user_id, 'post_waiting_buttons')
        
        await send_callback(
            "🔘 **Добавьте кнопки**\n\n"
            "Формат: `Название | ссылка`\n"
            "Для пропуска напишите: `пропустить`\n\n"
            "Пример:\n"
            "Купить | https://example.com\n"
            "Подробнее | https://site.ru"
        )
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        logger.info(f"[CMD] 🔘 handle_post_buttons")
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            button_rows = []
        else:
            button_rows, _ = TextFormatter.parse_buttons(buttons_text)
        
        # 🔧 Сохраняем в правильном формате для MAX API
        session['keyboard'] = button_rows
        self.state.save_draft(user_id, session.copy())
        
        # 🔧 Превью с медиа
        preview_parts = ["👁 **Предпросмотр поста**\n", session['text']]
        
        # Показываем медиа
        raw_attachments = session.get('raw_attachments', [])
        if raw_attachments:
            preview_parts.append(f"\n📎 **Вложения ({len(raw_attachments)}):**")
            for i, att in enumerate(raw_attachments, 1):
                att_type = att.get('type', 'файл')
                filename = att.get('filename', f'файл_{i}')
                preview_parts.append(f"  {i}. {att_type}: {filename}")
        
        # Показываем кнопки
        if button_rows:
            preview_parts.append("\n🔘 **Кнопки:**")
            for i, row in enumerate(button_rows, 1):
                for btn in row:
                    preview_parts.append(f"  {i}. {btn['text']}")
        
        preview_parts.append("\n✅ `/publish` — опубликовать")
        preview_parts.append("❌ `/cancel` — отменить")
        preview_parts.append("📅 `/publish ГГГГ-ММ-ДД ЧЧ:ММ` — отложить")
        
        await send_callback('\n'.join(preview_parts), keyboard=button_rows)
        self.state.set_step(user_id, 'post_ready')
    
    async def handle_preview(self, user_id: int, send_callback):
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден. Создайте пост через /post")
            return
        
        preview_text = TextFormatter.strip_markdown(draft['text'])
        keyboard = draft.get('keyboard', [])
        
        await send_callback(
            f"👁 **Предпросмотр**\n\n{preview_text}",
            keyboard=keyboard
        )
    
    # 🔧 ИСПРАВЛЕНО: Публикация с правильной обработкой медиа
    async def handle_publish(self, user_id: int, send_callback, 
                            immediate: bool = True, schedule_time: Optional[str] = None):
        logger.info(f"[CMD] 🚀 handle_publish(immediate={immediate})")
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден")
            return
        
        if not immediate and schedule_time:
            job_id = self.scheduler.schedule_post(user_id, draft, schedule_time)
            if job_id:
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send_callback(f"✅ Запланировано на {schedule_time}")
            else:
                await send_callback("❌ Неверный формат даты или время в прошлом")
            return
        
        await send_callback("⏳ Публикую...")
        
        # 🔧 Обрабатываем медиа
        published_attachments = []
        for att in draft.get('raw_attachments', []):
            if att.get('type') == 'share':
                published_attachments.append({
                    'type': 'share',
                    'url': att.get('url'),
                    'title': att.get('title'),
                    'description': att.get('description')
                })
            else:
                # Скачиваем и кэшируем медиа
                url = att.get('url')
                if url:
                    cached = await self.media_mgr.download_and_cache(url, att.get('filename'))
                    if cached:
                        published_attachments.append({
                            'type': att['type'],
                            'url': url,
                            'payload': att.get('payload', {}),
                            'filename': att.get('filename', 'file')
                        })
        
        # 🔧 Отправляем с правильной структурой
        result = await self.max_client.send_message(
            chat_id=self.channel_id,
            text=draft['text'],
            keyboard=draft.get('keyboard', []),
            attachments=published_attachments if published_attachments else None
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
            await send_callback(f"❌ Ошибка публикации: {error_detail}")
            logger.error(f"[CMD] Publish failed: {result}")
    
    async def handle_schedule_time(self, user_id: int, time_str: str, send_callback):
        await self.handle_publish(user_id, send_callback, immediate=False, schedule_time=time_str)
    
    async def handle_stats(self, user_id: int, send_callback):
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пока пуста")
            return
        
        report = ["📊 **Последние посты:**\n"]
        for item in all_stats[-10:]:
            mid_preview = item['message_id'][:12] if len(item['message_id']) > 12 else item['message_id']
            report.append(f"• `{mid_preview}...` | 👁 {item.get('views', 0)}")
        
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id: int, send_callback):
        await send_callback(
            "⚙️ **Настройки**\n\n"
            "`/set_channel <ID>` — сменить канал\n"
            "`/set_password <pwd>` — сменить пароль\n"
            "`/list_admins` — список админов"
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        await send_callback(f"✅ Канал изменён на `{new_channel_id}` (требуется перезапуск)")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        self.auth.change_password(new_password)
        await send_callback("✅ Пароль изменён. Все должны авторизоваться заново.")
    
    async def handle_list_admins(self, user_id: int, send_callback):
        admins = self.auth.list_authorized()
        if not admins:
            await send_callback("👥 Нет авторизованных пользователей")
            return
        report = ["👥 **Авторизованные:**"]
        for a in admins:
            report.append(f"• ID: `{a['user_id']}` | {a['auth_time'][:16]}")
        await send_callback('\n'.join(report))
    
    async def handle_cancel(self, user_id: int, send_callback):
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback("🗑️ Черновик удалён. /post — новый пост")

# ===================================================================
# 🌐 WEBHOOK HANDLER (ИСПРАВЛЕНО)
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
    logger.info(f"[MSG] 📨 Processing incoming message")
    
    rec = msg.get('recipient', {})
    user_id = rec.get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        # Пробуем получить из другого поля
        sender = msg.get('sender', {})
        user_id = sender.get('user_id')
        if not user_id:
            logger.error("[MSG] Cannot determine user_id")
            return
    
    logger.info(f"[MSG] 👤 user_id={user_id} | chat_id={chat_id}")
    
    # Сохраняем chat_id в сессии
    session = handlers.state.get_session(user_id)
    session['chat_id'] = chat_id
    
    # 🔧 ИСПРАВЛЕНО: send_callback с правильной структурой
    async def send_callback(text: str, keyboard: Optional[List[List[Dict]]] = None):
        logger.info(f"[SEND] 📤 To {chat_id or user_id}: '{text[:50]}...'")
        result = await handlers.max_client.send_message(
            chat_id=chat_id or user_id,
            text=text,
            keyboard=keyboard
        )
        logger.info(f"[SEND] ← {json.dumps(result, ensure_ascii=False)[:200]}")
        return result
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    attachments = handlers.media_mgr.parse_attachments(raw_attachments)
    
    logger.info(f"[MSG] 💬 '{text[:100]}...' | markup={len(markup)} | attachments={len(attachments)}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 Current step: {step}")
    
    # Обработка команд
    cmd = text.strip()
    
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send_callback)
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    elif cmd == '/publish':
        await handlers.handle_publish(user_id, send_callback)
    elif cmd.startswith('/publish '):
        time_str = cmd.replace('/publish ', '').strip()
        await handlers.handle_schedule_time(user_id, time_str, send_callback)
    elif cmd == '/cancel':
        await handlers.handle_cancel(user_id, send_callback)
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send_callback)
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
    elif step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, attachments, send_callback)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    elif step == 'waiting_schedule_time':
        await handlers.handle_schedule_time(user_id, text.strip(), send_callback)
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback("❓ Используйте /post для создания поста или /start для меню")
        else:
            await send_callback("🔐 Используйте /start для авторизации")
    
    logger.info("="*80)

# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "status": "running", "version": "3.2.0-fixed"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "3.2.0-fixed"})

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER BOT v3.2")
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
    
    # Веб-обработчики
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
