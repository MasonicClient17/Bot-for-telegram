"""Профили («кто я» / «кто ты»), недельная норма (/норма), неактив (/неактив) и рест (/рест)."""
import re
import time
from datetime import timedelta

from aiogram import Bot, Router, types
from aiogram.filters import Command
from aiogram.types import Message

import phrases
from config import LEVEL_ADMIN, LEVEL_OWNER
from db import Database, pick_display_name
from quota import current_week_start_ts
from utils import (
    answer_long, chat_quota, esc, format_date, get_args, get_chat_owner_id, is_group, is_number,
    kw, kw_phrase, level_of, prepare_target, resolve_target, try_delete_command_message,
)

profile_router = Router()

NORM_MIN_LEVEL = LEVEL_ADMIN   # /норма и /неактив — Админ и выше
REST_MIN_LEVEL = LEVEL_OWNER   # /рест и -рест — только Владелец (модератор 3-го порядка)
MAX_WEEKLY_QUOTA = 100_000
INACTIVE_LIST_LIMIT = 50

REST_RE = re.compile(r"([0-9]{0,3})([нм])", re.IGNORECASE)
REST_UNITS = {"н": timedelta(weeks=1), "м": timedelta(days=30)}   # месяц = 30 дней
REST_DEFAULT = timedelta(weeks=1)
MAX_REST = timedelta(days=365)


# ---------- статус активности ----------

def activity_emoji(count: int, quota: int) -> str:
    """Эмодзи по доле недельной нормы (границы включают нижнюю):
    ⬛ меньше 33% · 🟥 33–66% · 🟧 66–100% · 🟩 ровно 100% · 🟦 больше 100%.
    Целочисленная арифметика — без ошибок округления float."""
    quota, count = max(1, quota), max(0, count)
    if count > quota:
        return phrases.ACTIVITY_EMOJI[4]
    if count == quota:
        return phrases.ACTIVITY_EMOJI[3]
    if count * 100 >= quota * 66:
        return phrases.ACTIVITY_EMOJI[2]
    if count * 100 >= quota * 33:
        return phrases.ACTIVITY_EMOJI[1]
    return phrases.ACTIVITY_EMOJI[0]


def status_title(level: int) -> str:
    """Хелпер / Админ / Владелец по уровню; без уровня — «Участник»."""
    if level <= 0:
        return phrases.STATUS_MEMBER
    return phrases.MOD_STATUS_NAMES[min(level, LEVEL_OWNER)]


def joined_text(row: dict) -> str:
    # Telegram не отдаёт ботам дату вступления: точная известна, только если бот видел вступление
    if row["joined_at"]:
        return format_date(row["joined_at"])
    if row["first_seen"]:
        return "≈" + format_date(row["first_seen"])
    return phrases.JOINED_UNKNOWN


async def profile_status(db: Database, bot: Bot, chat_id: int, user_id: int) -> str:
    """Статус, который у человека есть В ГРУППЕ: владелец группы — Владелец, иначе уровень из базы.
    Привилегии суперпользователя (CREATOR_ID) в профиле не показываются."""
    if user_id == await get_chat_owner_id(bot, chat_id):
        return status_title(LEVEL_OWNER)
    return status_title(await db.get_stored_moderator_level(chat_id, user_id))


async def build_profile(db: Database, bot: Bot, chat_id: int, user: types.User) -> str:
    await db.touch_user(chat_id, user.id, user.username, user.first_name)  # гарантирует строку в БД
    row = await db.get_profile(chat_id, user.id)
    quota = await chat_quota(db, chat_id)
    name = pick_display_name(row["rp_name"], row["tag"], row["first_name"], row["username"], user.full_name)
    return phrases.PROFILE_TEMPLATE.format(
        name=esc(name),
        joined=esc(joined_text(row)),
        count=row["week_count"],
        emoji=activity_emoji(row["week_count"], quota),
        status=esc(await profile_status(db, bot, chat_id, user.id)),
        reputation=row["reputation"],
    )


async def send_profile(message: Message, user: types.User, db: Database, bot: Bot):
    if user.is_bot:
        await message.reply(phrases.ERR_PROFILE_BOT)
        return
    await message.reply(await build_profile(db, bot, message.chat.id, user))


# ---------- кто я / кто ты ----------

