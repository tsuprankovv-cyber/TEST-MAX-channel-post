"""
MAX Channel Poster Bot — CORE FIX v4.1
🔥 ИСПРАВЛЕНО: Кнопки, Медиа, Форматирование, Превью
🔥 МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ в проблемных зонах
🔥 Кнопки действий как inline-ссылки
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
logger.info("=" * 80)
logger.info(f"🔧 INIT: LOG_LEVEL={LOG_LEVEL}")
logger.info(f"🔧 INIT: CHANNEL_ID={CHANNEL_ID}")
logger.info(f"🔧 INIT: BASE_API_URL={BASE_API_URL}")
logger.info("=" * 80)

# ===================================================================
# 🎨 FORMATTING ENGINE (МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ)
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
    """
    Корректирует offset из UTF-16 (MAX) в Python-индексы.
    🔥 КРИТИЧНО для правильного форматирования!
    """
    logger.debug(f"[MARKUP-OFFSET] Correcting offset={max_offset}, length={max_length}")
    
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
        
        if python_offset != max_offset or python_length != max_length:
            logger.info(f"[MARKUP-OFFSET] 🔧 Corrected: MAX=[{max_offset}:{max_offset+max_length}] → Python=[{python_offset}:{python_offset+python_length}]")
        
        return python_offset, python_length
    
    return python_offset, max_length

def filter_overlapping_same_type(markup: List[Dict]) -> List[Dict]:
    """Убирает вложенные сущности одного типа"""
    if not markup:
        logger.debug("[MARKUP-FILTER] Empty markup, skipping")
        return []
    
    logger.info(f"[MARKUP-FILTER] 🔍 Filtering {len(markup)} entities")
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
                logger.warning(f"[MARKUP-FILTER] 🔄 Ignoring nested {etype}: [{offset}:{end}] inside [{other_offset}:{other_end}]")
                break
        
        if not is_nested:
            filtered.append(entity)
    
    logger.info(f"[MARKUP-FILTER] ✅ Kept {len(filtered)}/{len(markup)} entities")
    return filtered

def apply_markup(text: str, markup: List[Dict]) -> str:
    """
    Конвертирует MAX markup в HTML.
    🔥 КЛЮЧЕВАЯ ФУНКЦИЯ ФОРМАТИРОВАНИЯ!
    """
    if not markup or not text:
        logger.debug(f"[MARKUP-APPLY] No markup ({len(markup) if markup else 0}) or text ({len(text) if text else 0}), returning as-is")
        return text
    
    logger.info("[MARKUP-APPLY] ========== APPLYING MAX MARKUP ==========")
    logger.info(f"[MARKUP-APPLY] Input text length: {len(text)}")
    logger.info(f"[MARKUP-APPLY] Input text preview: '{text[:100]}...'")
    logger.info(f"[MARKUP-APPLY] Entities count: {len(markup)}")
    
    for idx, entity in enumerate(markup):
        logger.debug(f"[MARKUP-APPLY] Entity[{idx}]: type={entity.get('type')}, from={entity.get('from')}, length={entity.get('length')}")
    
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
        logger.debug(f"[MARKUP-APPLY] Corrected entity: type={entity.get('type')}, from={py_offset}, length={py_length}, text='{text[py_offset:py_offset+py_length]}'")
    
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
            logger.warning(f"[MARKUP-APPLY] ⚠️ Unknown type: {etype}, skipping")
            continue
        
        tag_name = MAX_TAG_MAP[etype]
        
        if etype in ('link', 'text_link', 'url'):
            url = entity.get('url', '').replace('"', '&quot;')
            if url:
                open_tag = f'<{tag_name} href="{url}">'
            else:
                open_tag = f'<{tag_name}>'
            logger.debug(f"[MARKUP-APPLY] Link entity: url={url[:50]}...")
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
        
        logger.info(f"[MARKUP-APPLY] 📍 {etype} → <{tag_name}> at [{offset}:{end_pos}]")
    
    # Собираем финальный HTML
    logger.debug("[MARKUP-APPLY] 🔨 Building HTML...")
    result = []
    
    for i, char in enumerate(text):
        # Закрываем теги на этой позиции
        if i in tag_ends:
            for close_tag in tag_ends[i]:
                result.append(close_tag)
                logger.debug(f"[MARKUP-APPLY] Closing tag at pos {i}: {close_tag}")
        
        # Открываем новые теги
        if i in tag_starts:
            for open_tag in tag_starts[i]:
                result.append(open_tag)
                logger.debug(f"[MARKUP-APPLY] Opening tag at pos {i}: {open_tag}")
        
        result.append(char)
    
    # Закрываем оставшиеся теги в конце
    last_pos = len(text)
    if last_pos in tag_ends:
        for close_tag in tag_ends[last_pos]:
            result.append(close_tag)
            logger.debug(f"[MARKUP-APPLY] Closing tag at end: {close_tag}")
    
    final_text = ''.join(result)
    
    logger.info(f"[MARKUP-APPLY] Output text length: {len(final_text)}")
    logger.info(f"[MARKUP-APPLY] Output preview: '{final_text[:200]}...'")
    logger.info("[MARKUP-APPLY] ========== END MARKUP ==========")
    
    return final_text

def parse_markdown_to_html(text: str) -> str:
    """
    Конвертирует Markdown-подобный синтаксис в HTML.
    🔥 Используется когда нет MAX markup!
    """
    if not text:
        return text
    
    logger.info("[MARKDOWN] ========== PARSING MARKDOWN ==========")
    logger.info(f"[MARKDOWN] Input: '{text[:150]}...'")
    
    original = text
    
    # Жирный: **текст**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    # Курсив: *текст* (но не **)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    
    # Подчёркнутый: ++текст++
    text = re.sub(r'\+\+(.+?)\+\+', r'<u>\1</u>', text)
    
    # Зачёркнутый: ~~текст~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # Моноширинный: `текст`
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    
    # Ссылки: [текст](url)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    
    if text != original:
        logger.info(f"[MARKDOWN] ✅ Converted: '{text[:150]}...'")
    else:
        logger.info(f"[MARKDOWN] ℹ️ No markdown found, returning as-is")
    
    logger.info("[MARKDOWN] ========== END MARKDOWN ==========")
    return text

def apply_formatting(text: str, markup: List[Dict] = None) -> str:
    """
    Применяет форматирование: сначала пробует MAX markup, потом Markdown.
    🔥 ЕДИНАЯ ТОЧКА ВХОДА ДЛЯ ФОРМАТИРОВАНИЯ!
    """
    logger.info(f"[FORMAT] 🎨 Applying formatting (text_len={len(text)}, has_markup={markup is not None and len(markup) > 0 if markup else False})")
    
    if markup and len(markup) > 0:
        logger.info("[FORMAT] Using MAX markup")
        result = apply_markup(text, markup)
    else:
        logger.info("[FORMAT] No MAX markup, trying Markdown")
        result = parse_markdown_to_html(text)
    
    logger.info(f"[FORMAT] Final text: '{result[:150]}...'")
    return result

def strip_html_tags(text: str) -> str:
    """Убирает HTML-теги для чистого текста"""
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
        logger.info(f"[AUTH] 🔐 Initialized (password_hash={hashlib.sha256(password.encode()).hexdigest()[:8]}...)")
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] 📥 Loaded {len(self.authorized)} authorized users")
            except Exception as e:
                logger.error(f"[AUTH] ❌ Load error: {e}")
        else:
            logger.info(f"[AUTH] 📄 Auth file not found: {self.auth_file}")
    
    def _save_to_file(self):
        try:
            data = {
                'users': {str(k): v for k, v in self.authorized.items()},
                'failed': {str(k): v for k, v in self.failed_attempts.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"[AUTH] 💾 Saved to {self.auth_file}")
        except Exception as e:
            logger.warning(f"[AUTH] ⚠️ Save error: {e}")
    
    def check_password(self, user_id: int, password: str) -> bool:
        logger.info(f"[AUTH] 🔍 Checking password for user_id={user_id}")
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat(),
                'password_hash': hashlib.sha256(self.password.encode()).hexdigest()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            logger.info(f"[AUTH] ✅ User {user_id} authorized")
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save_to_file()
        logger.warning(f"[AUTH] ❌ User {user_id} failed attempt #{self.failed_attempts[user_id]}")
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        authorized = user_id in self.authorized
        logger.debug(f"[AUTH] is_authorized({user_id}) = {authorized}")
        return authorized
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
            logger.info(f"[AUTH] 🔄 Reset failed attempts for {user_id}")
    
    def list_authorized(self) -> List[Dict]:
        return [{'user_id': uid, 'auth_time': data['auth_time']} for uid, data in self.authorized.items()]
    
    def change_password(self, new_password: str):
        logger.info(f"[AUTH] 🔑 Changing password")
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()
        logger.info(f"[AUTH] ✅ Password changed, all sessions cleared")

# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
        logger.info("[STATE] 🗄 Initialized")
    
    def get_session(self, user_id: int) -> Dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
            logger.debug(f"[STATE] 🆕 New session for user {user_id}")
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Optional[Dict] = None):
        session = self.get_session(user_id)
        old_step = session.get('step')
        session['step'] = step
        if data is not None:
            session['data'].update(data)
        logger.info(f"[STATE] 📍 User {user_id}: step {old_step} → {step} | data_keys={list(session['data'].keys())}")
    
    def get_step(self, user_id: int) -> Optional[str]:
        step = self.sessions.get(user_id, {}).get('step')
        logger.debug(f"[STATE] get_step({user_id}) = {step}")
        return step
    
    def get_session_data(self, user_id: int) -> Dict:
        data = self.sessions.get(user_id, {}).get('data', {})
        logger.debug(f"[STATE] get_session_data({user_id}) keys={list(data.keys())}")
        return data
    
    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"[STATE] 🧹 Cleared session for {user_id}")
    
    def save_draft(self, user_id: int, draft: Dict):
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
        logger.info(f"[STATE] 💾 Draft saved for {user_id} | keys={list(draft.keys())} | text_len={len(draft.get('text', ''))}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        draft = self.drafts.get(user_id)
        logger.debug(f"[STATE] get_draft({user_id}) = {'found' if draft else 'None'}")
        return draft
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]
            logger.info(f"[STATE] 🗑️ Draft cleared for {user_id}")

# ===================================================================
# 📡 MAX API CLIENT (МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ)
# ===================================================================
class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        logger.info(f"[MAX] 📡 Client initialized | base_url={base_url} | timeout={timeout}s")
    
    async def init(self):
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
            logger.info("[MAX] 🔗 HTTP session created")
    
    async def close(self):
        if self.session is not None:
            await self.session.close()
            logger.info("[MAX] 🔌 HTTP session closed")
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                       max_retries: int = 3) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/4.1"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ REQUEST #{self.request_count}: {method} {url}")
        logger.info(f"[MAX] 📤 BODY: {json.dumps(data, ensure_ascii=False)[:500] if data else 'None'}")
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                async with self.session.request(
                    method=method, url=url, headers=headers,
                    json=data, timeout=self.timeout
                ) as response:
                    elapsed = time.time() - start_time
                    text = await response.text()
                    
                    logger.info(f"[MAX] ◀️ RESPONSE #{self.request_count}: {response.status} in {elapsed:.2f}s")
                    logger.info(f"[MAX] 📥 BODY: {text[:500]}")
                    
                    if response.status == 200:
                        try:
                            result = json.loads(text) if text.strip() else {}
                            logger.info(f"[MAX] ✅ SUCCESS #{self.request_count}")
                            return result
                        except json.JSONDecodeError:
                            logger.warning(f"[MAX] ⚠️ Response is not JSON: {text[:200]}")
                            return {"raw": text}
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 30))
                        logger.warning(f"[MAX] ⏳ Rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    logger.error(f"[MAX] ❌ ERROR #{self.request_count}: HTTP {response.status} - {text[:300]}")
                    return {"error": f"HTTP_{response.status}", "detail": text}
                    
            except asyncio.TimeoutError:
                logger.warning(f"[MAX] ⏱ Timeout (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "timeout"}
            except Exception as e:
                logger.error(f"[MAX] 💥 Exception: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "exception", "detail": str(e)}
        
        return {"error": "max_retries_exceeded"}
    
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          reply_markup: Optional[Dict] = None,
                          attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Отправляет сообщение в MAX.
        🔥 reply_markup — для кнопок!
        🔥 attachments — с оригинальным payload!
        """
        logger.info(f"[MAX-SEND] ========== SENDING MESSAGE ==========")
        logger.info(f"[MAX-SEND] chat_id: {chat_id}")
        logger.info(f"[MAX-SEND] text_len: {len(text)}")
        logger.info(f"[MAX-SEND] text_preview: '{text[:100]}...'")
        logger.info(f"[MAX-SEND] has_reply_markup: {reply_markup is not None}")
        logger.info(f"[MAX-SEND] has_attachments: {attachments is not None}")
        
        payload = {"text": text}
        
        if reply_markup is not None:
            has_keyboard = bool(reply_markup.get('inline_keyboard'))
            logger.info(f"[MAX-SEND] 🔘 reply_markup present, has inline_keyboard: {has_keyboard}")
            if has_keyboard:
                rows = len(reply_markup['inline_keyboard'])
                total_buttons = sum(len(row) for row in reply_markup['inline_keyboard'])
                logger.info(f"[MAX-SEND] 🔘 Keyboard: {rows} rows, {total_buttons} buttons")
                for i, row in enumerate(reply_markup['inline_keyboard']):
                    for j, btn in enumerate(row):
                        logger.info(f"[MAX-SEND] 🔘 Button[{i}][{j}]: text='{btn.get('text')}', url='{btn.get('url', '')[:50]}...'")
            payload["reply_markup"] = reply_markup
        
        if attachments is not None and len(attachments) > 0:
            logger.info(f"[MAX-SEND] 📎 Attachments: {len(attachments)} items")
            for i, att in enumerate(attachments):
                logger.info(f"[MAX-SEND] 📎 Attachment[{i}]: type={att.get('type')}, has_payload={bool(att.get('payload'))}")
            payload["attachments"] = attachments
        
        logger.info(f"[MAX-SEND] 📤 Final payload keys: {list(payload.keys())}")
        
        endpoint = f"/messages?chat_id={chat_id}"
        result = await self._request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[MAX-SEND] ❌ Send failed: {result.get('detail', 'unknown')[:300]}")
        else:
            msg_id = result.get('message', {}).get('body', {}).get('mid', 'unknown')
            logger.info(f"[MAX-SEND] ✅ Sent successfully! msg_id={msg_id}")
        
        logger.info(f"[MAX-SEND] ========== END SEND ==========")
        return result
    
    async def edit_message(self, message_id: str, text: Optional[str] = None,
                          reply_markup: Optional[Dict] = None) -> Dict:
        logger.info(f"[MAX-EDIT] ✏️ Editing message {message_id}")
        payload = {}
        if text is not None:
            payload["text"] = text
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        endpoint = f"/messages/{message_id}"
        return await self._request("PUT", endpoint, data=payload)
    
    async def get_message_stats(self, message_id: str) -> Dict:
        logger.info(f"[MAX-STATS] 📊 Getting stats for {message_id}")
        endpoint = f"/messages/{message_id}/stats"
        return await self._request("GET", endpoint)
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        logger.info(f"[MAX-WEBHOOK] 🔗 Registering webhook: {webhook_url}")
        body = {
            "url": webhook_url,
            "chat_id": chat_id,
            "update_types": ["message_created"]
        }
        result = await self._request("POST", "/subscriptions", data=body)
        success = "error" not in result
        logger.info(f"[MAX-WEBHOOK] {'✅' if success else '❌'} Registration: {result}")
        return success

