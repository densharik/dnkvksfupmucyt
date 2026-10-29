import html
from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.config import Message


def fmt(template: str, user, tickets: int = 1, bot_username: str = "") -> str:
    return template.format_map({
        "name": html.escape(user["first_name"] or "друг"),
        "ticket": user["ticket"] or "",
        "tickets": tickets,
        "ref_link": ref_link(bot_username, user["tg_id"]),
    })


def ref_link(bot_username: str, tg_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{tg_id}"


def phone_keyboard(text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def message_keyboard(m: Message, link: str) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(text=b.text, url=str(b.url))] for b in m.buttons]
    if m.share_button:
        share = f"https://t.me/share/url?url={quote(link)}&text={quote("Записывайся на эфир")}"
        rows.append([InlineKeyboardButton(text=m.share_button, url=share)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    return "+" + digits


def mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    return phone[:4] + "*" * max(len(phone) - 6, 0) + phone[-2:]
