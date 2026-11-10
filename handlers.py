import asyncio
import datetime
import logging
import math
import random
import re
import time
from datetime import timedelta, timezone

from aiogram import Router, F, Bot, types
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import Message

import phrases
from backup import send_backup
from config import (
    ADMIN_RIGHTS, LEVEL_ADMIN, LEVEL_HELPER, LEVEL_OWNER, MAX_ACTIVE_WARNS, MAX_ASSIGNABLE_LEVEL,
    WARN_COOLDOWN_SECONDS, get_storage_chat_id,
)
from db import Database
from utils import (
    answer_long, display, esc, format_datetime, format_date, get_args, get_chat_owner_id, is_group, is_number, kw,
    level_of, prepare_target, try_delete_command_message, get_reply_user, resolve_target,
)

router = Router()
router.message.filter(F.from_user)

TAG_MIN_LEVEL = LEVEL_HELPER
SAVE_MIN_LEVEL = LEVEL_OWNER
MAX_NAME_LEN = 32
MAX_RP_TEXT_LEN = 1000
MAX_TAG_LEN = 32

CALL_COOLDOWN_SECONDS = 120
CALL_BATCH = 50
MAX_CALL_MEMBERS = 500
MAX_CALL_TEXT_LEN = 500
CALL_EMOJIS = list("😀😎🤠🥳😺🐶🦊🐼🐸🐵🦁🐯🐰🐨🐙🦄🐝🦋🌸🌻🍀🌈⭐🔥💎🎈🎵🎲🚀🍕🍩🍉🍒🧩🎯🏆🌟💫🍄🐢🦉")
_last_call: dict[int, float] = {}

SYSTEM_COMMANDS = {
    "мут", "размут", "варн", "-варн", "бан", "модер", "актив", "рест", "-рест",
    "ник", "-ник", "тэг", "команда", "-команда", "команды", "save", "start", "калл", "помощь",
    "кто", "норма", "неактив", "чистка", "варны", "скажи", "ежедневка",
}

COMMAND_NAME_RE = re.compile(r"[\w-]{1,32}")
DURATION_RE = re.compile(r"(\d+)([мmчhдd])", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{(user|U|reply|r|random|rn)\}")

WARN_DURATION_RE = re.compile(r"([0-9]{1,4})([чднм])", re.IGNORECASE)
WARN_UNITS = {
    "ч": timedelta(hours=1),
    "д": timedelta(days=1),
    "н": timedelta(weeks=1),
    "м": timedelta(days=30),
}
MAX_WARN_DURATION = timedelta(days=365)
MAX_REASON_LEN = 200


def normalize_cmd_name(raw: str) -> str:
    return raw.strip().lstrip("+").lower()


@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message):
    await try_delete_command_message(message)
    await message.answer(phrases.START_MESSAGE)


# ---------- 1.1 КОМАНДА «варны» ----------

