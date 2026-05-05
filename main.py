"""
MAX Channel Poster Bot — FINAL CLEAN VERSION
✅ Все синтаксические ошибки исправлены
✅ Максимальное логирование сохранено
✅ Работает на Render
"""
import asyncio
import logging
import os
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout, FormData, ClientError
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
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG').upper()
MAX_MEDIA_ITEMS = int(os.getenv('MAX_MEDIA_ITEMS', '10'))
SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '60'))

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
logger.info(f"🔧 LOG_LEVEL={LOG_LEVEL}, LOG_FILE={log_file}")

# ===================================================================
# 🔐 AUTH
# ===================================================================
class AuthManager:
    def __init__(self, password: str, auth_file: Path):
        self.password = password
        self.auth_file = auth_file
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 Initialized | hash={hashlib.sha256(password.encode()).hexdigest()[:8]}")
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] 📥 Loaded {len(self.authorized)} users")
            except Exception as e:
                logger.error(f"[AUTH] ❌ Load error: {e}")
    
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
            logger.warning(f"[AUTH] ⚠️ Save error: {e}")
    
    def check_password(self, user_id: int, password: str) -> bool:
        logger.info(f"[AUTH] 🔍 check_password(user_id={user_id})")
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
        logger.warning(f"[AUTH] ❌ User {user_id} failed attempt #{self.failed_attempts[user_id]}")
        self._save_to_file()
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        if user_id in self.authorized:
            if self.authorized[user_id].get('password_hash') == hashlib.sha256(self.password.encode()).hexdigest():
                return True
            del self.authorized[user_id]
        return False
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()


