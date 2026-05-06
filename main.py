"""
MAX Channel Poster Bot — STABLE v7.1
🔥 format=html (единственный рабочий вариант)
🔥 markup → HTML конвертация
🔥 Единый предпросмотр (одно сообщение)
🔥 /skip и /cancel на каждом шаге
🔥 Пошаговый алгоритм: фото → текст → кнопки → предпросмотр
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

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===================================================================
# 🔧 CONFIG
# ===================================================================
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
REQUIRE_PASSWORD = os.getenv('REQUIRE_PASSWORD', 'true').lower() == 'true'
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

logger.info("=" * 80)
logger.info(f"🚀 MAX CHANNEL POSTER v7.1 — STABLE")
logger.info(f"🔧 CHANNEL_ID={CHANNEL_ID}")
logger.info(f"🔧 REQUIRE_PASSWORD={REQUIRE_PASSWORD}")
logger.info(f"🔧 FORMAT=html (единственный рабочий)")
logger.info("=" * 80)

# ===================================================================
# 🎨 MARKUP → HTML КОНВЕРТЕР
# ===================================================================
def correct_markup_offsets(text: str, markup: List[Dict]) -> List[Dict]:
    """Корректирует UTF-16 offset → Python offset"""
    if not markup:
        return []
    
    corrected = []
    for entity in markup:
        entity = entity.copy()
        max_offset = entity.get('from', 0)
        max_length = entity.get('length', 0)
        
        # UTF-16 → Python offset
        python_offset = 0
        utf16_pos = 0
        for i, char in enumerate(text):
            if utf16_pos >= max_offset:
                python_offset = i
                break
            utf16_pos += len(char.encode('utf-16-le')) // 2
        else:
            python_offset = len(text)
        
        # UTF-16 → Python length
        python_length = 0
        utf16_pos = max_offset
        for i in range(python_offset, len(text)):
            if utf16_pos >= max_offset + max_length:
                break
            utf16_pos += len(text[i].encode('utf-16-le')) // 2
            python_length += 1
        
        entity['from'] = python_offset
        entity['length'] = python_length
        corrected.append(entity)
    
    return corrected


def markup_to_html(text: str, markup: List[Dict]) -> str:
    """
    Конвертирует MAX markup entities в HTML теги.
    🔥 Единственный рабочий формат для MAX API!
    """
    if not markup:
        return text
    
    logger.info(f"[MARKUP→HTML] Converting {len(markup)} entities")
    
    TAG_MAP = {
        "strong": "b", "bold": "b",
        "emphasized": "i", "italic": "i", "em": "i",
        "underline": "u", "u": "u",
        "strikethrough": "s", "strike": "s",
        "code": "code",
        "spoiler": "tg-spoiler",
        "link": "a", "text_link": "a",
    }
    
    corrected = correct_markup_offsets(text, markup)
    sorted_markup = sorted(corrected, key=lambda m: (m.get('from', 0), -m.get('length', 0)))
    
    # Фильтруем вложенные сущности одного типа
    filtered = []
    for i, entity in enumerate(sorted_markup):
        etype = entity.get('type', '')
        offset = entity.get('from', 0)
        end = offset + entity.get('length', 0)
        is_nested = False
        for j, other in enumerate(sorted_markup):
            if i == j or other.get('type') != etype:
                continue
            other_offset = other.get('from', 0)
            other_end = other_offset + other.get('length', 0)
            if other_offset <= offset and other_end >= end and (other_offset < offset or other_end > end):
                is_nested = True
                break
        if not is_nested:
            filtered.append(entity)
    
    # Строим карту тегов (открывающие и закрывающие по позициям)
    tag_starts = {}
    tag_ends = {}
    
    for entity in filtered:
        offset = entity.get('from', 0)
        length = entity.get('length', 0)
        etype = entity.get('type', '')
        
        if etype not in TAG_MAP:
            continue
        
        tag_name = TAG_MAP[etype]
        
        if etype in ('link', 'text_link'):
            url = entity.get('url', '').replace('"', '&quot;')
            open_tag = f'<{tag_name} href="{url}">' if url else f'<{tag_name}>'
        else:
            open_tag = f'<{tag_name}>'
        
        close_tag = f'</{tag_name}>'
        
        tag_starts.setdefault(offset, []).append(open_tag)
        tag_ends.setdefault(offset + length, []).append(close_tag)
        
        logger.debug(f"[MARKUP→HTML] {etype} → <{tag_name}> [{offset}:{offset+length}]")
    
    # Собираем HTML
    result = []
    for i, char in enumerate(text):
        # Закрываем теги
        if i in tag_ends:
            for tag in tag_ends[i]:
                result.append(tag)
        # Открываем теги
        if i in tag_starts:
            for tag in tag_starts[i]:
                result.append(tag)
        result.append(char)
    
    # Закрываем оставшиеся в конце
    last_pos = len(text)
    if last_pos in tag_ends:
        for tag in tag_ends[last_pos]:
            result.append(tag)
    
    final = ''.join(result)
    logger.info(f"[MARKUP→HTML] Input: '{text[:100]}...'")
    logger.info(f"[MARKUP→HTML] Output: '{final[:150]}...'")
    return final


# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    def __init__(self, password: str, auth_file: Path, require_password: bool = True):
        self.password = password
        self.auth_file = auth_file
        self.require_password = require_password
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 require_password={require_password}")
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
            except Exception:
                pass
    
    def _save_to_file(self):
        try:
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'users': {str(k): v for k, v in self.authorized.items()},
                    'failed': {str(k): v for k, v in self.failed_attempts.items()},
                }, f, indent=2)
        except Exception:
            pass
    
    def is_authorized(self, user_id: int) -> bool:
        if not self.require_password:
            return True
        return user_id in self.authorized
    
    def check_password(self, user_id: int, password: str) -> bool:
        if not self.require_password:
            return True
        if password == self.password:
            self.authorized[user_id] = {'auth_time': datetime.now().isoformat()}
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save_to_file()
        return False
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
    
    def change_password(self, new_password: str):
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()
        logger.info("[AUTH] 🔑 Password changed")

# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    STEPS = ['post_waiting_photo', 'post_waiting_text', 'post_waiting_buttons', 'post_ready']
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
    
    def get_session(self, user_id: int) -> Dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Optional[Dict] = None):
        session = self.get_session(user_id)
        old = session.get('step')
        session['step'] = step
        if data is not None:
            session['data'].update(data)
        logger.info(f"[STATE] 📍 {user_id}: {old} → {step}")
    
    def get_step(self, user_id: int) -> Optional[str]:
        return self.sessions.get(user_id, {}).get('step')
    
    def get_session_data(self, user_id: int) -> Dict:
        return self.sessions.get(user_id, {}).get('data', {})
    
    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"[STATE] 🧹 Session cleared {user_id}")
    
    def save_draft(self, user_id: int, draft: Dict):
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
        logger.info(f"[STATE] 💾 Draft saved {user_id} | photo={bool(draft.get('attachments'))} text={bool(draft.get('text'))} buttons={bool(draft.get('buttons'))}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]
            logger.info(f"[STATE] 🗑️ Draft cleared {user_id}")

# ===================================================================
# 📡 MAX API CLIENT
# ===================================================================
class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        logger.info(f"[MAX] 📡 Client initialized")
    
    async def init(self):
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
    
    async def close(self):
        if self.session is not None:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/7.1"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.info(f"[MAX] 📤 BODY: {json.dumps(data, ensure_ascii=False)[:600] if data else 'None'}")
        
        try:
            start = time.time()
            async with self.session.request(
                method=method, url=url, headers=headers,
                json=data, timeout=self.timeout
            ) as response:
                elapsed = time.time() - start
                text = await response.text()
                
                logger.info(f"[MAX] ◀️ #{self.request_count}: {response.status} in {elapsed:.2f}s")
                logger.info(f"[MAX] 📥 RESPONSE: {text[:600]}")
                
                if response.status == 200:
                    try:
                        result = json.loads(text) if text.strip() else {}
                        resp_body = result.get('message', {}).get('body', {})
                        logger.info(f"[MAX] 📥 markup={bool(resp_body.get('markup'))} text='{resp_body.get('text', '')[:80]}...'")
                        return result
                    except json.JSONDecodeError:
                        return {"raw": text}
                
                return {"error": f"HTTP_{response.status}", "detail": text}
                
        except Exception as e:
            logger.error(f"[MAX] 💥 {e}")
            return {"error": "exception", "detail": str(e)}
    
    # 🔥 ЕДИНЫЙ МЕТОД ОТПРАВКИ (format=html)
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          buttons: Optional[List[List[Dict]]] = None,
                          attachments: Optional[List[Dict]] = None,
                          use_html_format: bool = False) -> Dict:
        """
        Отправляет сообщение в MAX.
        🔥 use_html_format=True → добавляет "format": "html"
        """
        logger.info(f"[MAX-SEND] ========== SENDING ==========")
        logger.info(f"[MAX-SEND] chat_id={chat_id} text='{text[:80]}...' buttons={'YES' if buttons else 'NO'} attachments={len(attachments) if attachments else 0} html={use_html_format}")
        
        payload = {"text": text}
        
        if use_html_format:
            payload["format"] = "html"
        
        all_attachments = []
        if attachments:
            all_attachments.extend(attachments)
        if buttons and len(buttons) > 0:
            all_attachments.append({
                "type": "inline_keyboard",
                "payload": {"buttons": buttons}
            })
            logger.info(f"[MAX-SEND] 🔘 Keyboard: {len(buttons)} rows")
        
        if all_attachments:
            payload["attachments"] = all_attachments
        
        logger.info(f"[MAX-SEND] Keys: {list(payload.keys())}")
        
        endpoint = f"/messages?chat_id={chat_id}"
        result = await self._request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[MAX-SEND] ❌ FAILED")
        else:
            logger.info(f"[MAX-SEND] ✅ SUCCESS")
        
        return result
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        body = {"url": webhook_url, "chat_id": chat_id, "update_types": ["message_created"]}
        result = await self._request("POST", "/subscriptions", data=body)
        return "error" not in result

# ===================================================================
# 🖼 MEDIA MANAGER
# ===================================================================
class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Парсит вложения, сохраняя оригинальный payload"""
        logger.info(f"[MEDIA] Parsing {len(attachments)} attachments")
        result = []
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                result.append({
                    'type': att_type,
                    'payload': payload.copy(),
                    'url': payload.get('url', ''),
                    'filename': payload.get('filename', f'file_{i}'),
                    'index': i
                })
                logger.info(f"[MEDIA] [{i}] ✅ {att_type}")
        logger.info(f"[MEDIA] ✅ {len(result)}/{len(attachments)}")
        return result