# ===================================================================
# 🖼 MEDIA MANAGER (МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ)
# ===================================================================
class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        logger.info(f"[MEDIA] 🖼 Initialized | cache_dir={cache_dir} | max_items={max_items}")
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """
        Парсит вложения из сообщения MAX.
        🔥 Сохраняет оригинальный payload для обратной отправки!
        """
        logger.info(f"[MEDIA-PARSE] ========== PARSING ATTACHMENTS ==========")
        logger.info(f"[MEDIA-PARSE] Input count: {len(attachments)}")
        
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                logger.warning(f"[MEDIA-PARSE] ⚠️ Attachment #{i} is not a dict, skipping")
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            logger.info(f"[MEDIA-PARSE] Attachment #{i}: type='{att_type}', payload_keys={list(payload.keys())}")
            logger.debug(f"[MEDIA-PARSE] Full payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
            
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                parsed = {
                    'type': att_type,
                    'payload': payload.copy(),  # Копия!
                    'url': payload.get('url') or att.get('url', ''),
                    'filename': payload.get('filename') or att.get('title', f'file_{i}'),
                    'index': i
                }
                result.append(parsed)
                logger.info(f"[MEDIA-PARSE] ✅ Parsed #{i}: type={att_type}, filename='{parsed['filename']}', url={'present' if parsed['url'] else 'MISSING'}")
            else:
                logger.warning(f"[MEDIA-PARSE] ⚠️ Unknown type '{att_type}', skipping")
        
        logger.info(f"[MEDIA-PARSE] ✅ Successfully parsed {len(result)}/{len(attachments)}")
        logger.info(f"[MEDIA-PARSE] ========== END PARSE ==========")
        return result

# ===================================================================
# 📊 STATS MODULE
# ===================================================================
class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        self._load_from_file()
        logger.info(f"[STATS] 📊 Initialized | file={stats_file}")
    
    def _load_from_file(self):
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.stats = data.get('messages', {})
                logger.info(f"[STATS] 📥 Loaded {len(self.stats)} messages")
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
        logger.info(f"[STATS] 📝 Recorded message {message_id}")
    
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
        logger.info(f"[SCHEDULER] ⏰ Initialized | timezone={SCHEDULER_TIMEZONE}")
    
    def start(self):
        self.scheduler.start()
        logger.info("[SCHEDULER] 🚀 Started")
    
    def stop(self):
        self.scheduler.shutdown()
        logger.info("[SCHEDULER] 🛑 Stopped")
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        logger.debug(f"[SCHEDULER] Parsing datetime: '{dt_str}'")
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
        for fmt in formats:
            try:
                result = datetime.strptime(dt_str.strip(), fmt)
                logger.info(f"[SCHEDULER] ✅ Parsed as {fmt}: {result}")
                return result
            except ValueError:
                continue
        logger.error(f"[SCHEDULER] ❌ Failed to parse: '{dt_str}'")
        return None
    
    def schedule_post(self, user_id: int, post_data: Dict, publish_at: str) -> Optional[str]:
        logger.info(f"[SCHEDULER] 📅 Scheduling post for {publish_at}")
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            logger.warning(f"[SCHEDULER] ⚠️ Invalid time or in the past: {publish_at}")
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def publish_job():
            logger.info(f"[SCHEDULER] 🎯 Executing scheduled job {job_id}")
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
        logger.info(f"[SCHEDULER] ✅ Scheduled job {job_id} for {publish_time}")
        return job_id

# ===================================================================
# 🎮 COMMAND HANDLERS (ИСПРАВЛЕНО + МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ)
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
        logger.info(f"[HANDLERS] 🎮 Initialized | channel_id={channel_id}")
    
    async def handle_start(self, user_id: int, chat_id: int, send_callback):
        logger.info(f"[CMD-START] 🚀 /start user_id={user_id}, chat_id={chat_id}")
        
        if not self.auth.is_authorized(user_id):
            logger.info(f"[CMD-START] User {user_id} not authorized, asking password")
            await send_callback("🔐 Введите пароль для доступа:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        menu_keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "url": "max://new_post"}],
                [{"text": "📊 Статистика", "url": "max://stats"}],
                [{"text": "⚙️ Настройки", "url": "max://settings"}]
            ]
        }
        
        logger.info(f"[CMD-START] Sending main menu with {len(menu_keyboard['inline_keyboard'])} keyboard rows")
        
        await send_callback(
            "<b>MAX Channel Poster</b>\n\n"
            "/post — создать пост\n"
            "/preview — предпросмотр\n"
            "/publish — опубликовать\n"
            "/cancel — отменить",
            reply_markup=menu_keyboard
        )
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        logger.info(f"[CMD-PASS] 🔐 Password attempt from user_id={user_id}")
        
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            session = self.state.get_session(user_id)
            chat_id = session.get('chat_id', user_id)
            logger.info(f"[CMD-PASS] ✅ Password correct for {user_id}")
            await self.handle_start(user_id, chat_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            logger.warning(f"[CMD-PASS] ❌ Wrong password for {user_id}, attempts={attempts}, remaining={remaining}")
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много попыток. Попробуйте позже.")
    
    async def handle_post_command(self, user_id: int, send_callback):
        logger.info(f"[CMD-POST] 📝 /post from user_id={user_id}")
        
        if not self.auth.is_authorized(user_id):
            logger.warning(f"[CMD-POST] User {user_id} not authorized")
            await send_callback("🔐 Сначала /start")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        await send_callback(
            "📝 <b>Создание поста</b>\n\n"
            "1. Отправьте текст (можно с форматированием)\n"
            "2. Прикрепите фото/видео/файлы\n"
            "3. Добавьте кнопки в формате:\n"
            "   <code>Название | https://ссылка</code>\n\n"
            "После текста перейдём к кнопкам 👇"
        )
    
    async def handle_post_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        logger.info(f"[CMD-TEXT] ========== RECEIVED POST TEXT ==========")
        logger.info(f"[CMD-TEXT] user_id={user_id}")
        logger.info(f"[CMD-TEXT] text_len={len(text)}")
        logger.info(f"[CMD-TEXT] text_preview: '{text[:150]}...'")
        logger.info(f"[CMD-TEXT] markup_count={len(markup)}")
        logger.info(f"[CMD-TEXT] raw_attachments_count={len(raw_attachments)}")
        
        if markup:
            for idx, m in enumerate(markup):
                logger.info(f"[CMD-TEXT] markup[{idx}]: type={m.get('type')}, from={m.get('from')}, length={m.get('length')}")
        
        session = self.state.get_session_data(user_id)
        
        # 🔥 Применяем форматирование
        formatted_text = apply_formatting(text, markup)
        logger.info(f"[CMD-TEXT] Formatted text: '{formatted_text[:150]}...'")
        
        session['text'] = formatted_text
        session['raw_text'] = text
        session['markup'] = markup
        
        # Парсим вложения
        attachments = self.media_mgr.parse_attachments(raw_attachments)
        session['raw_attachments'] = raw_attachments
        session['attachments'] = attachments
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        logger.info(f"[CMD-TEXT] ✅ Text saved, waiting for buttons")
        
        await send_callback(
            "🔘 <b>Добавьте кнопки</b>\n\n"
            "Формат (каждая с новой строки):\n"
            "<code>Название | https://ссылка</code>\n\n"
            "Пример:\n"
            "Купить | https://shop.ru\n"
            "Подробнее | https://info.ru\n\n"
            "Напишите <code>пропустить</code> если не нужны"
        )
    
    def parse_buttons(self, text: str) -> List[List[Dict]]:
        """Парсит кнопки из текста"""
        logger.info(f"[BTN-PARSE] 🔘 Parsing buttons from text (len={len(text)})")
        logger.info(f"[BTN-PARSE] Input: '{text[:200]}...'")
        
        rows = []
        lines = text.strip().split('\n')
        
        for line_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            logger.debug(f"[BTN-PARSE] Line [{line_idx}]: '{line}'")
            
            btn = None
            for sep in [' | ', ' - ', ' → ', ' -> ', ' — ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max://')):
                        btn = {'text': btn_text, 'url': btn_url}
                        logger.debug(f"[BTN-PARSE] Found button with separator '{sep}': '{btn_text}' → {btn_url[:50]}...")
                        break
            
            if btn is not None:
                rows.append([btn])
                logger.info(f"[BTN-PARSE] ✅ Button parsed: text='{btn['text']}', url='{btn['url'][:50]}...'")
            else:
                logger.debug(f"[BTN-PARSE] ⏭ Line '{line[:50]}...' is not a button, skipping")
        
        logger.info(f"[BTN-PARSE] ✅ Total: {len(rows)} button rows, {sum(len(r) for r in rows)} buttons")
        return rows
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        logger.info(f"[CMD-BTN] ========== RECEIVED BUTTONS ==========")
        logger.info(f"[CMD-BTN] user_id={user_id}")
        logger.info(f"[CMD-BTN] buttons_text: '{buttons_text[:150]}...'")
        
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            button_rows = []
            logger.info(f"[CMD-BTN] User skipped buttons")
        else:
            button_rows = self.parse_buttons(buttons_text)
        
        reply_markup = None
        if button_rows:
            reply_markup = {"inline_keyboard": button_rows}
            logger.info(f"[CMD-BTN] Created reply_markup with {len(button_rows)} rows")
        else:
            logger.info(f"[CMD-BTN] No buttons, reply_markup is None")
        
        session['reply_markup'] = reply_markup
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        logger.info(f"[CMD-BTN] ✅ Draft saved, sending preview")
        
        # 🔥 Отправляем предпросмотр
        await self.send_preview(user_id, send_callback, session)
    
    # 🔥 ПОЛНОСТЬЮ ПЕРЕПИСАННЫЙ ПРЕДПРОСМОТР
    async def send_preview(self, user_id: int, send_callback, draft: Optional[Dict] = None):
        """
        Отправляет предпросмотр:
        - Медиа как вложения (не ссылки!)
        - Кнопки через reply_markup (интерактивные!)
        - Команды как inline-кнопки
        """
        logger.info(f"[PREVIEW] ========== SENDING PREVIEW ==========")
        
        if draft is None:
            draft = self.state.get_draft(user_id)
            logger.info(f"[PREVIEW] Loaded draft from state")
        
        if draft is None or 'text' not in draft:
            logger.error(f"[PREVIEW] ❌ No draft found for user {user_id}")
            await send_callback("❌ Нет черновика для предпросмотра")
            return
        
        text = draft['text']
        reply_markup = draft.get('reply_markup')
        attachments = draft.get('attachments', [])
        
        logger.info(f"[PREVIEW] text_len={len(text)}")
        logger.info(f"[PREVIEW] text_preview='{text[:100]}...'")
        logger.info(f"[PREVIEW] has_reply_markup={reply_markup is not None}")
        logger.info(f"[PREVIEW] attachments_count={len(attachments)}")
        
        chat_id = self.state.get_session(user_id).get('chat_id', user_id)
        
        # 🔥 1. Отправляем медиа
        media_sent = False
        
        for idx, att in enumerate(attachments):
            att_type = att.get('type', '')
            url = att.get('url', '')
            
            logger.info(f"[PREVIEW] Processing attachment [{idx}]: type={att_type}, has_url={bool(url)}")
            
            if att_type in ('image', 'photo') and url:
                logger.info(f"[PREVIEW] 📸 Sending photo as attachment")
                
                media_payload = {
                    "type": att_type,
                    "payload": att.get('payload', {})
                }
                
                caption = text if not media_sent else ""
                
                logger.info(f"[PREVIEW] Caption for first media: '{caption[:100]}...'")
                
                result = await self.max_client.send_message(
                    chat_id=chat_id,
                    text=caption if caption else "🖼",
                    attachments=[media_payload]
                )
                media_sent = True
                logger.info(f"[PREVIEW] Photo sent: {'OK' if 'error' not in result else 'FAILED'}")
                await asyncio.sleep(0.3)
            
            elif att_type == 'video' and url:
                logger.info(f"[PREVIEW] 🎬 Sending video as attachment")
                
                media_payload = {
                    "type": "video",
                    "payload": att.get('payload', {})
                }
                
                result = await self.max_client.send_message(
                    chat_id=chat_id,
                    text=text if not media_sent else "🎬",
                    attachments=[media_payload]
                )
                media_sent = True
                logger.info(f"[PREVIEW] Video sent: {'OK' if 'error' not in result else 'FAILED'}")
                await asyncio.sleep(0.3)
        
        # 🔥 2. Если медиа не было — отправляем текст
        if not media_sent:
            logger.info(f"[PREVIEW] No media sent, sending text only")
            await send_callback(text, reply_markup=reply_markup)
        
        # 🔥 3. Отправляем кнопки поста (если есть)
        if reply_markup and reply_markup.get('inline_keyboard'):
            logger.info(f"[PREVIEW] 🔘 Sending post buttons")
            await send_callback(
                "<b>🔘 Кнопки поста:</b>",
                reply_markup=reply_markup
            )
        
        # 🔥 4. Кнопки действий
        action_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Опубликовать", "url": "max://publish"},
                    {"text": "✏️ Редактировать", "url": "max://edit"}
                ],
                [
                    {"text": "📅 Отложить", "url": "max://schedule"},
                    {"text": "❌ Отмена", "url": "max://cancel"}
                ]
            ]
        }
        
        logger.info(f"[PREVIEW] 🎮 Sending action buttons")
        await send_callback(
            "<b>Действия:</b>",
            reply_markup=action_keyboard
        )
        
        # 🔥 5. Текстовые команды
        await send_callback(
            "<i>Или команды:</i>\n"
            "/publish — опубликовать\n"
            "/edit — редактировать\n"
            "/schedule ГГГГ-ММ-ДД ЧЧ:ММ — отложить\n"
            "/cancel — отменить"
        )
        
        logger.info(f"[PREVIEW] ========== END PREVIEW ==========")
    
    async def handle_preview(self, user_id: int, send_callback):
        logger.info(f"[CMD-PREVIEW] 👁 /preview from user_id={user_id}")
        await self.send_preview(user_id, send_callback)
    
    async def handle_edit(self, user_id: int, send_callback):
        logger.info(f"[CMD-EDIT] ✏️ /edit from user_id={user_id}")
        draft = self.state.get_draft(user_id)
        if draft is None:
            logger.warning(f"[CMD-EDIT] No draft for user {user_id}")
            await send_callback("❌ Нет черновика. /post — новый пост")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        edit_keyboard = {
            "inline_keyboard": [
                [{"text": "📝 Текст", "url": "max://edit_text"}],
                [{"text": "🖼 Медиа", "url": "max://edit_media"}],
                [{"text": "🔘 Кнопки", "url": "max://edit_buttons"}]
            ]
        }
        
        await send_callback(
            "✏️ <b>Редактирование</b>\n\n"
            "Отправьте новый текст или фото\n"
            "/buttons — редактировать кнопки\n"
            "/preview — предпросмотр",
            reply_markup=edit_keyboard
        )
    
    async def handle_edit_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        logger.info(f"[CMD-EDIT-TEXT] 📝 Editing text for user_id={user_id}")
        
        session = self.state.get_session_data(user_id)
        
        # Форматируем
        formatted_text = apply_formatting(text, markup)
        session['text'] = formatted_text
        session['raw_text'] = text
        session['markup'] = markup
        
        # Добавляем новые вложения если есть
        if raw_attachments:
            new_attachments = self.media_mgr.parse_attachments(raw_attachments)
            existing = session.get('attachments', [])
            session['attachments'] = existing + new_attachments
            session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
            logger.info(f"[CMD-EDIT-TEXT] Added {len(new_attachments)} new attachments, total={len(session['attachments'])}")
        
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        await send_callback("✅ Текст обновлён!")
        await self.send_preview(user_id, send_callback, session)
    
    # 🔥 ИСПРАВЛЕННАЯ ПУБЛИКАЦИЯ
    async def handle_publish(self, user_id: int, send_callback, 
                            immediate: bool = True, schedule_time: Optional[str] = None):
        logger.info(f"[CMD-PUBLISH] ========== PUBLISHING ==========")
        logger.info(f"[CMD-PUBLISH] user_id={user_id}, immediate={immediate}, schedule_time={schedule_time}")
        
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            logger.error(f"[CMD-PUBLISH] ❌ No draft found")
            await send_callback("❌ Черновик не найден. /post — новый пост")
            return
        
        logger.info(f"[CMD-PUBLISH] Draft: text_len={len(draft['text'])}, has_reply_markup={draft.get('reply_markup') is not None}")
        logger.info(f"[CMD-PUBLISH] Draft text: '{draft['text'][:150]}...'")
        
        if draft.get('reply_markup'):
            rows = len(draft['reply_markup'].get('inline_keyboard', []))
            logger.info(f"[CMD-PUBLISH] reply_markup has {rows} button rows")
        
        if not immediate and schedule_time:
            logger.info(f"[CMD-PUBLISH] 📅 Scheduling for {schedule_time}")
            job_id = self.scheduler.schedule_post(user_id, draft, schedule_time)
            if job_id:
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send_callback(f"✅ Запланировано на {schedule_time}")
            else:
                await send_callback("❌ Неверный формат даты (ГГГГ-ММ-ДД ЧЧ:ММ)")
            return
        
        await send_callback("⏳ Публикую...")
        
        # 🔥 Формируем attachments с ОРИГИНАЛЬНЫМИ payload
        attachments = []
        for att in draft.get('raw_attachments', []):
            if isinstance(att, dict) and att.get('type'):
                attachment = {
                    'type': att['type'],
                    'payload': att.get('payload', {})
                }
                attachments.append(attachment)
                logger.info(f"[CMD-PUBLISH] 📎 Attachment: type={att['type']}, payload_keys={list(att.get('payload', {}).keys())}")
        
        logger.info(f"[CMD-PUBLISH] Total attachments to publish: {len(attachments)}")
        
        # 🔥 Отправляем в канал
        logger.info(f"[CMD-PUBLISH] 🚀 Sending to channel {self.channel_id}")
        result = await self.max_client.send_message(
            chat_id=self.channel_id,
            text=draft['text'],
            reply_markup=draft.get('reply_markup'),
            attachments=attachments if attachments else None
        )
        
        if "error" not in result:
            message_id = result.get('message', {}).get('body', {}).get('mid')
            logger.info(f"[CMD-PUBLISH] ✅ Published! message_id={message_id}")
            
            if message_id is not None:
                self.stats.record_message(
                    message_id, self.channel_id, 
                    draft['text'], datetime.now().isoformat()
                )
            
            self.state.clear_draft(user_id)
            self.state.clear_session(user_id)
            
            await send_callback(
                "<b>✅ Пост опубликован!</b> 🎉\n\n"
                "/post — новый пост\n"
                "/stats — статистика"
            )
        else:
            error_detail = result.get('detail', 'неизвестная ошибка')
            logger.error(f"[CMD-PUBLISH] ❌ Failed: {error_detail[:300]}")
            await send_callback(f"<b>❌ Ошибка публикации:</b>\n{error_detail[:200]}")
        
        logger.info(f"[CMD-PUBLISH] ========== END PUBLISH ==========")
    
    async def handle_cancel(self, user_id: int, send_callback):
        logger.info(f"[CMD-CANCEL] ❌ /cancel from user_id={user_id}")
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback("🗑️ Черновик удалён. /post — новый пост")
    
    async def handle_stats(self, user_id: int, send_callback):
        logger.info(f"[CMD-STATS] 📊 /stats from user_id={user_id}")
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пока пуста")
            return
        report = ["📊 <b>Последние посты:</b>\n"]
        for item in all_stats[-10:]:
            mid = item['message_id'][:12]
            report.append(f"• <code>{mid}...</code> | 👁 {item.get('views', 0)}")
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id: int, send_callback):
        await send_callback(
            "⚙️ <b>Настройки</b>\n\n"
            "/set_channel ID — сменить канал\n"
            "/set_password pwd — сменить пароль\n"
            "/list_admins — список админов"
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        logger.info(f"[CMD-SET-CH] 📡 Setting channel to {new_channel_id}")
        await send_callback(f"✅ Канал: <code>{new_channel_id}</code> (нужен перезапуск)")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        logger.info(f"[CMD-SET-PASS] 🔑 Changing password")
        self.auth.change_password(new_password)
        await send_callback("✅ Пароль изменён. Все должны переавторизоваться.")
    
    async def handle_list_admins(self, user_id: int, send_callback):
        admins = self.auth.list_authorized()
        if not admins:
            await send_callback("👥 Нет авторизованных")
            return
        report = ["👥 <b>Авторизованные:</b>"]
        for a in admins:
            report.append(f"• ID: <code>{a['user_id']}</code> | {a['auth_time'][:16]}")
        await send_callback('\n'.join(report))

# ===================================================================
# 🌐 WEBHOOK HANDLER (МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ)
# ===================================================================
async def webhook_handler(request, handlers: CommandHandlers):
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    
    if request.method != 'POST':
        logger.warning(f"[WEBHOOK] Invalid method: {request.method}")
        return web.Response(status=405)
    
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 BODY: {json.dumps(body, ensure_ascii=False)[:800]}")
        
        update_type = body.get('update_type', 'unknown')
        logger.info(f"[WEBHOOK] Update type: {update_type}")
        
        if update_type == 'message_created' and (msg := body.get('message')):
            logger.info("[WEBHOOK] ✅ Message created, processing...")
            await handle_incoming_message(msg, handlers)
        else:
            logger.info(f"[WEBHOOK] ⏭ Skipping (not message_created or no message)")
        
        return web.Response(status=200)
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] ❌ Invalid JSON: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.exception(f"[WEBHOOK] 💥 Exception: {e}")
        return web.Response(status=500)

