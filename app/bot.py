import logging

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import ChatMemberUpdatedFilter, Command, CommandObject, CommandStart, KICKED, MEMBER
from aiogram.types import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from app import db
from app.config import LaunchConfig, Settings
from app.deeplink import Source, parse_start
from app.render import fmt, normalize_phone, phone_keyboard

log = logging.getLogger("bot")
router = Router()


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, pool: asyncpg.Pool, cfg: LaunchConfig,
                   bot: Bot, settings: Settings, box: dict, bot_username: str):
    u = message.from_user
    src = parse_start(command.args)
    user, is_new = await db.register_start(pool, u.id, u.first_name, u.username, src)
    log.info("start user=%s new=%s src=%s", u.id, is_new, src.raw or "organic")

    if u.id in settings.admins:
        await set_admin_menu(bot, u.id, box.get("webapp_url"))

    if user["phone"]:
        tickets = await db.tickets_count(pool, u.id)
        await message.answer(fmt(cfg.texts.already_registered, user, tickets, bot_username),
                             reply_markup=ReplyKeyboardRemove())
        return

    await message.answer(fmt(cfg.texts.welcome, user))
    await message.answer(fmt(cfg.texts.ask_phone, user), reply_markup=phone_keyboard(cfg.texts.phone_button))
    if cfg.nudge and is_new:
        await db.schedule(pool, u.id, "nudge", cfg.nudge.delay_seconds)


@router.message(F.contact)
async def on_contact(message: Message, pool: asyncpg.Pool, cfg: LaunchConfig, bot: Bot, bot_username: str):
    u = message.from_user
    # Контакт можно переслать чужой - принимаем только свой.
    if message.contact.user_id != u.id:
        await message.answer(cfg.texts.wrong_contact, reply_markup=phone_keyboard(cfg.texts.phone_button))
        return

    await db.register_start(pool, u.id, u.first_name, u.username, Source())
    user = await db.set_phone(pool, u.id, normalize_phone(message.contact.phone_number))
    if user is None:
        user = await db.get_user(pool, u.id)
        tickets = await db.tickets_count(pool, u.id)
        await message.answer(fmt(cfg.texts.already_registered, user, tickets, bot_username),
                             reply_markup=ReplyKeyboardRemove())
        return

    log.info("phone user=%s ticket=%s", u.id, user["ticket"])
    await message.answer(cfg.texts.thanks, reply_markup=ReplyKeyboardRemove())
    for m in cfg.messages:
        await db.schedule(pool, u.id, m.key, m.delay_seconds)

    if user["ref_by"]:
        await credit_referrer(bot, pool, cfg, user["ref_by"])


async def credit_referrer(bot: Bot, pool: asyncpg.Pool, cfg: LaunchConfig, ref_by: int):
    referrer = await db.get_user(pool, ref_by)
    if referrer is None:
        return
    tickets = await db.tickets_count(pool, ref_by)
    try:
        await bot.send_message(ref_by, fmt(cfg.texts.referral_bonus, referrer, tickets))
    except TelegramAPIError as e:
        log.warning("referral notify failed user=%s: %s", ref_by, e)


@router.message(Command("dashboard"))
async def on_dashboard(message: Message, settings: Settings, box: dict, bot: Bot):
    if message.from_user.id not in settings.admins:
        return
    url = box.get("webapp_url")
    if not url:
        await message.answer("Адрес миниаппа ещё не готов: туннель не поднят. Смотри логи.")
        return
    await set_admin_menu(bot, message.from_user.id, url)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть дашборд", web_app=WebAppInfo(url=url))]])
    await message.answer("Статистика воронки:", reply_markup=kb)


@router.message()
async def on_other(message: Message, pool: asyncpg.Pool, cfg: LaunchConfig):
    u = message.from_user
    user, _ = await db.register_start(pool, u.id, u.first_name, u.username, Source())
    if not user["phone"]:
        await message.answer(fmt(cfg.texts.ask_phone, user), reply_markup=phone_keyboard(cfg.texts.phone_button))


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=KICKED))
async def on_blocked(event: ChatMemberUpdated, pool: asyncpg.Pool):
    await db.mark_blocked(pool, event.from_user.id)
    log.info("blocked user=%s", event.from_user.id)


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def on_unblocked(event: ChatMemberUpdated, pool: asyncpg.Pool):
    await pool.execute("UPDATE users SET blocked_at = NULL WHERE tg_id = $1", event.from_user.id)


async def set_admin_menu(bot: Bot, admin_id: int, url: str | None):
    if not url:
        return
    try:
        await bot.set_chat_menu_button(
            chat_id=admin_id, menu_button=MenuButtonWebApp(text="Дашборд", web_app=WebAppInfo(url=url))
        )
    except TelegramAPIError as e:
        # Админ ещё не нажимал /start у бота - кнопка поставится при первом /start.
        log.info("menu button for admin=%s not set: %s", admin_id, e)
