import asyncio
import logging

import asyncpg
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import LinkPreviewOptions

from app import db
from app.config import LaunchConfig
from app.render import fmt, message_keyboard, phone_keyboard, ref_link

log = logging.getLogger("worker")

MAX_ATTEMPTS = 3
SEND_PAUSE = 0.05  # ~20 сообщений/с, ниже общего лимита Telegram в 30/с


async def send_job(bot: Bot, pool: asyncpg.Pool, cfg: LaunchConfig, bot_username: str, job) -> None:
    user = await db.get_user(pool, job["tg_id"])

    if job["key"] == "nudge":
        if cfg.nudge is None or user["phone"]:
            await db.finish_job(pool, job["id"], "skipped")
            return
        await bot.send_message(user["tg_id"], fmt(cfg.nudge.text, user),
                               reply_markup=phone_keyboard(cfg.texts.phone_button))
    else:
        m = next((m for m in cfg.messages if m.key == job["key"]), None)
        if m is None:
            # Сообщение убрали из конфига, пока задача ждала очереди.
            await db.finish_job(pool, job["id"], "skipped", "not in config")
            return
        tickets = await db.tickets_count(pool, user["tg_id"])
        await bot.send_message(
            user["tg_id"],
            fmt(m.text, user, tickets, bot_username),
            reply_markup=message_keyboard(m, ref_link(bot_username, user["tg_id"])),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    await db.finish_job(pool, job["id"], "sent")
    log.info("sent user=%s key=%s", user["tg_id"], job["key"])


async def process(bot: Bot, pool: asyncpg.Pool, cfg: LaunchConfig, bot_username: str, job) -> None:
    try:
        await send_job(bot, pool, cfg, bot_username, job)
    except TelegramRetryAfter as e:
        log.warning("flood limit user=%s key=%s retry_after=%s", job["tg_id"], job["key"], e.retry_after)
        await db.retry_job(pool, job["id"], e.retry_after, "retry_after")
    except TelegramForbiddenError:
        log.info("blocked user=%s key=%s", job["tg_id"], job["key"])
        await db.finish_job(pool, job["id"], "failed", "blocked")
        await db.mark_blocked(pool, job["tg_id"])
    except (TelegramAPIError, OSError) as e:
        if job["attempts"] + 1 >= MAX_ATTEMPTS:
            log.error("give up user=%s key=%s: %s", job["tg_id"], job["key"], e)
            await db.finish_job(pool, job["id"], "failed", str(e)[:300])
        else:
            delay = 5 * 2 ** job["attempts"]
            log.warning("retry in %ss user=%s key=%s: %s", delay, job["tg_id"], job["key"], e)
            await db.retry_job(pool, job["id"], delay, str(e)[:300])


async def run_worker(bot: Bot, pool: asyncpg.Pool, cfg: LaunchConfig, bot_username: str) -> None:
    tick = 0
    while True:
        if tick % 30 == 0 and (n := await db.recover_stale(pool)):
            log.warning("recovered %s stale jobs", n)
        tick += 1
        jobs = await db.claim_due(pool)
        for job in jobs:
            await process(bot, pool, cfg, bot_username, job)
            await asyncio.sleep(SEND_PAUSE)
        if not jobs:
            await asyncio.sleep(1)