async def handle_incoming_message(msg: Dict, handlers: CommandHandlers):
    logger.info("=" * 80)
    logger.info("[MSG] 📨 Processing incoming message")
    logger.info(f"[MSG] Raw keys: {list(msg.keys())}")
    
    rec = msg.get('recipient', {})
    sender = msg.get('sender', {})
    
    user_id = rec.get('user_id') or sender.get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        logger.error("[MSG] ❌ Cannot determine user_id!")
        logger.error(f"[MSG] recipient={rec}, sender={sender}")
        return
    
    logger.info(f"[MSG] 👤 user_id={user_id}")
    logger.info(f"[MSG] 💬 chat_id={chat_id}")
    logger.info(f"[MSG] 👤 sender: {sender.get('first_name', '')} {sender.get('last_name', '')} (@{sender.get('username', 'N/A')})")
    
    # Сохраняем chat_id
    session = handlers.state.get_session(user_id)
    session['chat_id'] = chat_id
    
    # 🔥 send_callback
    async def send_callback(text: str, reply_markup: Optional[Dict] = None):
        logger.info(f"[SEND] 📤 To {chat_id or user_id}")
        logger.info(f"[SEND] Text: '{text[:100]}...'")
        logger.info(f"[SEND] Has reply_markup: {reply_markup is not None}")
        
        result = await handlers.max_client.send_message(
            chat_id=chat_id or user_id,
            text=text,
            reply_markup=reply_markup
        )
        
        logger.info(f"[SEND] Result: {'OK' if 'error' not in result else 'FAILED'}")
        return result
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    logger.info(f"[MSG] 💬 Text: '{text[:150]}...' (len={len(text)})")
    logger.info(f"[MSG] 🎨 Markup: {len(markup)} entities")
    logger.info(f"[MSG] 📎 Attachments: {len(raw_attachments)} items")
    
    if markup:
        for idx, m in enumerate(markup):
            logger.info(f"[MSG] Markup[{idx}]: type={m.get('type')}, from={m.get('from')}, length={m.get('length')}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 Current step: {step}")
    
    cmd = text.strip()
    logger.info(f"[MSG] 🔍 Command: '{cmd[:50]}...'")
    
    # 🔥 Маршрутизация
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send_callback)
    
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send_callback)
    
    elif cmd == '/edit':
        await handlers.handle_edit(user_id, send_callback)
    
    elif cmd == '/buttons':
        handlers.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback("🔘 Отправьте кнопки (или <code>пропустить</code>):")
    
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
        logger.info(f"[MSG] 🔐 Processing password step")
        await handlers.handle_password(user_id, text.strip(), send_callback)
    
    elif step == 'post_waiting_text':
        logger.info(f"[MSG] 📝 Processing text step")
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send_callback)
    
    elif step == 'post_waiting_buttons':
        logger.info(f"[MSG] 🔘 Processing buttons step")
        await handlers.handle_post_buttons(user_id, text, send_callback)
    
    elif step == 'post_ready':
        logger.info(f"[MSG] ✏️ Editing existing post")
        await handlers.handle_edit_text(user_id, text, markup, raw_attachments, send_callback)
    
    else:
        logger.info(f"[MSG] ❓ Unknown step or no step, sending help")
        if handlers.auth.is_authorized(user_id):
            await send_callback(
                "<b>MAX Channel Poster</b>\n\n"
                "/post — создать пост\n"
                "/preview — предпросмотр\n"
                "/edit — редактировать\n"
                "/publish — опубликовать"
            )
        else:
            await send_callback("🔐 /start для авторизации")
    
    logger.info("=" * 80)

# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "version": "4.1-core-fix"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "4.1"})

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER v4.1")
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
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await app['max_client'].register_webhook(webhook_url, CHANNEL_ID)
    
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
    
    async def wh(request):
        return await webhook_handler(request, app['handlers'])
    app.router.add_post('/webhook', wh)
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Starting server on port {port}")
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
