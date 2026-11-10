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

NORM_MIN_LEVEL = LEVEL_ADMIN
REST_MIN_LEVEL = LEVEL_OWNER
MAX_WEEKLY_QUOTA = 100_000
INACTIVE_LIST_LIMIT = 50

REST_RE = re.compile(r"([0-9]{0,3})([нм])", re.IGNORECASE)
REST_UNITS = {"н": timedelta(weeks=1), "м": timedelta(days=30)}
REST_DEFAULT = timedelta(weeks=1)
MAX_REST = timedelta(days=365)

def activity_emoji(count: int, quota: int) -> str:
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
    if level <= 0:
        return phrases.STATUS_MEMBER
    return phrases.MOD_STATUS_NAMES[min(level, LEVEL_OWNER)]

def joined_text(row: dict) -> str:
    if row["joined_at"]:
        return format_date(row["joined_at"])
    if row["first_seen"]:
        return "≈" + format_date(row["first_seen"])
    return phrases.JOINED_UNKNOWN

async def profile_status(db: Database, bot: Bot, chat_id: int, user_id: int) -> str:
    if user_id == await get_chat_owner_id(bot, chat_id):
        return status_title(LEVEL_OWNER)
    return status_title(await db.get_stored_moderator_level(chat_id, user_id))

async def build_profile(db: Database, bot: Bot, chat_id: int, user: types.User) -> str:
    await db.touch_user(chat_id, user.id, user.username, user.first_name)
    row = await db.get_profile(chat_id, user.id)
    quota = await chat_quota(db, chat_id)
    name = pick_display_name(row["rp_name"], row["tag"], row["first_name"], row["username"], user.full_name)
    
    # Краткое количество варнов (1.1) и кассеты (4.6)
    warns_count = await db.get_total_warns(chat_id, user.id)
    cassettes_count = row.get("cassettes", 0)

    template = getattr(phrases, "PROFILE_TEMPLATE", 
                       "👤 <b>{name}</b>\n📅 В чате с: {joined}\n💬 Сообщений: {count} {emoji}\n🛡 Статус: {status}\n⭐ Репутация: {reputation} (варнов: {warns})\n📼 Кассеты: {cassettes}")
    
    # Если в phrases.PROFILE_TEMPLATE есть [WIP], заменяем на cassettes или форматируем с кассетами и варнами
    formatted_template = template
    if "{warns}" not in formatted_template and "⭐ Репутация: {reputation}" in formatted_template:
        formatted_template = formatted_template.replace("⭐ Репутация: {reputation}", "⭐ Репутация: {reputation} | 🛡 Варны: {warns}")
    if "[WIP]" in formatted_template:
        formatted_template = formatted_template.replace("[WIP]", str(cassettes_count))
    elif "{cassettes}" not in formatted_template:
        formatted_template += "\n📼 Кассеты: {cassettes}"

    try:
        return formatted_template.format(
            name=esc(name),
            joined=esc(joined_text(row)),
            count=row["week_count"],
            emoji=activity_emoji(row["week_count"], quota),
            status=esc(await profile_status(db, bot, chat_id, user.id)),
            reputation=row["reputation"],
            warns=warns_count,
            cassettes=cassettes_count,
        )
    except Exception:
        # Запасной вариант рендеринга профиля
        return (f"👤 <b>{esc(name)}</b>\n"
                f"📅 В чате с: {esc(joined_text(row))}\n"
                f"💬 Сообщений: {row['week_count']} {activity_emoji(row['week_count'], quota)}\n"
                f"🛡 Статус: {esc(await profile_status(db, bot, chat_id, user.id))}\n"
                f"⭐ Репутация: {row['reputation']} | 🛡 Варны: {warns_count}\n"
                f"📼 Кассеты: {cassettes_count}")

async def send_profile(message: Message, user: types.User, db: Database, bot: Bot):
    if user.is_bot:
        await message.reply(phrases.ERR_PROFILE_BOT)
        return
    await message.reply(await build_profile(db, bot, message.chat.id, user))

@profile_router.message(Command("актив", ignore_case=True))
@profile_router.message(kw("актив"))
async def cmd_active(message: Message, db: Database):
    parts = get_args(message).split()
    if len(parts) > 1 or (parts and not is_number(parts[0])):
        await message.reply(phrases.USAGE_ACTIVE)
        return
    await try_delete_command_message(message)
    chat_id = message.chat.id
    total_users = await db.get_total_users_count(chat_id)
    if total_users == 0:
        await message.answer(phrases.EMPTY_ACTIVITY)
        return

    limit = 20
    total_pages = (total_users + limit - 1) // limit
    page = min(max(1, int(parts[0]) if parts else 1), total_pages)
    offset = (page - 1) * limit
    quota = await chat_quota(db, chat_id)

    text = phrases.ACTIVITY_HEADER.format(page=page, total=total_pages, quota=quota)
    for idx, (user_id, week_count, total_count) in enumerate(
            await db.get_top_users(chat_id, limit, offset), start=offset + 1):
        name = esc(await db.get_display_name(chat_id, user_id))
        text += phrases.ACTIVITY_LINE.format(
            index=idx, name=name, week=week_count, emoji=activity_emoji(week_count, quota), total=total_count)
    await message.answer(text)

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

def parse_rest_duration(token: str) -> timedelta | None:
    match = REST_RE.fullmatch(token)
    if not match:
        return None
    number = int(match.group(1)) if match.group(1) else 1
    if number == 0:
        return None
    return REST_UNITS[match.group(2).lower()] * number

@profile_router.message(Command("рест", ignore_case=True))
async def cmd_rest(message: Message, db: Database, bot: Bot):
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
        
