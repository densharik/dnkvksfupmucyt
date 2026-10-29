import asyncio
import logging

import httpx
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app import db
from app.api import create_app
from app.bot import router, set_admin_menu
from app.config import Settings, load_launch
from app.worker import run_worker

log = logging.getLogger("main")


async def resolve_webapp_url(bot: Bot, settings: Settings, box: dict) -> None:
    """Берёт https-адрес у cloudflared quick tunnel и вешает кнопку дашборда админам."""
    url = settings.webapp_url
    async with httpx.AsyncClient(timeout=3) as client:
        for _ in range(60):
            if url:
                break
            try:
                host = (await client.get(f"{settings.cloudflared_metrics}/quicktunnel")).json().get("hostname")
                url = f"https://{host}/" if host else ""
            except (httpx.HTTPError, ValueError):
                pass
            if not url:
                await asyncio.sleep(2)
    if not url:
        log.error("webapp url not found: set WEBAPP_URL or start cloudflared")
        return
    box["webapp_url"] = url
    log.info("dashboard: %s", url)
    for admin in settings.admins:
        await set_admin_menu(bot, admin, url)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = Settings()
    cfg = load_launch(settings.launch_config)
    pool = await db.connect(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    me = await bot.get_me()
    log.info("bot @%s, launch %r, messages %s", me.username, cfg.launch.name,
             [(m.key, m.delay_seconds) for m in cfg.messages])

    if cfg.launch.description:
        await bot.set_my_description(cfg.launch.description.strip())

    box: dict = {}
    dp = Dispatcher(pool=pool, cfg=cfg, settings=settings, box=box, bot_username=me.username)
    dp.include_router(router)

    server = uvicorn.Server(uvicorn.Config(create_app(pool, settings, cfg), host="0.0.0.0",
                                           port=settings.api_port, log_level="warning"))
    await asyncio.gather(
        dp.start_polling(bot, handle_signals=False),
        run_worker(bot, pool, cfg, me.username),
        server.serve(),
        resolve_webapp_url(bot, settings, box),
    )


if __name__ == "__main__":
    asyncio.run(main())