# ===================================================================
# 📊 STATS
# ===================================================================
class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f).get('messages', {})
            except Exception:
                pass
    
    def _save(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump({'messages': self.stats}, f, indent=2)
        except Exception:
            pass
    
    def record_message(self, message_id: str, chat_id: str, text: str, published_at: str):
        self.stats[message_id] = {'chat_id': chat_id, 'text_preview': text[:100], 'published_at': published_at, 'views': 0}
        self._save()
    
    def get_stats(self, message_id=None):
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
    
    def start(self):
        self.scheduler.start()
    
    def stop(self):
        self.scheduler.shutdown()
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id, draft, publish_at):
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def job():
            await self.max_client.send_message(
                chat_id=self.channel_id,
                text=draft.get('text', ''),
                buttons=draft.get('buttons'),
                attachments=draft.get('attachments'),
                use_html_format=True
            )
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(job, trigger=trigger, id=job_id, replace_existing=True)
        return job_id

# ===================================================================
# 🎮 COMMAND HANDLERS
# ===================================================================
class CommandHandlers:
    def __init__(self, auth, state, max_client, media_mgr, scheduler, stats, channel_id):
        self.auth = auth
        self.state = state
        self.max_client = max_client
        self.media_mgr = media_mgr
        self.scheduler = scheduler
        self.stats = stats
        self.channel_id = channel_id
    
    def _help(self) -> str:
        return "📝 /post — создать пост\n👁 /preview — предпросмотр\n📊 /stats — статистика\n⚙️ /settings — настройки\n❌ /cancel — сброс"
    
    def parse_buttons(self, text: str) -> List[List[Dict]]:
        """Парсит URL-кнопки: Название | url"""
        rows = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            for sep in [' | ', ' - ', ' → ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://')):
                        rows.append([{"type": "link", "text": btn_text, "url": btn_url}])
                        logger.info(f"[BTN] ✅ '{btn_text}'")
                        break
        return rows
    
    # ========== СТАРТ ==========
    
    async def handle_start(self, user_id, chat_id, send):
        logger.info(f"[CMD] /start user={user_id}")
        if self.auth.require_password and not self.auth.is_authorized(user_id):
            await send("🔐 Введите пароль:")
            self.state.set_step(user_id, 'waiting_password')
            return
        self.state.clear_session(user_id)
        await send(f"👋 MAX Channel Poster\n\n{self._help()}")
    
    async def handle_password(self, user_id, password, send):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            session = self.state.get_session(user_id)
            await self.handle_start(user_id, session.get('chat_id', user_id), send)
        else:
            remaining = 3 - self.auth.get_failed_attempts(user_id)
            await send(f"❌ Неверный пароль. Осталось: {remaining}" if remaining > 0 else "🔒 Заблокировано.")
    
    # ========== ШАГ 1: ФОТО ==========
    
    async def handle_post_command(self, user_id, send):
        if not self.auth.is_authorized(user_id):
            await send("🔐 /start")
            return
        self.state.clear_session(user_id)
        self.state.set_step(user_id, 'post_waiting_photo')
        await send("📸 Шаг 1/3: Отправьте фото/видео\n⏭ /skip | ❌ /cancel")
    
    async def handle_post_photo(self, user_id, raw_attachments, send):
        logger.info(f"[PHOTO] {len(raw_attachments)} attachments")
        session = self.state.get_session_data(user_id)
        attachments = self.media_mgr.parse_attachments(raw_attachments)
        session['raw_attachments'] = raw_attachments
        session['attachments'] = attachments
        self.state.set_step(user_id, 'post_waiting_text')
        await send(f"✅ Фото ({len(attachments)} шт.)\n📝 Шаг 2/3: Напишите текст\n⏭ /skip | ❌ /cancel")
    
    # ========== ШАГ 2: ТЕКСТ ==========
    
    async def handle_post_text(self, user_id, text, markup, raw_attachments, send):
        logger.info(f"[TEXT] '{text[:80]}...' markup={len(markup) if markup else 0}")
        session = self.state.get_session_data(user_id)
        
        if raw_attachments:
            new = self.media_mgr.parse_attachments(raw_attachments)
            session['attachments'] = session.get('attachments', []) + new
            session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
        
        # 🔥 Конвертируем в HTML (format=html)
        if markup:
            session['text'] = markup_to_html(text, markup)
        else:
            session['text'] = text
        
        session['raw_text'] = text
        session['markup'] = markup
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send("✅ Текст сохранён\n🔘 Шаг 3/3: Добавьте URL-кнопки\nФормат: Название | https://ссылка\n⏭ /skip | ❌ /cancel")
    
    # ========== ШАГ 3: КНОПКИ ==========
    
    async def handle_post_buttons(self, user_id, buttons_text, send):
        logger.info(f"[BTN] '{buttons_text[:100]}...'")
        session = self.state.get_session_data(user_id)
        session['buttons'] = self.parse_buttons(buttons_text)
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        await self.send_preview(user_id, send, session)
    
    # ========== ПРЕДПРОСМОТР ==========
    
    async def send_preview(self, user_id, send, draft=None):
        """🔥 Единый предпросмотр: фото + текст + кнопки в ОДНОМ сообщении"""
        logger.info("[PREVIEW] ==========")
        
        if draft is None:
            draft = self.state.get_draft(user_id)
        if draft is None:
            await send("❌ Нет черновика")
            return
        
        text = draft.get('text', '')
        buttons = draft.get('buttons', [])
        attachments = draft.get('attachments', [])
        
        logger.info(f"[PREVIEW] text='{text[:50]}...' buttons={len(buttons)} attachments={len(attachments)}")
        
        chat_id = self.state.get_session(user_id).get('chat_id', user_id)
        
        # 🔥 Отправляем ОДНО сообщение
        await self.max_client.send_message(
            chat_id=chat_id,
            text=text or "Предпросмотр",
            buttons=buttons,
            attachments=[{'type': a['type'], 'payload': a['payload']} for a in attachments if a.get('payload')],
            use_html_format=bool(draft.get('markup'))
        )
        
        # Команды ОТДЕЛЬНО
        await send("📝 /edit | 🚀 /publish | ❌ /cancel")
        logger.info("[PREVIEW] ==========")
    
    async def handle_preview(self, user_id, send):
        await self.send_preview(user_id, send)
    
    # ========== РЕДАКТИРОВАНИЕ ==========
    
    async def handle_edit(self, user_id, send):
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send("❌ Нет черновика. /post")
            return
        
        menu = ["✏️ Что редактируем?\n"]
        if draft.get('attachments'):
            menu.append("🖼 /edit_photo — фото")
        if draft.get('text'):
            menu.append("📝 /edit_text — текст")
        if draft.get('buttons'):
            menu.append("🔘 /edit_buttons — кнопки")
        menu.append("\n👁 /preview | ❌ /cancel")
        
        await send('\n'.join(menu))
    
    async def handle_edit_photo(self, user_id, send):
        self.state.set_step(user_id, 'post_waiting_photo')
        await send("🖼 Новое фото или /skip /cancel")
    
    async def handle_edit_text(self, user_id, send):
        self.state.set_step(user_id, 'post_waiting_text')
        await send("📝 Новый текст или /skip /cancel")
    
    async def handle_edit_buttons(self, user_id, send):
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send("🔘 Новые кнопки или /skip /cancel")
    
    # ========== ПУБЛИКАЦИЯ ==========
    
    async def handle_publish(self, user_id, send, immediate=True, schedule_time=None):
        logger.info(f"[PUBLISH] ==========")
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send("❌ Нет черновика")
            return
        
        logger.info(f"[PUBLISH] text='{draft.get('text', '')[:50]}...' buttons={len(draft.get('buttons', []))} attachments={len(draft.get('attachments', []))}")
        
        if not immediate and schedule_time:
            job_id = self.scheduler.schedule_post(user_id, draft, schedule_time)
            if job_id:
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send(f"✅ Запланировано на {schedule_time}")
            else:
                await send("❌ Неверная дата (ГГГГ-ММ-ДД ЧЧ:ММ)")
            return
        
        await send("⏳ Публикую...")
        
        attachments = []
        for att in draft.get('raw_attachments', []):
            if isinstance(att, dict) and att.get('type'):
                attachments.append({'type': att['type'], 'payload': att.get('payload', {})})
        
        # 🔥 ОДНА публикация с format=html
        result = await self.max_client.send_message(
            chat_id=self.channel_id,
            text=draft.get('text', ''),
            buttons=draft.get('buttons'),
            attachments=attachments if attachments else None,
            use_html_format=True  # Всегда html для форматирования
        )
        
        if "error" not in result:
            message_id = result.get('message', {}).get('body', {}).get('mid')
            if message_id:
                self.stats.record_message(message_id, self.channel_id, draft.get('text', ''), datetime.now().isoformat())
            self.state.clear_draft(user_id)
            self.state.clear_session(user_id)
            await send(f"✅ Опубликовано!\n\n{self._help()}")
            logger.info(f"[PUBLISH] ✅ msg_id={message_id}")
        else:
            await send(f"❌ Ошибка: {result.get('detail', '')[:200]}")
            logger.error(f"[PUBLISH] ❌ {result.get('detail', '')[:200]}")
        logger.info("[PUBLISH] ==========")
    
    # ========== ОТМЕНА ==========
    
    async def handle_cancel(self, user_id, send):
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send(f"🗑️ Сброшено.\n\n{self._help()}")
    
    # ========== SKIP ==========
    
    async def handle_skip(self, user_id, send):
        step = self.state.get_step(user_id)
        logger.info(f"[SKIP] step={step}")
        
        if step == 'post_waiting_photo':
            self.state.set_step(user_id, 'post_waiting_text')
            await send("📝 Шаг 2/3: Напишите текст\n⏭ /skip | ❌ /cancel")
        elif step == 'post_waiting_text':
            self.state.set_step(user_id, 'post_waiting_buttons')
            await send("🔘 Шаг 3/3: Добавьте URL-кнопки\n⏭ /skip | ❌ /cancel")
        elif step == 'post_waiting_buttons':
            session = self.state.get_session_data(user_id)
            session['buttons'] = []
            self.state.save_draft(user_id, session.copy())
            self.state.set_step(user_id, 'post_ready')
            await self.send_preview(user_id, send, session)
    
    # ========== ПРОЧЕЕ ==========
    
    async def handle_stats(self, user_id, send):
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send("📊 Пусто")
            return
        report = ["📊 Последние посты:\n"]
        for item in all_stats[-10:]:
            report.append(f"• {item['message_id'][:12]}... | 👁 {item.get('views', 0)}")
        await send('\n'.join(report))
    
    async def handle_settings(self, user_id, send):
        await send("⚙️ /set_channel ID | /set_password pwd | /list_admins")
    
    async def handle_set_channel(self, user_id, new_id, send):
        await send(f"✅ Канал: {new_id} (перезапустите)")
    
    async def handle_set_password(self, user_id, new_pwd, send):
        self.auth.change_password(new_pwd)
        await send("✅ Пароль изменён")
    
    async def handle_list_admins(self, user_id, send):
        admins = self.auth.authorized
        if not admins:
            await send("👥 Пусто")
            return
        report = ["👥 Админы:"]
        for uid, data in admins.items():
            report.append(f"• {uid} | {data.get('auth_time', '')[:16]}")
        await send('\n'.join(report))