# ===================================================================
# 🗄 STATE
# ===================================================================
class StateManager:
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
        logger.info("[STATE] 🗄 Initialized")
    
    def get_session(self, user_id: int) -> Dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Dict = None):
        session = self.get_session(user_id)
        session['step'] = step
        if data:
            session['data'].update(data)
        logger.info(f"[STATE] 📍 User {user_id} → step={step}")
    
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
        logger.info(f"[STATE] 💾 Draft saved for user {user_id}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]


# ===================================================================
# 📡 MAX API
# ===================================================================
class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 60):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        logger.info(f"[MAX] 📡 Initialized | base_url={base_url}")
    
    async def init(self):
        if not self.session:
            self.session = ClientSession(timeout=self.timeout)
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, data: Dict = None, 
                       params: Dict = None, files: Dict = None, 
                       max_retries: int = 3) -> Dict:
        await self.init()
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Poster/1.0"
        }
        if files:
            headers.pop("Content-Type", None)
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url[:100]}")
        
        if data:
            logger.debug(f"[MAX] Body: {json.dumps(data, ensure_ascii=False)[:300]}")
        
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                if files:
                    form = FormData()
                    if data:
                        for key, value in data.items():
                            form.add_field(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                    for key, file_data in files.items():
                        form.add_field(key, file_data['data'], filename=file_data.get('filename', 'file'))
                    async with self.session.request(method=method, url=url, headers=headers, params=params, data=form, timeout=self.timeout) as response:
                        return await self._handle_response(response, start_time, attempt)
                else:
                    async with self.session.request(method=method, url=url, headers=headers, params=params, json=data, timeout=self.timeout) as response:
                        return await self._handle_response(response, start_time, attempt)
            except asyncio.TimeoutError as e:
                logger.warning(f"[MAX] ⏱ Timeout (attempt {attempt+1})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "timeout"}
            except ClientError as e:
                logger.error(f"[MAX] 🌐 ClientError: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "client_error"}
            except Exception as e:
                logger.exception(f"[MAX] 💥 Error: {e}")
                return {"error": "exception"}
        return {"error": "max_retries"}
    
    async def _handle_response(self, response, start_time: float, attempt: int) -> Dict:
        elapsed = time.time() - start_time
        text = await response.text()
        logger.info(f"[MAX] ← {response.status} in {elapsed:.2f}s | {text[:200]}")
        if response.status == 429:
            wait = int(response.headers.get('Retry-After', 30))
            await asyncio.sleep(wait)
            return {"error": "rate_limited"}
        if response.status == 401:
            return {"error": "auth_failed", "detail": text}
        if response.status == 200:
            try:
                return json.loads(text) if text.strip() else {}
            except:
                return {"raw": text}
        return {"error": f"HTTP_{response.status}", "detail": text, "status": response.status}
    
    async def send_message(self, chat_id: Union[str, int], text: str, buttons: List[Dict] = None, markup: List[Dict] = None) -> Dict:
        logger.info(f"[MAX] 📤 send_message(chat_id={chat_id}, text_len={len(text)})")
        payload = {"text": text}
        if buttons:
            payload["buttons"] = buttons
        if markup:
            payload["markup"] = markup
        endpoint = f"/messages?chat_id={chat_id}"
        return await self._request("POST", endpoint, data=payload)
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        logger.info(f"[MAX] 🔗 register_webhook(url={webhook_url})")
        body = {"url": webhook_url, "chat_id": chat_id, "update_types": ["message_created"]}
        result = await self._request("POST", "/subscriptions", data=body)
        return "error" not in result


# ===================================================================
# 🎨 FORMATTER
# ===================================================================
class TextFormatter:
    @staticmethod
    def parse_buttons(text: str) -> List[Dict]:
        buttons = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for i, line in enumerate(lines):
            if '|' in line:
                parts = line.split('|', 1)
                btn_text = parts[0].strip()
                btn_url = parts[1].strip()
                if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max.ru/')):
                    buttons.append({'text': btn_text, 'url': btn_url, 'index': i})
        return buttons
    
    @staticmethod
    def pass_through_markup(markup: List[Dict]) -> List[Dict]:
        return markup if markup else []


# ===================================================================
# 🎮 HANDLERS
# ===================================================================
class CommandHandlers:
    def __init__(self, auth, state, max_client, scheduler, stats, channel_id: str):
        self.auth = auth
        self.state = state
        self.max_client = max_client
        self.scheduler = scheduler
        self.stats = stats
        self.channel_id = channel_id
    
    async def handle_start(self, user_id: int, send_callback):
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль:")
            self.state.set_step(user_id, 'waiting_password')
            return
        kb = {"inline_keyboard": [[{"text": "➕ Новый пост", "callback_data": "new_post"}], [{"text": "📊 Статистика", "callback_data": "stats"}]]}
        await send_callback("👋 **MAX Channel Poster**\n\n/post — создать пост", kb)
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            await self.handle_start(user_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много попыток.")
    
    async def handle_post_command(self, user_id: int, send_callback):
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала /start")
            return
        self.state.set_step(user_id, 'post_waiting_text')
        await send_callback("📝 Отправь текст поста. Кнопки потом: `Текст | ссылка` (каждая с новой строки)")
    
    async def handle_post_text(self, user_id: int, text: str, markup: List, send_callback):
        session = self.state.get_session_data(user_id)
        session['text'] = text
        session['markup'] = TextFormatter.pass_through_markup(markup)
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback("🔘 Кнопки: `Текст | ссылка` или `пропустить`")
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        session = self.state.get_session_data(user_id)
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            session['buttons'] = []
        else:
            session['buttons'] = TextFormatter.parse_buttons(buttons_text)
        self.state.save_draft(user_id, session.copy())
        kb = {"inline_keyboard": [[{"text": "👁 Предпросмотр", "callback_data": "preview"}], [{"text": "✅ Опубликовать", "callback_data": "publish_now"}]]}
        await send_callback(f"📋 Черновик готов.\n\n📝 {session['text'][:100]}...\n🔘 Кнопок: {len(session['buttons'])}", kb)
    
    async def handle_preview(self, user_id: int, send_callback):
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден")
            return
        kb = {"inline_keyboard": [[{"text": btn['text'], "url": btn['url']} for btn in draft['buttons']]]} if draft.get('buttons') else None
        await send_callback(f"👁 **Предпросмотр**\n\n{draft['text']}", kb, markup=draft.get('markup'))
        kb_menu = {"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": "publish_now"}]]}
        await send_callback("Выберите действие:", kb_menu)
    
    async def handle_publish(self, user_id: int, send_callback, immediate: bool = True):
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден")
            return
        if immediate:
            await send_callback("⏳ Публикую...")
            result = await self.max_client.send_message(chat_id=self.channel_id, text=draft['text'], buttons=draft.get('buttons'), markup=draft.get('markup'))
            if "error" not in result:
                self.state.clear_draft(user_id)
                await send_callback("✅ **Опубликовано!** 🎉")
            else:
                await send_callback(f"❌ Ошибка: {result.get('detail', '???')}")
        else:
            self.state.set_step(user_id, 'waiting_schedule_time')
            await send_callback("⏰ Введите время: `ГГГГ-ММ-ДД ЧЧ:ММ`")
    
    async def handle_schedule_time(self, user_id: int, time_str: str, send_callback):
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден")
            return
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
        publish_time = None
        for fmt in formats:
            try:
                publish_time = datetime.strptime(time_str.strip(), fmt)
                break
            except:
                continue
        if not publish_time or publish_time <= datetime.now():
            await send_callback("❌ Неверный формат времени")
            return
        job_id = f"post_{user_id}_{int(time.time())}"
        async def publish_job():
            await self.max_client.send_message(chat_id=self.channel_id, text=draft['text'], buttons=draft.get('buttons'), markup=draft.get('markup'))
        self.scheduler.scheduler.add_job(publish_job, DateTrigger(run_date=publish_time), id=job_id, replace_existing=True)
        self.state.clear_draft(user_id)
        await send_callback(f"✅ Запланировано на {time_str}")
    
    async def handle_stats(self, user_id: int, send_callback):
        await send_callback("📊 Статистика: пока пусто (функция в разработке)")


# ===================================================================
# 🌐 WEBHOOK
# ===================================================================
async def webhook_handler(request, handlers, send_callback_factory):
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    if request.method != 'POST':
        return web.Response(status=405)
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 Update: {json.dumps(body, ensure_ascii=False)[:400]}")
        if body.get('update_type') == 'message_created' and (msg := body.get('message')):
            await handle_incoming_message(msg, handlers, send_callback_factory)
        return web.Response(status=200)
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] ❌ Invalid JSON: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.exception(f"[WEBHOOK] 💥 Error: {e}")
        return web.Response(status=500)