@profile_router.message(kw_phrase("кто", "я"))
async def cmd_whoami(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    if get_args(message, skip=2):
        await message.reply(phrases.USAGE_WHOAMI)
        return
    await send_profile(message, message.from_user, db, bot)


@profile_router.message(kw_phrase("кто", "ты"))
async def cmd_whois(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    target, rest = await resolve_target(message, get_args(message, skip=2), db, bot)
    if not target or rest:
        await message.reply(phrases.USAGE_WHOIS)
        return
    await send_profile(message, target, db, bot)


# ---------- норма и неактив ----------

@profile_router.message(Command("норма", ignore_case=True))
async def cmd_set_quota(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < NORM_MIN_LEVEL:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    args = get_args(message).split()
    if len(args) != 1 or not is_number(args[0]) or not 1 <= int(args[0]) <= MAX_WEEKLY_QUOTA:
        await message.reply(phrases.USAGE_QUOTA.format(
            current=await chat_quota(db, chat_id), max=MAX_WEEKLY_QUOTA))
        return

    quota = int(args[0])
    await db.set_weekly_quota(chat_id, quota)
    await try_delete_command_message(message)
    await message.answer(phrases.QUOTA_SET.format(quota=quota))


@profile_router.message(Command("неактив", ignore_case=True))
async def cmd_inactive(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < NORM_MIN_LEVEL:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return
    if get_args(message):
        await message.reply(phrases.USAGE_INACTIVE)
        return

    quota = await chat_quota(db, chat_id)
    total = await db.count_inactive_members(chat_id, quota)
    await try_delete_command_message(message)
    if total == 0:
        await message.answer(phrases.INACTIVE_EMPTY)
        return

    rows = await db.get_inactive_members(chat_id, quota, INACTIVE_LIST_LIMIT)
    text = phrases.INACTIVE_HEADER.format(
        quota=quota, since=format_date(current_week_start_ts()), total=total)
    now = int(time.time())
    for idx, row in enumerate(rows, start=1):
        name = pick_display_name(row["rp_name"], row["tag"], row["first_name"], row["username"],
                                 str(row["user_id"]))
        text += phrases.INACTIVE_LINE.format(
            index=idx, name=esc(name), count=row["week_count"], quota=quota,
            emoji=activity_emoji(row["week_count"], quota),
            rest=phrases.REST_TAG if row["rest_until"] > now else "")
    if total > len(rows):
        text += phrases.INACTIVE_MORE.format(n=total - len(rows))
    await answer_long(message, text)


# ---------- рест (отдых от нормы) ----------

def parse_rest_duration(token: str) -> timedelta | None:
    """'2н' -> 2 недели, '1м' -> 30 дней, 'н' / 'м' (число опущено) -> 1 неделя / 1 месяц.
    Мусор и нулевой срок -> None."""
    match = REST_RE.fullmatch(token)
    if not match:
        return None
    number = int(match.group(1)) if match.group(1) else 1
    if number == 0:
        return None
    return REST_UNITS[match.group(2).lower()] * number


@profile_router.message(Command("рест", ignore_case=True))
async def cmd_rest(message: Message, db: Database, bot: Bot):
    """/рест [число][н|м] [@username] — отдых от нормы; без срока — 1 неделя."""
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=REST_MIN_LEVEL,
                                    hierarchy=False, usage=phrases.USAGE_REST_LINE)
    if not prepared:
        return
    target, rest = prepared
    if target.is_bot:
        await message.reply(phrases.ERR_BOT_TARGET)
        return

    tokens = rest.split()
    duration = REST_DEFAULT if not tokens else (parse_rest_duration(tokens[0]) if len(tokens) == 1 else None)
    if duration is None:
        await message.reply(phrases.USAGE_REST)
        return
    if duration > MAX_REST:
        await message.reply(phrases.ERR_REST_TOO_LONG.format(days=MAX_REST.days))
        return

    chat_id = message.chat.id
    until = int(time.time() + duration.total_seconds())
    await db.touch_user(chat_id, target.id, target.username, target.first_name)
    await db.set_rest(chat_id, target.id, until)
    name = esc(await db.get_display_name(chat_id, target.id, fallback=target.full_name))
    await try_delete_command_message(message)
    await message.answer(phrases.REST_SET.format(user=name, until=format_date(until)))


@profile_router.message(kw("-рест"))
async def cmd_rest_cancel(message: Message, db: Database, bot: Bot):
    """-рест [@username] — досрочно снимает рест."""
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=REST_MIN_LEVEL,
                                    hierarchy=False, usage=phrases.USAGE_REST_CANCEL_LINE)
    if not prepared:
        return
    target, rest = prepared
    if rest:
        await message.reply(phrases.USAGE_REST_CANCEL)
        return

    chat_id = message.chat.id
    name = esc(await db.get_display_name(chat_id, target.id, fallback=target.full_name))
    if not await db.clear_rest(chat_id, target.id):
        await message.reply(phrases.REST_NOT_ACTIVE.format(user=name))
        return
    await try_delete_command_message(message)
    await message.answer(phrases.REST_CANCELLED.format(user=name))