# ===================================================================
# 🌐 WEBHOOK
# ===================================================================
async def webhook_handler(request, handlers):
    if request.method != 'POST':
        return web.Response(status=405)
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 {json.dumps(body, ensure_ascii=False)[:600]}")
        if body.get('update_type') == 'message_created' and (msg := body.get('message')):
            await handle_incoming_message(msg, handlers)
        return web.Response(status=200)
    except Exception as e:
        logger.exception(f"[WEBHOOK] {e}")
        return web.Response(status=500)

async def handle_incoming_message(msg, handlers):
    logger.info("=" * 80)
    
    rec = msg.get('recipient', {})
    sender = msg.get('sender', {})
    user_id = rec.get('user_id') or sender.get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        return
    
    logger.info(f"[MSG] user={user_id} chat={chat_id}")
    
    handlers.state.get_session(user_id)['chat_id'] = chat_id
    
    async def send(text, buttons=None):
        logger.info(f"[SEND] '{text[:50]}...'")
        return await handlers.max_client.send_message(
            chat_id=chat_id or user_id,
            text=text,
            buttons=buttons
        )
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    logger.info(f"[MSG] text='{text[:80]}...' markup={len(markup)} attachments={len(raw_attachments)}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] step={step}")
    
    cmd = text.strip()
    
    # Роутинг
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send)
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send)
    elif cmd == '/skip':
        await handlers.handle_skip(user_id, send)
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send)
    elif cmd == '/edit':
        await handlers.handle_edit(user_id, send)
    elif cmd == '/edit_photo':
        await handlers.handle_edit_photo(user_id, send)
    elif cmd == '/edit_text':
        await handlers.handle_edit_text(user_id, send)
    elif cmd == '/edit_buttons':
        await handlers.handle_edit_buttons(user_id, send)
    elif cmd == '/publish':
        await handlers.handle_publish(user_id, send)
    elif cmd.startswith('/schedule '):
        await handlers.handle_publish(user_id, send, immediate=False, schedule_time=cmd.replace('/schedule ', ''))
    elif cmd == '/cancel':
        await handlers.handle_cancel(user_id, send)
    elif cmd == '/stats':
        await handlers.handle_stats(user_id, send)
    elif cmd == '/settings':
        await handlers.handle_settings(user_id, send)
    elif cmd.startswith('/set_channel '):
        await handlers.handle_set_channel(user_id, cmd.split()[1], send)
    elif cmd.startswith('/set_password '):
        await handlers.handle_set_password(user_id, cmd.split()[1], send)
    elif cmd == '/list_admins':
        await handlers.handle_list_admins(user_id, send)
    elif step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send)
    elif step == 'post_waiting_photo':
        if raw_attachments:
            await handlers.handle_post_photo(user_id, raw_attachments, send)
        else:
            await send("📸 Отправьте фото или /skip")
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send)
    elif step == 'post_ready':
        # Если прислали новое — редактируем текст
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send)
        await handlers.send_preview(user_id, send)
    else:
        if handlers.auth.is_authorized(user_id):
            await send(handlers._help())
        else:
            await send("🔐 /start")
    
    logger.info("=" * 80)

