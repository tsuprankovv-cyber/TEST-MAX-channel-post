import asyncio
import logging
import os
import json
import time

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    force=True
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

user_sessions = {}
api_session = None


# ===================================================================
# API ЗАПРОСЫ (с логированием времени)
# ===================================================================
async def api_request(method, endpoint, data=None, max_retries=3):
    headers = {
        "Authorization": BOT_TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "MAX-Channel-Poster/1.0"
    }
    url = f"{BASE_API_URL}{endpoint}"
    timeout = ClientTimeout(total=60)  # 🔥 Увеличил до 60 сек
    
    for attempt in range(max_retries):
        start_time = time.time()
        try:
            logger.info(f"[API] #{attempt+1} {method} {url[:100]}...")
            
            async with api_session.request(
                method=method, url=url, headers=headers,
                json=data, timeout=timeout
            ) as response:
                elapsed = time.time() - start_time
                text = await response.text()
                
                logger.info(f"[API] ← {response.status} in {elapsed:.2f}s | {text[:200]}")
                
                if response.status == 429:
                    wait = int(response.headers.get('Retry-After', 30))
                    logger.warning(f"⏳ Rate limit, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                
                if response.status == 200:
                    try:
                        return json.loads(text) if text.strip() else {}
                    except:
                        return {"raw": text}
                
                # Возвращаем ошибку для перебора вариантов
                return {"error": f"HTTP_{response.status}", "detail": text, "status": response.status}
                
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[API] #{attempt+1} Exception after {elapsed:.2f}s: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    return {"error": "max_retries"}


# ===================================================================
# УМНАЯ ОТПРАВКА СООБЩЕНИЙ (перебор всех вариантов!)
# ===================================================================
async def send_message_smart(recipient, text, keyboard=None):
    """
    Отправляет сообщение, перебирая ВСЕ возможные варианты:
    - Эндпоинты: /messages, /messages?user_id=, /messages?chat_id=
    - Параметры в URL или в body
    - ID: chat_id или user_id из recipient
    - Формат кнопок: buttons / reply_markup / attachments
    """
    
    logger.info("=" * 80)
    logger.info(f"[SEND] 🚀 Starting smart send")
    logger.info(f"[SEND] Text length: {len(text)}")
    logger.info(f"[SEND] Recipient structure: {json.dumps(recipient, ensure_ascii=False)[:300]}")
    
    # 🔥 Извлекаем все возможные ID
    possible_ids = []
    if isinstance(recipient, dict):
        if recipient.get('chat_id'): possible_ids.append(('chat_id', recipient['chat_id']))
        if recipient.get('user_id'): possible_ids.append(('user_id', recipient['user_id']))
        if recipient.get('id'): possible_ids.append(('id', recipient['id']))
    
    logger.info(f"[SEND] Possible IDs to try: {possible_ids}")
    
    # 🔥 Формируем кнопки в 3 возможных форматах
    button_variants = []
    
    # Вариант 1: buttons (массив)
    if keyboard and "inline_keyboard" in keyboard:
        buttons_flat = []
        for row in keyboard["inline_keyboard"]:
            for btn in row:
                btn_data = {"text": btn.get("text", "")}
                if btn.get("url"): btn_data["url"] = btn["url"]
                if btn.get("callback_data"): btn_data["callback_data"] = btn["callback_data"]
                buttons_flat.append(btn_data)
        button_variants.append(("buttons", buttons_flat))
    
    # Вариант 2: reply_markup
    if keyboard:
        button_variants.append(("reply_markup", keyboard))
    
    # Вариант 3: attachments
    if keyboard and "inline_keyboard" in keyboard:
        button_variants.append(("attachments", [{"type": "inline_keyboard", "payload": keyboard}]))
    
    # Если кнопок нет — добавляем пустой вариант
    if not button_variants:
        button_variants.append(("buttons", []))
    
    logger.info(f"[SEND] Button variants to try: {[name for name, _ in button_variants]}")
    
    # 🔥 Перебираем ВСЕ комбинации
    for id_name, id_value in possible_ids:
        for endpoint_variant in ["messages", f"messages?{id_name}={{id}}"]:
            for body_location in ["body", "url"]:  # параметр в теле или в URL
                for btn_name, btn_value in button_variants:
                    
                    # 🔧 Формируем запрос
                    if endpoint_variant == "messages" or body_location == "body":
                        endpoint = "/messages"
                        payload = {"text": text, btn_name: btn_value}
                        # Добавляем ID в тело запроса
                        payload[id_name] = id_value
                        url_params = None
                    else:
                        endpoint = f"/messages?{id_name}={id_value}"
                        payload = {"text": text, btn_name: btn_value}
                        url_params = None
                    
                    logger.info(f"[SEND] 🔄 Trying: {endpoint} | {id_name}={id_value} | {btn_name}={len(btn_value) if isinstance(btn_value, list) else 'object'}")
                    
                    result = await api_request("POST", endpoint, data=payload)
                    
                    # 🔍 Проверяем результат
                    if "error" not in result:
                        logger.info(f"[SEND] ✅ SUCCESS with: {endpoint} | {id_name}={id_value} | {btn_name}")
                        logger.info("=" * 80)
                        return True
                    else:
                        status = result.get("status")
                        detail = result.get("detail", "")[:100]
                        logger.warning(f"[SEND] ❌ Failed ({status}): {detail}")
                        
                        # 🔥 Если ошибка "неверный chatId" или "not found" — пробуем следующий вариант
                        if status in (400, 403, 404) and ("chatId" in detail.lower() or "not found" in detail.lower() or "invalid" in detail.lower()):
                            logger.info(f"[SEND] → Trying next variant...")
                            continue
                        # Если другая ошибка (401, 500) — останавливаемся
                        elif status in (401, 500, 502, 503):
                            logger.error(f"[SEND] 🛑 Critical error, stopping")
                            logger.info("=" * 80)
                            return False
    
    logger.error(f"[SEND] ❌ ALL VARIANTS FAILED")
    logger.info("=" * 80)
    return False


# ===================================================================
# ОТПРАВКА В КАНАЛ (аналогично, но с CHANNEL_ID)
# ===================================================================
async def publish_to_channel(post_data):
    """Публикация поста в канал с перебором вариантов"""
    
    logger.info(f"[PUBLISH] 🚀 Starting channel publish")
    
    # 🔥 Пробуем CHANNEL_ID с минусом и без
    channel_ids_to_try = [CHANNEL_ID]
    if CHANNEL_ID.startswith('-'):
        channel_ids_to_try.append(CHANNEL_ID[1:])  # без минуса
    else:
        channel_ids_to_try.append('-' + CHANNEL_ID)  # с минусом
    
    logger.info(f"[PUBLISH] Channel IDs to try: {channel_ids_to_try}")
    
    # Формируем кнопки
    buttons = []
    if post_data.get('button_title') and post_data.get('button_url'):
        buttons.append({"text": post_data['button_title'], "url": post_data['button_url']})
    
    # Перебираем варианты
    for cid in channel_ids_to_try:
        for endpoint_variant in ["/messages", f"/messages?chat_id={cid}", f"/messages?user_id={cid}"]:
            for btn_format in [("buttons", buttons if buttons else []), ("reply_markup", {"inline_keyboard": [[{"text": post_data.get('button_title'), "url": post_data.get('button_url')}]]}) if buttons else ("buttons", [])]:
                
                btn_name, btn_value = btn_format
                payload = {"text": post_data.get('text', ''), btn_name: btn_value}
                
                # Если эндпоинт уже содержит ID — не добавляем в body
                if "chat_id=" not in endpoint_variant and "user_id=" not in endpoint_variant:
                    payload["chat_id"] = cid
                
                logger.info(f"[PUBLISH] 🔄 Trying: {endpoint_variant} | chat_id={cid}")
                
                result = await api_request("POST", endpoint_variant, data=payload)
                
                if "error" not in result:
                    logger.info(f"[PUBLISH] ✅ SUCCESS with: {endpoint_variant}")
                    return True
                else:
                    logger.warning(f"[PUBLISH] ❌ Failed: {result.get('detail', '')[:100]}")
    
    logger.error(f"[PUBLISH] ❌ ALL VARIANTS FAILED")
    return False


# ===================================================================
# РЕГИСТРАЦИЯ ВЕБХУКА
# ===================================================================
async def register_webhook(webhook_url):
    """Регистрирует вебхук в MAX API"""
    logger.info(f"[WEBHOOK] Registering: {webhook_url} for chat {CHANNEL_ID}")
    
    body = {
        "url": webhook_url,
        "chat_id": CHANNEL_ID,
        "update_types": ["message_created"]
    }
    
    result = await api_request("POST", "/subscriptions", data=body)
    
    if "error" not in result:
        logger.info("[WEBHOOK] ✅ Registered successfully")
        return True
    else:
        logger.error(f"[WEBHOOK] ❌ Failed: {result}")
        return False


# ===================================================================
# ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ
# ===================================================================
async def webhook_handler(request):
    """Принимает обновления от MAX API"""
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    
    if request.method != 'POST':
        return web.Response(status=405)
    
    try:
        body = await request.json()
        update_type = body.get('update_type', 'unknown')
        logger.info(f"[WEBHOOK] Type: {update_type}")
        
        if update_type == 'message_created' and (msg := body.get('message')):
            await handle_max_message(msg)
        
        return web.Response(status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] Invalid JSON: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.error(f"[WEBHOOK] Error: {e}", exc_info=True)
        return web.Response(status=500)


async def handle_max_message(msg):
    """Обработка сообщения от пользователя"""
    
    logger.info("=" * 80)
    logger.info(f"[HANDLE] 📦 Full message: {json.dumps(msg, ensure_ascii=False, indent=2)[:1500]}")
    
    # 🔥 Извлекаем recipient для отправки ответа
    recipient = msg.get('recipient') or msg.get('sender') or {}
    
    if not recipient:
        logger.error("[HANDLE] ❌ No recipient or sender found")
        return
    
    # Извлекаем текст
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    
    logger.info(f"[HANDLE] 💬 Text: '{text[:100] if text else '[empty]'}'")
    
    # Обработка команд
    if text == "/start":
        logger.info(f"[HANDLE] 🎯 Processing /start")
        kb = {"inline_keyboard": [
            [{"text": "➕ Новый пост", "callback_data": "new_post"}],
            [{"text": "ℹ️ Помощь", "callback_data": "help"}]
        ]}
        await send_message_smart(recipient, "👋 **MAX Channel Poster**\n\nНажми «Новый пост»", kb)
    
    elif text == "/post":
        logger.info(f"[HANDLE] 🎯 Processing /post")
        # Используем chat_id как ключ сессии (более стабильный)
        session_key = recipient.get('chat_id') or recipient.get('user_id') or recipient.get('id')
        if session_key:
            user_sessions[session_key] = {"step": "waiting_text"}
            await send_message_smart(recipient, "📝 Отправь текст поста")
    
    elif recipient.get('chat_id') or recipient.get('user_id'):
        session_key = recipient.get('chat_id') or recipient.get('user_id')
        if session_key in user_sessions:
            sd = user_sessions[session_key]
            step = sd.get("step")
            logger.info(f"[HANDLE] 🎯 Session step={step}")
            
            if step == "waiting_text":
                sd["text"] = text
                sd["step"] = "waiting_button"
                await send_message_smart(recipient, "🔘 Кнопка: `Текст | ссылка`\nИли `пропустить`")
            
            elif step == "waiting_button":
                if text and text.lower() not in ("пропустить", "skip", "-"):
                    if "|" in text:
                        parts = text.split("|", 1)
                        sd["button_title"] = parts[0].strip()
                        sd["button_url"] = parts[1].strip()
                    else:
                        await send_message_smart(recipient, "❌ Формат: `Текст | ссылка`")
                        return
                ok = await publish_to_channel(sd)
                await send_message_smart(recipient, "✅ Опубликовано!" if ok else "❌ Ошибка")
                del user_sessions[session_key]
    
    logger.info("=" * 80)


# ===================================================================
# WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "status": "running"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "webhook": "active"})

async def on_startup(app):
    global api_session
    logger.info("🚀 Starting MAX Channel Poster (Webhook mode)")
    api_session = ClientSession()
    
    if RENDER_EXTERNAL_URL and CHANNEL_ID:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await register_webhook(webhook_url)

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if api_session:
        await api_session.close()

app = web.Application()
app.add_routes([
    web.get('/', root_handler),
    web.get('/health', health_check),
    web.post('/webhook', webhook_handler),
])
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Server on port {port}")
    logger.info(f"🔗 Webhook: {RENDER_EXTERNAL_URL}/webhook if set")
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