async def handle_incoming_message(msg: Dict, handlers, send_callback_factory):
    logger.info("=" * 60)
    logger.info(f"[MSG] 📨 Processing message")
    recipient = msg.get('recipient', {})
    user_id = recipient.get('user_id') or recipient.get('chat_id') or recipient.get('id')
    chat_id_for_reply = recipient.get('chat_id') or recipient.get('user_id') or user_id
    if not user_id:
        logger.error(f"[MSG] ❌ No user_id")
        return
    logger.info(f"[MSG] 👤 user_id={user_id} | reply_chat_id={chat_id_for_reply}")
    
    async def send_callback(text: str, keyboard: Dict = None, markup: List = None):
        logger.info(f"[SEND] 📤 To chat_id={chat_id_for_reply}: text_len={len(text)}")
        buttons = keyboard['inline_keyboard'] if keyboard and 'inline_keyboard' in keyboard else None
        result = await handlers.max_client.send_message(chat_id=chat_id_for_reply, text=text, buttons=buttons, markup=markup)
        logger.info(f"[SEND] ← {result}")
        return result
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    logger.info(f"[MSG] 💬 Text: '{text[:100]}...' | markup={len(markup)}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 Step: {step}")
    
    if step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, send_callback)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    elif step == 'waiting_schedule_time':
        await handlers.handle_schedule_time(user_id, text.strip(), send_callback)
    elif text == '/start':
        await handlers.handle_start(user_id, send_callback)
    elif text == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    elif text == '/stats':
        await handlers.handle_stats(user_id, send_callback)
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback("❓ Неизвестная команда. /start, /post, /stats")
        else:
            await send_callback("🔐 Авторизуйтесь: /start")
    logger.info("=" * 60)


# ===================================================================
# 🌐 SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({'ok': True, 'status': 'running'})

async def root_handler(request):
    return web.json_response({'bot': 'MAX Channel Poster', 'webhook': 'active'})

async def on_startup(app):
    logger.info("🚀 STARTING MAX CHANNEL POSTER BOT — CLEAN")
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE)
    app['state'] = StateManager()
    app['max_client'] = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    app['stats'] = type('Stats', (), {'get_stats': lambda s, mid=None: []})()
    scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
    scheduler.start()
    app['scheduler'] = type('Sched', (), {'scheduler': scheduler})()
    app['handlers'] = CommandHandlers(app['auth'], app['state'], app['max_client'], app['scheduler'], app['stats'], CHANNEL_ID)
    if RENDER_EXTERNAL_URL:
        await app['max_client'].register_webhook(f"{RENDER_EXTERNAL_URL}/webhook", CHANNEL_ID)
    logger.info("✅ Initialized")

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if hasattr(app.get('scheduler'), 'scheduler'):
        app['scheduler'].scheduler.shutdown()
    if app.get('max_client'):
        await app['max_client'].close()

def create_app():
    app = web.Application()
    app.add_routes([web.get('/', root_handler), web.get('/health', health_check), web.post('/webhook', lambda req: webhook_handler(req, app['handlers'], lambda t, k=None, m=None: None))])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Server on port {port}")
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None, print=logger.info)