# ===================================================================
# 🌐 SERVER
# ===================================================================
async def health(request):
    return web.json_response({"ok": True, "version": "7.1"})

async def root(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "7.1"})

async def on_startup(app):
    logger.info("🚀 STARTING v7.1 — STABLE")
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE, REQUIRE_PASSWORD)
    app['state'] = StateManager()
    app['max_client'] = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    app['media_mgr'] = MediaManager(MEDIA_CACHE_DIR, MAX_MEDIA_ITEMS)
    app['stats'] = StatsCollector(STATS_FILE)
    app['scheduler'] = PublishScheduler(app['max_client'], CHANNEL_ID)
    app['scheduler'].start()
    app['handlers'] = CommandHandlers(app['auth'], app['state'], app['max_client'], app['media_mgr'], app['scheduler'], app['stats'], CHANNEL_ID)
    if RENDER_EXTERNAL_URL:
        await app['max_client'].register_webhook(f"{RENDER_EXTERNAL_URL}/webhook", CHANNEL_ID)
    logger.info("✅ Ready!")

async def on_cleanup(app):
    if 'scheduler' in app:
        app['scheduler'].stop()
    if 'max_client' in app:
        await app['max_client'].close()

def create_app():
    app = web.Application()
    app.router.add_get('/', root)
    app.router.add_get('/health', health)
    app.router.add_post('/webhook', lambda req: webhook_handler(req, app['handlers']))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    web.run_app(create_app(), host='0.0.0.0', port=port, access_log=None)
