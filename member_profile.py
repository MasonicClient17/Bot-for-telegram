"""Профили («кто я» / «кто ты»), недельная норма (/норма) и список неактивных (/неактив)."""
from aiogram import Bot, Router, types
from aiogram.filters import Command
from aiogram.types import Message

import phrases
from config import CREATOR_LEVEL
from db import Database, pick_display_name
from quota import current_week_start_ts
from utils import (
    answer_long, chat_quota, esc, format_date, get_args, is_group, is_number, kw_phrase,
    level_of, resolve_target, try_delete_command_message,
)

profile_router = Router()

NORM_MIN_LEVEL = 2          # /норма и /неактив — модераторы 2+
MAX_WEEKLY_QUOTA = 100_000
INACTIVE_LIST_LIMIT = 50


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


def status_title(level: int, is_chat_owner: bool) -> str:
    if is_chat_owner or level >= CREATOR_LEVEL:
        return phrases.STATUS_OWNER
    if level <= 0:
        return phrases.STATUS_MEMBER
    names = phrases.MOD_STATUS_NAMES
    return names.get(level, names[max(names)])


def joined_text(row: dict) -> str:
    # Telegram не отдаёт ботам дату вступления: точная известна, только если бот видел вступление
    if row["joined_at"]:
        return format_date(row["joined_at"])
    if row["first_seen"]:
        return "≈" + format_date(row["first_seen"])
    return phrases.JOINED_UNKNOWN


async def is_chat_owner(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status == "creator"


async def build_profile(db: Database, bot: Bot, chat_id: int, user: types.User) -> str:
    await db.touch_user(chat_id, user.id, user.username, user.first_name)  # гарантирует строку в БД
    row = await db.get_profile(chat_id, user.id)
    quota = await chat_quota(db, chat_id)
    level = await level_of(db, chat_id, user.id)
    name = pick_display_name(row["rp_name"], row["tag"], row["first_name"], row["username"], user.full_name)
    return phrases.PROFILE_TEMPLATE.format(
        name=esc(name),
        joined=esc(joined_text(row)),
        count=row["week_count"],
        emoji=activity_emoji(row["week_count"], quota),
        status=esc(status_title(level, await is_chat_owner(bot, chat_id, user.id))),
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
async def cmd_set_quota(message: Message, db: Database):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, chat_id, message.from_user.id) < NORM_MIN_LEVEL:
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
async def cmd_inactive(message: Message, db: Database):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, chat_id, message.from_user.id) < NORM_MIN_LEVEL:
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
    for idx, row in enumerate(rows, start=1):
        name = pick_display_name(row["rp_name"], row["tag"], row["first_name"], row["username"],
                                 str(row["user_id"]))
        text += phrases.INACTIVE_LINE.format(
            index=idx, name=esc(name), count=row["week_count"], quota=quota,
            emoji=activity_emoji(row["week_count"], quota))
    if total > len(rows):
        text += phrases.INACTIVE_MORE.format(n=total - len(rows))
    await answer_long(message, text)
