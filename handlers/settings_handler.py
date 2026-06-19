"""
Обработчики настроек и статистики
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_stats(send, stats):
    logger.info("[STATS] Requested")
    all_stats = stats.get_stats()
    if not all_stats:
        await send("📊 Пусто")
        return
    report = ["📊 Последние посты:\n"]
    for item in all_stats[-10:]:
        report.append(f"• {item['message_id'][:12]}... | 👁 {item.get('views', 0)}")
    await send('\n'.join(report))


async def handle_settings(send):
    logger.info("[SETTINGS] Requested")
    await send("⚙️ /set_channel ID | /set_password pwd | /list_admins")


async def handle_set_channel(user_id, new_id, send):
    logger.info(f"[SET-CH] user={user_id} channel={new_id}")
    await send(f"✅ Канал: {new_id} (перезапустите)")


async def handle_set_password(user_id, new_pwd, send, auth):
    logger.info(f"[SET-PASS] user={user_id}")
    auth.change_password(new_pwd)
    await send("✅ Пароль изменён")


async def handle_list_admins(send, auth):
    logger.info("[LIST-ADMINS] Requested")
    admins = auth.authorized
    if not admins:
        await send("👥 Пусто")
        return
    report = ["👥 Админы:"]
    for uid, data in admins.items():
        report.append(f"• {uid} | {data.get('auth_time', '')[:16]}")
    await send('\n'.join(report))
