"""Команда /чистка: всем, кто не набрал недельную норму, — 1 варн на две недели (с подтверждением)."""
import asyncio
import logging
import secrets
import time
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import phrases
from config import LEVEL_ADMIN, MAX_ACTIVE_WARNS, WARN_COOLDOWN_SECONDS, get_creator_id
from db import Database
from quota import current_week_start_ts
from utils import chat_quota, get_args, is_group, level_of, try_delete_command_message

cleanup_router = Router()

CLEAN_MIN_LEVEL = LEVEL_ADMIN                 # /чистка — Админ и выше
CLEAN_WARN_DURATION = timedelta(weeks=2)      # срок варна
CONFIRM_TTL_SECONDS = 600
CLEAN_REASON = "чистка: недельная норма"

_pending: dict[str, dict] = {}   # токен подтверждения -> {chat_id, issuer_id, issuer_level, expires}
_running: set[int] = set()       # чаты, где чистка выполняется прямо сейчас


def confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=phrases.CLEAN_BTN_YES, callback_data=f"cl:y:{token}"),
        InlineKeyboardButton(text=phrases.CLEAN_BTN_NO, callback_data=f"cl:n:{token}"),
    ]])


async def find_targets(bot: Bot, db: Database, chat_id: int, issuer_level: int, quota: int) -> list[dict]:
    """Кого коснётся чистка: не набрали норму за текущую неделю, но НЕ на ресте, НЕ новички этой недели
    и ниже рангом, чем тот, кто запустил чистку."""
    rows = await db.get_quota_candidates(chat_id, quota, current_week_start_ts())
    return [r for r in rows if await level_of(db, bot, chat_id, r["user_id"]) < issuer_level]


@cleanup_router.message(Command("чистка", ignore_case=True))
async def cmd_clean(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    issuer_level = await level_of(db, bot, chat_id, message.from_user.id)
    if issuer_level < CLEAN_MIN_LEVEL:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return
    if get_args(message):
        await message.reply(phrases.USAGE_CLEAN)
        return

    quota = await chat_quota(db, chat_id)
    targets = await find_targets(bot, db, chat_id, issuer_level, quota)
    if not targets:
        await message.reply(phrases.CLEAN_NOBODY)
        return
    will_ban = 0
    for row in targets:
        if await db.get_total_warns(chat_id, row["user_id"]) >= MAX_ACTIVE_WARNS:
            will_ban += 1

    now = time.monotonic()
    for token in [t for t, r in _pending.items() if r["expires"] < now]:   # чистим просроченные запросы
        del _pending[token]
    token = secrets.token_hex(4)
    _pending[token] = {"chat_id": chat_id, "issuer_id": message.from_user.id,
                       "issuer_level": issuer_level, "expires": now + CONFIRM_TTL_SECONDS}

    await try_delete_command_message(message)
    await message.answer(
        phrases.CLEAN_CONFIRM.format(quota=quota, count=len(targets), bans=will_ban, limit=MAX_ACTIVE_WARNS),
        reply_markup=confirm_keyboard(token))


async def run_clean(bot: Bot, db: Database, chat_id: int, issuer_id: int, issuer_level: int, quota: int) -> dict:
    """Выдаёт варны. Список пересчитывается в момент подтверждения: кто успел набрать норму — не пострадает.
    Правила те же, что у команды «варн»: не чаще раза в час, 3-й активный варн = бан."""
    stats = {"warned": 0, "banned": 0, "recent": 0, "gone": 0, "failed": 0}
    now = int(time.time())
    expires_at = now + int(CLEAN_WARN_DURATION.total_seconds())

    for row in await find_targets(bot, db, chat_id, issuer_level, quota):
        user_id = row["user_id"]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception as e:
            logging.warning("Чистка: get_chat_member(%s) не удался: %s", user_id, e)
            stats["failed"] += 1
            continue
        if member.status in ("left", "kicked"):
            await db.mark_left(chat_id, user_id)
            stats["gone"] += 1
            continue
        if member.status == "creator" or member.user.is_bot:
            continue

        last_warn = await db.get_last_warn_time(chat_id, user_id)
        if last_warn and now - last_warn < WARN_COOLDOWN_SECONDS:
            stats["recent"] += 1
            continue

        if await db.get_total_warns(chat_id, user_id) >= MAX_ACTIVE_WARNS:
            try:
                await bot.ban_chat_member(chat_id, user_id)
            except Exception as e:
                logging.warning("Чистка: бан %s не удался: %s", user_id, e)
                stats["failed"] += 1
                continue
            await db.reset_warns(chat_id, user_id)
            await db.mark_left(chat_id, user_id)   # забанен — дальше в списки не попадает
            stats["banned"] += 1
        else:
            await db.add_temp_warn(chat_id, user_id, expires_at, issued_by=issuer_id, reason=CLEAN_REASON)
            stats["warned"] += 1
        await asyncio.sleep(0.05)
    return stats


@cleanup_router.callback_query(F.data.startswith("cl:"))
async def on_clean_button(call: CallbackQuery, bot: Bot, db: Database):
    try:
        _, action, token = call.data.split(":")
    except ValueError:
        await call.answer()
        return

    request = _pending.get(token)
    if not request or request["expires"] < time.monotonic():
        _pending.pop(token, None)
        await call.answer(phrases.CLEAN_EXPIRED, show_alert=True)
        if call.message:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
        return
    if call.from_user.id not in (request["issuer_id"], get_creator_id()):
        await call.answer(phrases.ERR_NO_PERMISSION, show_alert=True)
        return

    if action == "n":
        del _pending[token]
        await call.answer()
        if call.message:
            await call.message.edit_text(phrases.CLEAN_CANCELLED, reply_markup=None)
        return
    if action != "y":
        await call.answer()
        return

    chat_id = request["chat_id"]
    if chat_id in _running:
        await call.answer(phrases.CLEAN_BUSY, show_alert=True)
        return
    del _pending[token]
    _running.add(chat_id)
    await call.answer()
    try:
        if call.message:
            await call.message.edit_text(phrases.CLEAN_RUNNING, reply_markup=None)
        quota = await chat_quota(db, chat_id)
        stats = await run_clean(bot, db, chat_id, request["issuer_id"], request["issuer_level"], quota)
        summary = phrases.CLEAN_DONE.format(quota=quota, **stats)
    except Exception:
        logging.exception("Ошибка при выполнении чистки")
        summary = phrases.CLEAN_FAILED
    finally:
        _running.discard(chat_id)
    if call.message:
        await call.message.edit_text(summary, reply_markup=None)