@router.message(Command("варны", ignore_case=True))
@router.message(kw("варны"))
async def cmd_warns_list(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return

    chat_id = message.chat.id
    raw_args = get_args(message)
    target, rest = await resolve_target(message, raw_args, db, bot)

    if target:
        details = await db.get_user_warn_details(chat_id, target.id)
        name = await display(db, chat_id, target)
        if not details:
            await message.reply(f"У пользователя {name} нет активных варнов.")
            return

        text = f"📋 <b>Список варнов {name}:</b>\n\n"
        for idx, w in enumerate(details, start=1):
            issued = format_datetime(w["issued_at"]) if w.get("issued_at") else "неизвестно"
            until = format_datetime(w["expires_at"])
            reason = esc(w["reason"]) if w.get("reason") else "без причины"
            issuer_id = w.get("issued_by")
            issuer_str = f"<code>{issuer_id}</code>" if issuer_id else "система"
            text += f"{idx}. Выдан: {issued} (кем: {issuer_str})\n   Действует до: {until}\n   Причина: {reason}\n"

        await message.reply(text)
    else:
        warned_users = await db.get_warned_users(chat_id)
        if not warned_users:
            await message.reply("🟢 В этом чате ни у кого нет активных варнов.")
            return

        text = "⚠️ <b>Список участников с активными варнами:</b>\n\n"
        for idx, (u_id, count) in enumerate(warned_users, start=1):
            name = esc(await db.get_display_name(chat_id, u_id))
            text += f"{idx}. {name} — {count}/3 варнов\n"

        await message.reply(text)


# ---------- 2.0 КОМАНДА «скажи» ----------

@router.message(Command("скажи", ignore_case=True))
@router.message(kw("скажи"))
async def cmd_say(message: Message, db: Database):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    text = get_args(message)
    if not text:
        return
    await try_delete_command_message(message)
    user_name = await display(db, message.chat.id, message.from_user)
    await message.answer(f"{user_name} говорит {esc(text)}")


# ---------- 3.0 УЛУЧШЕННЫЕ ТРИГГЕРЫ (3+ УРОВЕНЬ) ----------

def parse_rep_trigger_args(arg_str: str):
    arg_str = arg_str.strip()
    if not arg_str:
        return None, None
    tokens = arg_str.split()
    if len(tokens) < 2:
        return None, None
    delta_token = tokens[-1]
    if delta_token not in ("+", "-"):
        return None, None
    delta = 1 if delta_token == "+" else -1
    rest = " ".join(tokens[:-1]).strip()

    m = re.match(r"^\[(.*?)\]$", rest)
    if m:
        inner = m.group(1)
        phrases_list = [p.strip().lower() for p in inner.split(";") if p.strip()]
    else:
        if rest:
            phrases_list = [rest.strip().lower()]
        else:
            return None, None
    return phrases_list, delta


def parse_tabu_trigger_args(arg_str: str):
    arg_str = arg_str.strip()
    if not arg_str:
        return None, None
    if arg_str.startswith("["):
        end_bracket = arg_str.find("]")
        if end_bracket == -1:
            return None, None
        phrases_part = arg_str[1:end_bracket].strip()
        action_cmd = arg_str[end_bracket+1:].strip()
        phrases_list = [p.strip().lower() for p in phrases_part.split(";") if p.strip()]
        return phrases_list, action_cmd
    else:
        parts = arg_str.split(maxsplit=1)
        if len(parts) < 2:
            return None, None
        return [parts[0].strip().lower()], parts[1].strip()


@router.message(kw("+триггер"))
async def cmd_add_trigger(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_OWNER:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    raw = get_args(message)
    if raw.lower().startswith("репутация"):
        rest = raw[9:].strip()
        phrases_list, delta = parse_rep_trigger_args(rest)
        if not phrases_list or delta is None:
            await message.reply(phrases.TRIGGER_REP_USAGE)
            return
        sign = "+" if delta > 0 else ""
        for p in phrases_list:
            await db.add_rep_trigger(chat_id, p, delta)
        await message.reply(phrases.TRIGGER_REP_ADDED.format(phrase=esc(", ".join(phrases_list)), sign=sign))
        return

    if raw.lower().startswith("табу"):
        rest = raw[4:].strip()
        phrases_list, action_cmd = parse_tabu_trigger_args(rest)
        if not phrases_list or not action_cmd:
            await message.reply(phrases.TRIGGER_TABU_USAGE)
            return
        for p in phrases_list:
            await db.add_tabu_trigger(chat_id, p, action_cmd)
        await message.reply(phrases.TRIGGER_TABU_ADDED.format(count=len(phrases_list), cmd=esc(action_cmd)))
        return

    await message.reply(phrases.TRIGGER_REP_USAGE + "\n" + phrases.TRIGGER_TABU_USAGE)


@router.message(kw("-триггер"))
async def cmd_remove_trigger(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_OWNER:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    raw = get_args(message)
    if raw.lower().startswith("репутация"):
        phrase = raw[9:].strip().strip("[]").lower()
        if await db.remove_rep_trigger(chat_id, phrase):
            await message.reply(phrases.TRIGGER_REP_REMOVED.format(phrase=esc(phrase)))
        else:
            await message.reply(phrases.TRIGGER_NOT_FOUND)
        return

    if raw.lower().startswith("табу"):
        phrase = raw[4:].strip().strip("[]").lower()
        if await db.remove_tabu_trigger(chat_id, phrase):
            await message.reply(phrases.TRIGGER_TABU_REMOVED.format(phrase=esc(phrase)))
        else:
            await message.reply(phrases.TRIGGER_NOT_FOUND)
        return

    await message.reply(phrases.TRIGGER_REMOVE_REP_USAGE + "\n" + phrases.TRIGGER_REMOVE_TABU_USAGE)


# ---------- 4.0 КАССЕТЫ И ЕЖЕДНЕВКА ----------

@router.message(Command("ежедневка", ignore_case=True))
@router.message(kw("ежедневка"))
@router.message(kw("/ежедневка"))
async def cmd_daily(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    args = get_args(message).split()

    if args:
        if await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_OWNER:
            await message.reply(phrases.ERR_NO_PERMISSION)
            return

        token = args[0]
        if "-" in token:
            parts = token.split("-")
            if len(parts) == 2 and is_number(parts[0]) and is_number(parts[1]):
                d_min, d_max = int(parts[0]), int(parts[1])
                if d_min <= d_max and d_min >= 0:
                    await db.set_daily_range(chat_id, d_min, d_max)
                    await message.reply(f"🎰 Награда за ежедневку установлена в диапазоне: {d_min}-{d_max} кассет.")
                    return
        elif is_number(token):
            val = int(token)
            if val >= 0:
                await db.set_daily_range(chat_id, val, val)
                await message.reply(f"🎰 Награда за ежедневку установлена: {val} кассет.")
                return

        await message.reply("Структура: /ежедневка [число] или [минимум-максимум]")
        return

    now_gmt3 = datetime.datetime.now(timezone.utc) + timedelta(hours=3)
    today_str = now_gmt3.strftime("%Y-%m-%d")

    d_min, d_max = await db.get_daily_range(chat_id)
    reward = random.randint(d_min, d_max) if d_min <= d_max else d_min

    if await db.claim_daily(chat_id, message.from_user.id, today_str, reward):
        user_name = await display(db, chat_id, message.from_user)
        await message.reply(f"🎁 {user_name}, вы получили ежедневную награду: <b>{reward}</b> 📼 кассет!")
    else:
        await message.reply("⏳ Вы уже забирали ежедневную награду сегодня. Попробуйте после 00:00 (GMT+3)!")


@router.message(kw("+кассет"))
async def cmd_transfer_cassettes(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    raw_args = get_args(message)

    parts = raw_args.split()
    if not parts or not is_number(parts[0]):
        await message.reply("Структура: +кассет [число] [@username/ответом]")
        return
    amount = int(parts[0])
    if amount <= 0:
        await message.reply("Число должно быть больше 0.")
        return

    rest_args = " ".join(parts[1:])
    target, _ = await resolve_target(message, rest_args, db, bot)
    if not target:
        await message.reply(phrases.ERR_USER_NOT_FOUND)
        return
    if target.id == message.from_user.id:
        await message.reply("Нельзя передавать кассеты самому себе.")
        return
    if target.is_bot:
        await message.reply(phrases.ERR_BOT_TARGET)
        return

    if await db.transfer_cassettes(chat_id, message.from_user.id, target.id, amount):
        sender_name = await display(db, chat_id, message.from_user)
        target_name = await display(db, chat_id, target)
        await message.reply(f"📼 {sender_name} передал {amount} кассет участнику {target_name}.")
    else:
        await message.reply("У вас недостаточно кассет.")


@router.message(kw("+рест"))
async def cmd_buy_rest(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    price = await db.get_rest_price(chat_id)
    owner_id = await get_chat_owner_id(bot, chat_id)

    raw_args = get_args(message)
    target, _ = await resolve_target(message, raw_args, db, bot)
    if not target:
        target = message.from_user

    if target.is_bot:
        await message.reply(phrases.ERR_BOT_TARGET)
        return

    user_cassettes = await db.get_cassettes(chat_id, message.from_user.id)
    if user_cassettes < price:
        await message.reply(f"У вас недостаточно кассет. Цена реста (на 1 неделю): {price} 📼 (у вас: {user_cassettes} 📼).")
        return

    await db.add_cassettes(chat_id, message.from_user.id, -price)
    if owner_id:
        await db.add_cassettes(chat_id, owner_id, price)

    until = int(time.time() + 7 * 86400)
    await db.set_rest(chat_id, target.id, until)
    target_name = await display(db, chat_id, target)
    buyer_name = await display(db, chat_id, message.from_user)

    await message.reply(f"🛌 {buyer_name} купил рест для {target_name} за {price} 📼 кассет! Рест установлен до {format_date(until)}.")


@router.message(kw("-рест"))
async def cmd_set_rest_price(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    chat_id = message.chat.id
    raw_args = get_args(message)

    target, rest_str = await resolve_target(message, raw_args, db, bot)
    if target and not is_number(raw_args.split()[0] if raw_args else ""):
        if await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_OWNER:
            await message.reply(phrases.ERR_NO_PERMISSION)
            return
        name = esc(await db.get_display_name(chat_id, target.id, fallback=target.full_name))
        if not await db.clear_rest(chat_id, target.id):
            await message.reply(phrases.REST_NOT_ACTIVE.format(user=name))
            return
        await try_delete_command_message(message)
        await message.answer(phrases.REST_CANCELLED.format(user=name))
        return

    if await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_OWNER:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    tokens = raw_args.split()
    if len(tokens) == 1 and is_number(tokens[0]):
        price = int(tokens[0])
        await db.set_rest_price(chat_id, price)
        await message.reply(f"⚙️ Стоимость покупки реста установлена: {price} 📼 кассет.")
        return

    await message.reply("Структура команды:\n-рест [цена]\nили -рест [@username] для снятия реста")


@router.message(kw("+ник"))
async def cmd_set_rp_name(message: Message, db: Database):
    name = " ".join(get_args(message).split())
    if not name:
        await message.reply(phrases.USAGE_NICK)
        return
    if len(name) > MAX_NAME_LEN:
        await message.reply(phrases.ERR_TOO_LONG.format(limit=MAX_NAME_LEN))
        return
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, name)
    await message.answer(phrases.RP_NAME_SET.format(name=esc(name)))


@router.message(Command("ник", ignore_case=True))
@router.message(kw("-ник"))
async def cmd_reset_rp_name(message: Message, db: Database):
    if get_args(message):
        await message.reply(phrases.USAGE_NICK_RESET)
        return
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, "")
    await message.answer(phrases.RP_NAME_RESET)


@router.message(kw("тэг"))
async def cmd_set_tag(message: Message, db: Database, bot: Bot):
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < TAG_MIN_LEVEL:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    args = get_args(message)
    reply_user = get_reply_user(message)
    if reply_user:
        tag_text, target_id = " ".join(args.split()), reply_user.id
    else:
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].startswith("@") or len(parts[0]) < 2:
            await message.reply(phrases.USAGE_TAG)
            return
        tag_text = " ".join(parts[1].split())
        target_id = await db.get_user_id_by_username(chat_id, parts[0])
        if not target_id:
            await message.reply(phrases.ERR_USER_NOT_FOUND)
            return

    if not tag_text:
        await message.reply(phrases.USAGE_TAG)
        return
    if len(tag_text) > MAX_TAG_LEN:
        await message.reply(phrases.ERR_TOO_LONG.format(limit=MAX_TAG_LEN))
        return

    if reply_user and not reply_user.is_bot:
        await db.touch_user(chat_id, reply_user.id, reply_user.username, reply_user.first_name)
    await try_delete_command_message(message)
    await db.set_tag(chat_id, target_id, tag_text)
    target_display = esc(await db.get_display_name(chat_id, target_id))
    await message.answer(phrases.TAG_SET.format(user=target_display, tag=esc(tag_text)))


@router.message(kw("+команда"))
async def cmd_create_rp_command(message: Message, db: Database):
    parts = get_args(message).split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(phrases.USAGE_COMMAND_CREATE)
        return
    cmd_name = normalize_cmd_name(parts[0])
    cmd_text = parts[1].strip()

    if not COMMAND_NAME_RE.fullmatch(cmd_name):
        await message.reply(phrases.ERR_BAD_COMMAND_NAME)
        return
    if cmd_name in SYSTEM_COMMANDS:
        await message.reply(phrases.ERR_SYSTEM_COMMAND)
        return
    if len(cmd_text) > MAX_RP_TEXT_LEN:
        await message.reply(phrases.ERR_TOO_LONG.format(limit=MAX_RP_TEXT_LEN))
        return

    if not await db.add_rp_command(message.chat.id, cmd_name, cmd_text, message.from_user.id):
        await message.reply(phrases.ERR_COMMAND_EXISTS)
        return
    await try_delete_command_message(message)
    await message.answer(phrases.COMMAND_CREATED.format(name=esc(cmd_name)))


@router.message(Command("команды", ignore_case=True))
@router.message(kw("команды"))
async def cmd_list_rp_commands(message: Message, db: Database):
    if get_args(message):
        await message.reply(phrases.USAGE_COMMANDS)
        return
    await try_delete_command_message(message)
    commands = await db.get_all_rp_commands(message.chat.id)
    if not commands:
        await message.answer(phrases.COMMANDS_EMPTY)
        return
    text = phrases.COMMANDS_LIST_HEADER
    for (name,) in commands:
        text += phrases.COMMANDS_LIST_ITEM.format(name=esc(name))
    await answer_long(message, text)


@router.message(kw("-команда"))
async def cmd_delete_rp_command(message: Message, db: Database, bot: Bot):
    parts = get_args(message).split()
    if len(parts) != 1:
        await message.reply(phrases.USAGE_COMMAND_DELETE)
        return
    chat_id = message.chat.id
    cmd_name = normalize_cmd_name(parts[0])

    exists, author_id = await db.get_rp_command_info(chat_id, cmd_name)
    if not exists:
        await message.reply(phrases.ERR_COMMAND_NOT_FOUND)
        return

    is_author = author_id is not None and author_id == message.from_user.id
    if not is_author and await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_HELPER:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    await try_delete_command_message(message)
    await db.delete_rp_command(chat_id, cmd_name)
    await message.answer(phrases.COMMAND_DELETED.format(name=esc(cmd_name)))


@router.message(Command("помощь", ignore_case=True))
@router.message(kw("помощь"))
async def cmd_help(message: Message):
    if get_args(message):
        await message.reply(phrases.USAGE_HELP)
        return
    await try_delete_command_message(message)
    await message.answer(phrases.HELP_TEXT)


def parse_mute_args(args: str | None):
    if not args:
        return None, "навсегда", "Нарушение"
    first, _, rest = args.strip().partition(" ")
    m = DURATION_RE.fullmatch(first)
    if not m:
        return None, "навсегда", args.strip()
    value, unit = int(m.group(1)), m.group(2).lower()
    if unit in ("м", "m"):
        delta = timedelta(minutes=value)
    elif unit in ("ч", "h"):
        delta = timedelta(hours=value)
    else:
        delta = timedelta(days=value)
    return delta, first, rest.strip() or "Нарушение"


def parse_warn_duration_or_date(token: str) -> timedelta | None:
    match = WARN_DURATION_RE.fullmatch(token)
    if match:
        val = int(match.group(1))
        if val > 0:
            return WARN_UNITS[match.group(2).lower()] * val

    now_dt = datetime.datetime.now()
    target_dt = None

    m1 = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", token)
    if m1:
        day, month, year = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
        try:
            target_dt = datetime.datetime(year, month, day, 23, 59, 59)
        except ValueError:
            return None

    m2 = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", token)
    if not target_dt and m2:
        day, month = int(m2.group(1)), int(m2.group(2))
        try:
            target_dt = datetime.datetime(now_dt.year, month, day, 23, 59, 59)
        except ValueError:
            return None

    m3 = re.fullmatch(r"(\d{1,2})", token)
    if not target_dt and m3:
        day = int(m3.group(1))
        try:
            target_dt = datetime.datetime(now_dt.year, now_dt.month, day, 23, 59, 59)
        except ValueError:
            return None

    if target_dt:
        diff = target_dt - now_dt
        if diff.total_seconds() > 0:
            return diff

    return None


@router.message(Command("мут", ignore_case=True))
async def cmd_mute(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_HELPER,
                                    usage=phrases.USAGE_MUTE)
    if not prepared:
        return
    target, rest = prepared
    until, duration_text, reason = parse_mute_args(rest)
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except Exception as e:
        await message.reply(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    await try_delete_command_message(message)
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.MUTE_SUCCESS.format(
        user=name, duration=esc(duration_text), reason=esc(reason)))


@router.message(Command("размут", ignore_case=True))
async def cmd_unmute(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_HELPER, hierarchy=False,
                                    usage=phrases.USAGE_UNMUTE)
    if not prepared:
        return
    target, _ = prepared
    try:
        chat = await bot.get_chat(message.chat.id)
        permissions = chat.permissions or types.ChatPermissions(
            can_send_messages=True, can_send_audios=True, can_send_documents=True,
            can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
            can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await bot.restrict_chat_member(message.chat.id, target.id, permissions=permissions)
    except Exception as e:
        await message.reply(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    await try_delete_command_message(message)
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.UNMUTE_SUCCESS.format(user=name))


@router.message(Command("варн", ignore_case=True))
@router.message(kw("варн"))
async def cmd_warn(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN,
                                    usage=phrases.USAGE_WARN_LINE)
    if not prepared:
        return
    target, rest = prepared

    parts = rest.split(maxsplit=1)
    duration = parse_warn_duration_or_date(parts[0]) if parts else None
    if duration is None:
        await message.reply(phrases.USAGE_WARN)
        return
    if duration > MAX_WARN_DURATION:
        await message.reply(phrases.ERR_WARN_TOO_LONG.format(days=MAX_WARN_DURATION.days))
        return
    reason = " ".join(parts[1].split()) if len(parts) > 1 else ""
    if len(reason) > MAX_REASON_LEN:
        await message.reply(phrases.ERR_TOO_LONG.format(limit=MAX_REASON_LEN))
        return

    chat_id = message.chat.id
    name = await display(db, chat_id, target)
    now = int(time.time())

    last_warn = await db.get_last_warn_time(chat_id, target.id)
    if last_warn and now - last_warn < WARN_COOLDOWN_SECONDS:
        minutes_left = math.ceil((WARN_COOLDOWN_SECONDS - (now - last_warn)) / 60)
        await message.reply(phrases.ERR_WARN_COOLDOWN.format(user=name, minutes=minutes_left))
        return

    if await db.get_total_warns(chat_id, target.id) >= MAX_ACTIVE_WARNS:
        try:
            await bot.ban_chat_member(chat_id, target.id)
        except Exception as e:
            await message.reply(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
            return
        await db.reset_warns(chat_id, target.id)
        await try_delete_command_message(message)
        await message.answer(phrases.WARN_LIMIT_REACHED.format(user=name))
        return

    expires_at = now + int(duration.total_seconds())
    count = await db.add_temp_warn(chat_id, target.id, expires_at,
                                   issued_by=message.from_user.id, reason=reason or None)
    await try_delete_command_message(message)
    await message.answer(phrases.WARN_SUCCESS.format(
        user=name, count=count, limit=MAX_ACTIVE_WARNS + 1, until=format_datetime(expires_at),
        reason=phrases.WARN_REASON.format(reason=esc(reason)) if reason else ""))


@router.message(kw("-варн"))
async def cmd_unwarn(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN,
                                    hierarchy=False, usage=phrases.USAGE_UNWARN_LINE)
    if not prepared:
        return
    target, rest = prepared

    tokens = rest.split()
    if len(tokens) > 1 or (tokens and (not is_number(tokens[0]) or int(tokens[0]) < 1)):
        await message.reply(phrases.USAGE_UNWARN)
        return
    amount = min(int(tokens[0]), 99) if tokens else 1

    chat_id = message.chat.id
    name = await display(db, chat_id, target)
    before = await db.get_total_warns(chat_id, target.id)
    if before == 0:
        await message.reply(phrases.UNWARN_NONE.format(user=name))
        return
    after = await db.decrease_warn(chat_id, target.id, amount)
    await try_delete_command_message(message)
    await message.answer(phrases.UNWARN_SUCCESS.format(user=name, count=before - after, total=after))


@router.message(Command("бан", ignore_case=True))
async def cmd_ban(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN, usage=phrases.USAGE_BAN)
    if not prepared:
        return
    target, rest = prepared
    reason = rest or "Нарушение"
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
    except Exception as e:
        await message.reply(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    await try_delete_command_message(message)
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.BAN_SUCCESS.format(user=name, reason=esc(reason)))


async def sync_telegram_admin(bot: Bot, chat_id: int, user_id: int, old_level: int, new_level: int) -> str:
    try:
        status = (await bot.get_chat_member(chat_id, user_id)).status
        if new_level == LEVEL_ADMIN and status not in ("administrator", "creator"):
            await bot.promote_chat_member(chat_id, user_id, **ADMIN_RIGHTS)
            return phrases.MODER_TG_PROMOTED
        if old_level == LEVEL_ADMIN and new_level < LEVEL_ADMIN and status == "administrator":
            await bot.promote_chat_member(chat_id, user_id, **{right: False for right in ADMIN_RIGHTS})
            return phrases.MODER_TG_DEMOTED
    except Exception as e:
        return phrases.MODER_TG_FAILED.format(error=esc(e))
    return ""


@router.message(Command("модер", ignore_case=True))
async def cmd_moder(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_OWNER,
                                    usage=phrases.USAGE_MODER_LINE)
    if not prepared:
        return
    target, rest = prepared
    chat_id = message.chat.id
    tokens = rest.split()
    if len(tokens) != 1 or not is_number(tokens[0]):
        await message.reply(phrases.USAGE_MODER.format(max=MAX_ASSIGNABLE_LEVEL))
        return
    new_level = int(tokens[0])
    if new_level > MAX_ASSIGNABLE_LEVEL:
        await message.reply(phrases.ERR_BAD_LEVEL)
        return
    if target.is_bot:
        await message.reply(phrases.ERR_BOT_TARGET)
        return
    if target.id == await get_chat_owner_id(bot, chat_id):
        await message.reply(phrases.ERR_OWNER_FIXED)
        return

    old_level = await db.get_stored_moderator_level(chat_id, target.id)
    await db.set_moderator_level(chat_id, target.id, new_level)
    tg_note = await sync_telegram_admin(bot, chat_id, target.id, old_level, new_level)
    await try_delete_command_message(message)
    name = await display(db, chat_id, target)
    text = phrases.MODER_SET.format(
        user=name, level=new_level, role=phrases.MOD_STATUS_NAMES.get(new_level, phrases.STATUS_MEMBER))
    await message.answer(text + (f"\n{tg_note}" if tg_note else ""))


@router.message(Command("save", ignore_case=True))
async def cmd_save(message: Message, db: Database, bot: Bot):
    await try_delete_command_message(message)
    storage_id = get_storage_chat_id()

    if await level_of(db, bot, message.chat.id, message.from_user.id) < SAVE_MIN_LEVEL:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return
    if not storage_id or message.chat.id != storage_id:
        await message.answer(phrases.ERR_NOT_STORAGE_CHAT.format(
            chat_id=message.chat.id, storage_id=storage_id or "не задан"))
        return

    try:
        await send_backup(bot, db, storage_id, caption=phrases.BACKUP_SUCCESS)
    except Exception as e:
        logging.exception("Ошибка ручного бэкапа")
        await message.answer(phrases.ERR_BACKUP_FAILED.format(error=esc(e)))


@router.message(Command("калл", ignore_case=True))
@router.message(kw("калл"))
async def cmd_call_everyone(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return
    text = " ".join(get_args(message).split())
    if not text:
        await message.reply(phrases.USAGE_CALL)
        return
    if len(text) > MAX_CALL_TEXT_LEN:
        await message.reply(phrases.ERR_TOO_LONG.format(limit=MAX_CALL_TEXT_LEN))
        return

    chat_id = message.chat.id
    level = await level_of(db, bot, chat_id, message.from_user.id)
    wait = CALL_COOLDOWN_SECONDS - (time.monotonic() - _last_call.get(chat_id, -1e9))
    if level < LEVEL_HELPER and wait > 0:
        await message.reply(phrases.ERR_CALL_COOLDOWN.format(
            minutes=CALL_COOLDOWN_SECONDS // 60 or 1, seconds=int(wait) + 1))
        return

    member_ids = await db.get_member_ids(chat_id, message.from_user.id, MAX_CALL_MEMBERS)
    try:
        for admin in await bot.get_chat_administrators(chat_id):
            u = admin.user
            if not u.is_bot and u.id != message.from_user.id and u.id not in member_ids:
                member_ids.append(u.id)
    except Exception as e:
        logging.debug("get_chat_administrators не удался: %s", e)
    member_ids = member_ids[:MAX_CALL_MEMBERS]
    if not member_ids:
        await message.reply(phrases.ERR_CALL_NOBODY)
        return

    _last_call[chat_id] = time.monotonic()
    await try_delete_command_message(message)
    caller = await display(db, chat_id, message.from_user)
    header = phrases.CALL_HEADER.format(user=caller, text=esc(text))

    replied = message.reply_to_message
    reply_params = None
    if replied and not replied.forum_topic_created:
        reply_params = types.ReplyParameters(message_id=replied.message_id, allow_sending_without_reply=True)

    for i in range(0, len(member_ids), CALL_BATCH):
        mentions = "".join(
            f'<a href="tg://user?id={uid}">{random.choice(CALL_EMOJIS)}</a>'
            for uid in member_ids[i:i + CALL_BATCH])
        body = f"{header}\n\n{mentions}" if i == 0 else mentions
        extra = {"reply_parameters": reply_params} if (i == 0 and reply_params) else {}
        try:
            try:
                await message.answer(body, **extra)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await message.answer(body, **extra)
        except Exception:
            logging.exception("Не удалось отправить пачку упоминаний")
            break
        await asyncio.sleep(1)


# ---------- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ, ТРИГГЕРОВ И РП-КОМАНД ----------

@router.message(F.text)
async def handle_text_and_triggers(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    raw_text = message.text.strip()
    if not raw_text:
        return

    chat_id = message.chat.id
    msg_lower = raw_text.lower()

    # 3.2 ТАБУ-ТРИГГЕРЫ (работает при наличии текста в сообщении)
    tabu_triggers = await db.get_tabu_triggers(chat_id)
    for phrase, action_cmd in tabu_triggers:
        if phrase in msg_lower:
            await try_delete_command_message(message)

            sender_name = await display(db, chat_id, message.from_user)
            cmd_to_run = action_cmd.replace("{User}", sender_name).replace("{user}", sender_name)

            if cmd_to_run.lower().startswith("скажи "):
                say_text = cmd_to_run[6:].strip()
                await message.answer(f"{say_text}")
            elif cmd_to_run.lower().startswith("варн"):
                parts = cmd_to_run.split(maxsplit=1)
                warn_args = parts[1] if len(parts) > 1 else "1д"
                duration = parse_warn_duration_or_date(warn_args.split()[0]) or timedelta(days=1)
                expires_at = int(time.time() + duration.total_seconds())
                count = await db.add_temp_warn(chat_id, message.from_user.id, expires_at, reason="табу-слово")
                await message.answer(phrases.TABU_WARN_NOTICE.format(user=sender_name, count=count))
            return

    # 3.1 ТРИГГЕРЫ РЕПУТАЦИИ (полное совпадение слов / фраз при ответе на сообщение)
    reply_user = get_reply_user(message)
    if reply_user and reply_user.id != message.from_user.id and not reply_user.is_bot:
        rep_triggers = await db.get_rep_triggers(chat_id)
        words = re.findall(r'\b\w+\b', msg_lower)
        for phrase, delta in rep_triggers:
            matched = False
            if " " in phrase:
                if phrase in msg_lower:
                    matched = True
            else:
                if phrase in words:
                    matched = True

            if matched:
                await db.change_reputation(chat_id, reply_user.id, delta)
                sign = "+" if delta > 0 else ""
                target_name = await display(db, chat_id, reply_user)
                await message.answer(phrases.REP_CHANGED_NOTICE.format(user=target_name, sign=sign, delta=delta))
                break

    # РП-КОМАНДЫ
    if raw_text.startswith("/"):
        return

    first_word = raw_text.split(maxsplit=1)[0]
    cmd_candidate = (first_word[1:] if first_word.startswith("+") else first_word).lower()
    template = await db.get_rp_command(chat_id, cmd_candidate) if cmd_candidate else None

    if template:
        if reply_user and reply_user.id == bot.id:
            await try_delete_command_message(message)
            await message.answer(phrases.ERR_BOT_TARGET)
            return
        if not reply_user and re.search(r"\{(reply|r)\}", template):
            await message.answer(phrases.ERR_NEED_REPLY)
            return

        await try_delete_command_message(message)
        sender_name = await display(db, chat_id, message.from_user)
        reply_name = await display(db, chat_id, reply_user) if reply_user else ""
        random_id = await db.get_random_user(chat_id)
        random_name = esc(await db.get_display_name(chat_id, random_id)) if random_id else "Кто-то"

        values = {
            "user": sender_name, "U": sender_name,
            "reply": reply_name, "r": reply_name,
            "random": random_name, "rn": random_name,
        }
        text = PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], esc(template))
        await message.answer(text)
        return
