import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app import db
from app.api import create_app
from app.bot import router, set_admin_menu
from app.config import Settings, load_launch
from app.worker import run_worker

log = logging.getLogger("main")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    settings = Settings()
    cfg = load_launch(settings.launch_config)
    pool = await db.connect(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    me = await bot.get_me()
    log.info("bot @%s, launch %r, messages %s", me.username, cfg.launch.name,
             [(m.key, m.delay_seconds) for m in cfg.messages])

    if cfg.launch.description:
        await bot.set_my_description(cfg.launch.description.strip())

    for admin in settings.admins:
        await set_admin_menu(bot, admin, settings.webapp_url)

    dp = Dispatcher(pool=pool, cfg=cfg, settings=settings, bot_username=me.username)
    dp.include_router(router)

    server = uvicorn.Server(uvicorn.Config(create_app(pool, settings, cfg), host="0.0.0.0",
                                           port=settings.api_port, log_level="warning"))
    await asyncio.gather(
        dp.start_polling(bot, handle_signals=False),
        run_worker(bot, pool, cfg, me.username),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
