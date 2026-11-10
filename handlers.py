import asyncio
import logging
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone

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
    answer_long, display, esc, format_datetime, get_args, get_chat_owner_id, is_group, is_number, kw,
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
    "кто", "норма", "неактив", "чистка", "варны", "скажи", "+триггер", "+кассет", "/ежедневка", "ежедневка",
}

COMMAND_NAME_RE = re.compile(r"[\w-]{1,32}")
DURATION_RE = re.compile(r"(\d+)([мmчhдd])", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{(user|U|reply|r|random|rn)\}")

def normalize_cmd_name(raw: str) -> str:
    return raw.strip().lstrip("+").lower()

@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message):
    await try_delete_command_message(message)
    await message.answer(getattr(phrases, "START_MESSAGE", "Привет! Бот запущен."))

@router.message(kw("+ник"))
async def cmd_set_rp_name(message: Message, db: Database):
    name = " ".join(get_args(message).split())
    if not name:
        await message.reply(getattr(phrases, "USAGE_NICK", "Использование: +ник [имя]"))
        return
    if len(name) > MAX_NAME_LEN:
        await message.reply(getattr(phrases, "ERR_TOO_LONG", "Слишком длинный текст").format(limit=MAX_NAME_LEN))
        return
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, name)
    await message.answer(getattr(phrases, "RP_NAME_SET", "РП-ник установлен: {name}").format(name=esc(name)))

@router.message(Command("ник", ignore_case=True))
@router.message(kw("-ник"))
async def cmd_reset_rp_name(message: Message, db: Database):
    if get_args(message):
        await message.reply(getattr(phrases, "USAGE_NICK_RESET", "Использование: -ник"))
        return
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, "")
    await message.answer(getattr(phrases, "RP_NAME_RESET", "РП-ник сброшен."))

@router.message(kw("тэг"))
async def cmd_set_tag(message: Message, db: Database, bot: Bot):
    chat_id = message.chat.id
    if await level_of(db, bot, chat_id, message.from_user.id) < TAG_MIN_LEVEL:
        await message.reply(getattr(phrases, "ERR_NO_PERMISSION", "Нет прав."))
        return
    args = get_args(message)
    reply_user = get_reply_user(message)
    if reply_user:
        tag_text, target_id = " ".join(args.split()), reply_user.id
    else:
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].startswith("@") or len(parts[0]) < 2:
            await message.reply(getattr(phrases, "USAGE_TAG", "Использование: тэг @user [текст]"))
            return
        tag_text = " ".join(parts[1].split())
        target_id = await db.get_user_id_by_username(chat_id, parts[0])
        if not target_id:
            await message.reply(getattr(phrases, "ERR_USER_NOT_FOUND", "Пользователь не найден."))
            return
    if not tag_text or len(tag_text) > MAX_TAG_LEN:
        await message.reply(getattr(phrases, "ERR_TOO_LONG", "Слишком длинный текст").format(limit=MAX_TAG_LEN))
        return
    if reply_user and not reply_user.is_bot:
        await db.touch_user(chat_id, reply_user.id, reply_user.username, reply_user.first_name)
    await try_delete_command_message(message)
    await db.set_tag(chat_id, target_id, tag_text)
    target_display = esc(await db.get_display_name(chat_id, target_id))
    await message.answer(getattr(phrases, "TAG_SET", "Тэг установлен для {user}: {tag}").format(user=target_display, tag=esc(tag_text)))

@router.message(kw("+команда"))
async def cmd_create_rp_command(message: Message, db: Database):
    parts = get_args(message).split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(getattr(phrases, "USAGE_COMMAND_CREATE", "Использование: +команда [имя] [текст]"))
        return
    cmd_name = normalize_cmd_name(parts[0])
    cmd_text = parts[1].strip()
    if not COMMAND_NAME_RE.fullmatch(cmd_name) or cmd_name in SYSTEM_COMMANDS:
        await message.reply(getattr(phrases, "ERR_BAD_COMMAND_NAME", "Неверное имя команды"))
        return
    if len(cmd_text) > MAX_RP_TEXT_LEN:
        await message.reply(getattr(phrases, "ERR_TOO_LONG", "Слишком длинный текст").format(limit=MAX_RP_TEXT_LEN))
        return
    if not await db.add_rp_command(message.chat.id, cmd_name, cmd_text, message.from_user.id):
        await message.reply(getattr(phrases, "ERR_COMMAND_EXISTS", "Команда уже существует"))
        return
    await try_delete_command_message(message)
    await message.answer(getattr(phrases, "COMMAND_CREATED", "Команда {name} создана").format(name=esc(cmd_name)))

@router.message(Command("команды", ignore_case=True))
@router.message(kw("команды"))
async def cmd_list_rp_commands(message: Message, db: Database):
    if get_args(message):
        await message.reply(getattr(phrases, "USAGE_COMMANDS", "Использование: команды"))
        return
    await try_delete_command_message(message)
    commands = await db.get_all_rp_commands(message.chat.id)
    if not commands:
        await message.answer(getattr(phrases, "COMMANDS_EMPTY", "Нет РП-команд."))
        return
    text = getattr(phrases, "COMMANDS_LIST_HEADER", "Список команд:\n")
    for (name,) in commands:
        text += getattr(phrases, "COMMANDS_LIST_ITEM", "- {name}\n").format(name=esc(name))
    await answer_long(message, text)

@router.message(kw("-команда"))
async def cmd_delete_rp_command(message: Message, db: Database, bot: Bot):
    parts = get_args(message).split()
    if len(parts) != 1:
        await message.reply(getattr(phrases, "USAGE_COMMAND_DELETE", "Использование: -команда [имя]"))
        return
    chat_id = message.chat.id
    cmd_name = normalize_cmd_name(parts[0])
    exists, author_id = await db.get_rp_command_info(chat_id, cmd_name)
    if not exists:
        await message.reply(getattr(phrases, "ERR_COMMAND_NOT_FOUND", "Команда не найдена"))
        return
    is_author = author_id is not None and author_id == message.from_user.id
    if not is_author and await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_HELPER:
        await message.reply(getattr(phrases, "ERR_NO_PERMISSION", "Нет прав."))
        return
    await try_delete_command_message(message)
    await db.delete_rp_command(chat_id, cmd_name)
    await message.answer(getattr(phrases, "COMMAND_DELETED", "Команда {name} удалена").format(name=esc(cmd_name)))

@router.message(Command("помощь", ignore_case=True))
@router.message(kw("помощь"))
async def cmd_help(message: Message):
    if get_args(message):
        await message.reply("Использование: помощь")
        return
    await try_delete_command_message(message)
    await message.answer(getattr(phrases, "HELP_TEXT", "Справка по боту."))

WARN_DURATION_RE = re.compile(r"([0-9]{1,4})([чднм])", re.IGNORECASE)
WARN_UNITS = {
    "ч": timedelta(hours=1),
    "д": timedelta(days=1),
    "н": timedelta(weeks=1),
    "м": timedelta(days=30),
}
MAX_WARN_DURATION = timedelta(days=365)
MAX_REASON_LEN = 200

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

def parse_warn_duration_or_date(token: str) -> timedelta | datetime | None:
    """Парсит относительный срок (2д, 1н) или абсолютную дату (ДД.ММ.ГГГГ, ДД.ММ, ДД)."""
    # 1. Относительный срок
    match = WARN_DURATION_RE.fullmatch(token)
    if match:
        value = int(match.group(1))
        if value == 0:
            return None
        return WARN_UNITS[match.group(2).lower()] * value

    # 2. Абсолютная дата (ДД.ММ.ГГГГ, ДД.ММ, ДД)
    now = datetime.now()
    parts = token.split(".")
    try:
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year, month, day, 23, 59, 59)
        elif len(parts) == 2:
            day, month = int(parts[0]), int(parts[1])
            return datetime(now.year, month, day, 23, 59, 59)
        elif len(parts) == 1 and parts[0].isdigit():
            day = int(parts[0])
            return datetime(now.year, now.month, day, 23, 59, 59)
    except ValueError:
        return None
    return None

@router.message(Command("мут", ignore_case=True))
async def cmd_mute(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_HELPER,
                                    usage=getattr(phrases, "USAGE_MUTE", "Использование мута"))
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
        await message.reply(getattr(phrases, "ERR_ACTION_FAILED", "Ошибка: {error}").format(error=esc(e)))
        return
    await try_delete_command_message(message)
    name = await display(db, message.chat.id, target)
    await message.answer(getattr(phrases, "MUTE_SUCCESS", "{user} в муте").format(
        user=name, duration=esc(duration_text), reason=esc(reason)))

@router.message(Command("размут", ignore_case=True))
async def cmd_unmute(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_HELPER, hierarchy=False,
                                    usage=getattr(phrases, "USAGE_UNMUTE", "Использование размута"))
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
        await message.reply(getattr(phrases, "ERR_ACTION_FAILED", "Ошибка: {error}").format(error=esc(e)))
        return
    await try_delete_command_message(message)
    name = await display(db, message.chat.id, target)
    await message.answer(getattr(phrases, "UNMUTE_SUCCESS", "{user} размучен").format(user=name))

@router.message(Command("варн", ignore_case=True))
@router.message(kw("варн"))
async def cmd_warn(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN,
                                    usage=getattr(phrases, "USAGE_WARN_LINE", "Использование варна"))
    if not prepared:
        return
    target, rest = prepared

    parts = rest.split(maxsplit=1)
    parsed_dur = parse_warn_duration_or_date(parts[0]) if parts else None
    if parsed_dur is None:
        await message.reply(getattr(phrases, "USAGE_WARN", "Укажите срок или дату варна"))
        return

    now_ts = int(time.time())
    if isinstance(parsed_dur, timedelta):
        if parsed_dur > MAX_WARN_DURATION:
            await message.reply(getattr(phrases, "ERR_WARN_TOO_LONG", "Срок слишком большой").format(days=MAX_WARN_DURATION.days))
            return
        expires_at = now_ts + int(parsed_dur.total_seconds())
        duration_text = format_datetime(expires_at)
    else:
        expires_at = int(parsed_dur.timestamp())
        if expires_at <= now_ts:
            await message.reply("Дата окончания варна должна быть в будущем.")
            return
        duration_text = format_datetime(expires_at)

    reason = " ".join(parts[1].split()) if len(parts) > 1 else ""
    if len(reason) > MAX_REASON_LEN:
        await message.reply(getattr(phrases, "ERR_TOO_LONG", "Слишком длинный текст").format(limit=MAX_REASON_LEN))
        return

    chat_id = message.chat.id
    name = await display(db, chat_id, target)

    last_warn = await db.get_last_warn_time(chat_id, target.id)
    if last_warn and now_ts - last_warn < WARN_COOLDOWN_SECONDS:
        minutes_left = math.ceil((WARN_COOLDOWN_SECONDS - (now_ts - last_warn)) / 60)
        await message.reply(getattr(phrases, "ERR_WARN_COOLDOWN", "Куда спешишь?").format(user=name, minutes=minutes_left))
        return

    if await db.get_total_warns(chat_id, target.id) >= MAX_ACTIVE_WARNS:
        try:
            await bot.ban_chat_member(chat_id, target.id)
        except Exception as e:
            await message.reply(getattr(phrases, "ERR_ACTION_FAILED", "Ошибка: {error}").format(error=esc(e)))
            return
        await db.reset_warns(chat_id, target.id)
        await try_delete_command_message(message)
        await message.answer(getattr(phrases, "WARN_LIMIT_REACHED", "{user} забанен за лимит варнов").format(user=name))
        return

    count = await db.add_temp_warn(chat_id, target.id, expires_at,
                                   issued_by=message.from_user.id, reason=reason or None)
    await try_delete_command_message(message)
    await message.answer(getattr(phrases, "WARN_SUCCESS", "Варн выдан {user}").format(
        user=name, count=count, limit=MAX_ACTIVE_WARNS + 1, until=duration_text,
        reason=getattr(phrases, "WARN_REASON", "Причина: {reason}").format(reason=esc(reason)) if reason else ""))

@router.message(kw("-варн"))
async def cmd_unwarn(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN,
                                    hierarchy=False, usage=getattr(phrases, "USAGE_UNWARN_LINE", "Использование -варн"))
    if not prepared:
        return
    target, rest = prepared
    tokens = rest.split()
    if len(tokens) > 1 or (tokens and (not is_number(tokens[0]) or int(tokens[0]) < 1)):
        await message.reply(getattr(phrases, "USAGE_UNWARN", "Использование -варн [число]"))
        return
    amount = min(int(tokens[0]), 99) if tokens else 1
    chat_id = message.chat.id
    name = await display(db, chat_id, target)
    before = await db.get_total_warns(chat_id, target.id)
    if before == 0:
        await message.reply(getattr(phrases, "UNWARN_NONE", "У пользователя нет варнов").format(user=name))
        return
    after = await db.decrease_warn(chat_id, target.id, amount)
    await try_delete_command_message(message)
    await message.answer(getattr(phrases, "UNWARN_SUCCESS", "Снято варнов").format(user=name, count=before - after, total=after))

# --- 1.1 Новая команда "варны" ---
@router.message(Command("варны", ignore_case=True))
@router.message(kw("варны"))
async def cmd_list_warns(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(getattr(phrases, "ERR_GROUP_ONLY", "Только для групп."))
        return
    chat_id = message.chat.id
    args = get_args(message)
    reply_user = get_reply_user(message)

    # Если указан @username или ответом на сообщение
    target_user = None
    if reply_user:
        target_user = reply_user
    elif args.strip():
        username = args.strip()
        uid = await db.get_user_id_by_username(chat_id, username)
        if uid:
            try:
                target_user = await bot.get_chat_member(chat_id, uid)
                target_user = target_user.user
            except Exception:
                pass

    await try_delete_command_message(message)

    if target_user:
        # Подробный список варнов пользователя
        details = await db.get_user_warn_details(chat_id, target_user.id)
        name = await display(db, chat_id, target_user)
        if not details:
            await message.answer(f"У пользователя <b>{name}</b> нет активных варнов.")
            return
        text = f"🛡 <b>Подробный список варнов пользователя {name}:</b>\n"
        for idx, d in enumerate(details, 1):
            expires_str = format_datetime(d["expires_at"])
            reason = d["reason"] or "Без причины"
            text += f"\n{idx}. До: {expires_str} | Причина: {esc(reason)}"
        await answer_long(message, text)
    else:
        # Общий список тех, кто получил варн
        warned_ids = await db.get_warned_users(chat_id)
        if not warned_ids:
            await message.answer("🛡 В чате нет пользователей с активными варнами.")
            return
        text = "🛡 <b>Список пользователей с варнами:</b>\n"
        for idx, uid in enumerate(warned_ids, 1):
            name = await display(db, chat_id, types.User(id=uid, is_bot=False, first_name="User"))
            total = await db.get_total_warns(chat_id, uid)
            text += f"\n{idx}. {name} — {total} варн(а/ов)"
        await answer_long(message, text)

# --- 2. Команда "скажи [текст]" ---
@router.message(kw("скажи"))
async def cmd_say(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    text = get_args(message)
    if not text:
        return
    await try_delete_command_message(message)
    chat_id = message.chat.id
    user_name = await display(db, chat_id, message.from_user)
    await message.answer(f"{user_name} говорит {text}")

# --- 3. Команда "+триггер" (Доступно начиная с уровня модераторства 3 / Владелец и суперпользователь) ---
@router.message(kw("+триггер"))
async def cmd_add_trigger(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    chat_id = message.chat.id
    level = await level_of(db, bot, chat_id, message.from_user.id)
    # Уровень 3 — Владелец, CREATOR_LEVEL — суперпользователь
    if level < LEVEL_OWNER:
        await message.reply(getattr(phrases, "ERR_NO_PERMISSION", "Недостаточно прав. Требуется 3+ уровень."))
        return

    args = get_args(message).strip()
    # 3.1: +триггер репутация [текст] [+/-]
    if args.lower().startswith("репутация"):
        sub_args = args[len("репутация"):].strip()
        parts = sub_args.rsplit(maxsplit=1)
        if len(parts) != 2 or parts[1] not in ("+", "-"):
            await message.reply("Использование: +триггер репутация [текст] [+|-]")
            return
        keyword, sign = parts[0].strip(), parts[1].strip()
        await db.add_trigger(chat_id, "reputation", keyword, sign)
        await try_delete_command_message(message)
        await message.answer(f"✅ Триггер репутации добавлен: «{esc(keyword)}» -> {sign}1")
        return

    # 3.2: +триггер табу [текст; текст] [команда]
    if args.lower().startswith(" табу"):
        # Пример: +триггер табу [блять; пошёл нахуй] варн 2н
        match = re.match(r"^табу\s*\[(.*?)\]\s+(.+)$", args, re.IGNORECASE | re.DOTALL)
        if not match:
            await message.reply("Использование: +триггер табу [текст; текст] [команда]")
            return
        keywords_raw, action_cmd = match.group(1), match.group(2).strip()
        keywords = [k.strip() for k in keywords_raw.split(";") if k.strip()]
        if not keywords or not action_cmd:
            await message.reply("Некорректный формат триггера табу.")
            return

        for kw_item in keywords:
            await db.add_trigger(chat_id, "tabu", kw_item, action_cmd)
        await try_delete_command_message(message)
        await message.answer(f"✅ Табу-триггеры ({len(keywords)} шт.) добавлены с действием: <code>{esc(action_cmd)}</code>")
        return

    await message.reply("Использование:\n+триггер репутация [текст] [+|-]\n+триггер табу [текст; текст] [команда]")

# --- 4.3 Передача кассет: +кассет [число] [@username/ответом] ---
@router.message(kw("+кассет"))
async def cmd_transfer_cassettes(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    chat_id = message.chat.id
    args = get_args(message).strip()
    reply_user = get_reply_user(message)

    target_id = None
    amount_str = ""

    if reply_user:
        target_id = reply_user.id
        amount_str = args
    else:
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            await message.reply("Использование: +кассет [число] [@username или ответом]")
            return
        amount_str = parts[0]
        username = parts[1].strip()
        target_id = await db.get_user_id_by_username(chat_id, username)
        if not target_id:
            await message.reply("Пользователь не найден.")
            return

    if not amount_str.isdigit() or int(amount_str) <= 0:
        await message.reply("Укажите положительное число кассет.")
        return

    amount = int(amount_str)
    sender_id = message.from_user.id

    if sender_id == target_id:
        await message.reply("Нельзя передавать кассеты самому себе.")
        return

    sender_balance = await db.get_cassettes(chat_id, sender_id)
    if sender_balance < amount:
        await message.reply(f"У вас недостаточно кассет. Ваш баланс: {sender_balance} 📼")
        return

    await db.add_cassettes(chat_id, sender_id, -amount)
    await db.add_cassettes(chat_id, target_id, amount)

    sender_name = await display(db, chat_id, message.from_user)
    target_name = await display(db, chat_id, types.User(id=target_id, is_bot=False, first_name="User"))

    await try_delete_command_message(message)
    await message.answer(f"📼 <b>{sender_name}</b> передал(а) <b>{amount}</b> кассет(ы) пользователю <b>{target_name}</b>!")

# --- 4.4 & 4.5 Покупка реста за кассеты: +рест и установка цены: -рест [число] ---
@router.message(kw("-рест"))
async def cmd_set_rest_price(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    chat_id = message.chat.id
    level = await level_of(db, bot, chat_id, message.from_user.id)
    if level < LEVEL_OWNER:
        await message.reply(getattr(phrases, "ERR_NO_PERMISSION", "Только для Владельца."))
        return
    args = get_args(message).strip()
    if not args.isdigit() or int(args) < 0:
        await message.reply("Использование: -рест [число]")
        return
    price = int(args)
    await db.set_rest_price(chat_id, price)
    await try_delete_command_message(message)
    await message.answer(f"💰 Цена реста установлена в размере <b>{price}</b> кассет(ы).")

@router.message(kw("+рест"))
async def cmd_buy_rest(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    chat_id = message.chat.id
    target, rest = await resolve_target(message, get_args(message), db, bot)
    if not target:
        target = message.from_user

    price = await db.get_rest_price(chat_id)
    sender_id = message.from_user.id
    sender_balance = await db.get_cassettes(chat_id, sender_id)

    if sender_balance < price:
        await message.reply(f"Недостаточно кассет для покупки реста. Требуется: {price} 📼, у вас: {sender_balance} 📼.")
        return

    # Списываем у отправителя
    await db.add_cassettes(chat_id, sender_id, -price)

    # Кассеты идут в счёт владельца группы (4.4)
    owner_id = await get_chat_owner_id(bot, chat_id)
    if owner_id:
        await db.add_cassettes(chat_id, owner_id, price)

    # Выдаем рест на 1 неделю
    until = int(time.time() + 7 * 86400)
    await db.touch_user(chat_id, target.id, target.username, target.first_name)
    await db.set_rest(chat_id, target.id, until)

    target_name = await display(db, chat_id, target)
    sender_name = await display(db, chat_id, message.from_user)
    await try_delete_command_message(message)
    await message.answer(f"🌴 <b>{sender_name}</b> купил(а) рест для <b>{target_name}</b> за {price} кассет(ы)! Рест активен до {format_datetime(until)}.")

# --- 4.1 & 4.2 Ежедневка: /ежедневка [число] или [мин-макс] ---
@router.message(Command("ежедневка", ignore_case=True))
@router.message(kw("ежедневка"))
async def cmd_daily(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    chat_id = message.chat.id
    args = get_args(message).strip()
    level = await level_of(db, bot, chat_id, message.from_user.id)

    # Если переданы аргументы -> настройка награды (доступно только с 3+ уровня)
    if args:
        if level < LEVEL_OWNER:
            await message.reply("Издавать настройки ежедневной награды могут только владельцы (3+ уровень).")
            return
        if not re.match(r"^\d+(-\d+)?$", args):
            await message.reply("Формат: /ежедневка [число] или [минимум-максимум] (например, /ежедневка 10-50)")
            return
        await db.set_daily_reward(chat_id, args)
        await try_delete_command_message(message)
        await message.answer(f"🎁 Ежедневная награда установлена: <b>{args}</b> кассет(ы).")
        return

    # Получение ежедневной награды пользователем (00:00 GMT+3)
    # Вычисляем текущую дату по GMT+3
    now_gmt3 = datetime.now(timezone(timedelta(hours=3)))
    today_str = now_gmt3.strftime("%Y-%m-%d")

    last_claim = await db.get_last_daily_claim(chat_id, message.from_user.id)
    if last_claim == today_str:
        await message.reply("🎁 Вы уже получили ежедневную награду сегодня! Приходите завтра в 00:00 GMT+3.")
        return

    reward_setting = await db.get_daily_reward(chat_id) or "1" # по умолчанию 1 кассета
    amount = 1
    if "-" in reward_setting:
        try:
            mn, mx = map(int, reward_setting.split("-"))
            amount = random.randint(min(mn, mx), max(mn, mx))
        except ValueError:
            amount = 1
    elif reward_setting.isdigit():
        amount = int(reward_setting)

    await db.set_last_daily_claim(chat_id, message.from_user.id, today_str)
    await db.add_cassettes(chat_id, message.from_user.id, amount)

    name = await display(db, chat_id, message.from_user)
    await try_delete_command_message(message)
    await message.answer(f"🎁 <b>{name}</b> получил(а) ежедневную награду в размере <b>{amount}</b> кассет(ы)! 📼")

@router.message(Command("модер", ignore_case=True))
async def cmd_moder(message: Message, db: Database, bot: Bot):
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_OWNER,
                                    usage=getattr(phrases, "USAGE_MODER_LINE", "Использование /модер"))
    if not prepared:
        return
    target, rest = prepared
    chat_id = message.chat.id
    tokens = rest.split()
    if len(tokens) != 1 or not is_number(tokens[0]):
        await message.reply(getattr(phrases, "USAGE_MODER", "Использование /модер").format(max=MAX_ASSIGNABLE_LEVEL))
        return
    new_level = int(tokens[0])
    if new_level > MAX_ASSIGNABLE_LEVEL:
        await message.reply(getattr(phrases, "ERR_BAD_LEVEL", "Неверный уровень"))
        return
    if target.is_bot:
        await message.reply(getattr(phrases, "ERR_BOT_TARGET", "Нельзя на бота"))
        return
    if target.id == await get_chat_owner_id(bot, chat_id):
        await message.reply(getattr(phrases, "ERR_OWNER_FIXED", "Нельзя менять владельца"))
        return

    old_level = await db.get_stored_moderator_level(chat_id, target.id)
    await db.set_moderator_level(chat_id, target.id, new_level)
    tg_note = "" # упрощенно
    await try_delete_command_message(message)
    name = await display(db, chat_id, target)
    text = getattr(phrases, "MODER_SET", "Уровень модератора установлен").format(
        user=name, level=new_level, role=phrases.MOD_STATUS_NAMES.get(new_level, getattr(phrases, "STATUS_MEMBER", "Участник")))
    await message.answer(text)

@router.message(Command("save", ignore_case=True))
async def cmd_save(message: Message, db: Database, bot: Bot):
    await try_delete_command_message(message)
    storage_id = get_storage_chat_id()
    if await level_of(db, bot, message.chat.id, message.from_user.id) < SAVE_MIN_LEVEL:
        await message.answer(getattr(phrases, "ERR_NO_PERMISSION", "Нет прав."))
        return
    if not storage_id or message.chat.id != storage_id:
        await message.answer("Неверный чат-хранилище.")
        return
    try:
        await send_backup(bot, db, storage_id, caption="Бэкап по запросу")
    except Exception as e:
        await message.answer(f"Ошибка бэкапа: {e}")

@router.message(Command("калл", ignore_case=True))
@router.message(kw("калл"))
async def cmd_call_everyone(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        await message.reply(getattr(phrases, "ERR_GROUP_ONLY", "Только для групп."))
        return
    text = " ".join(get_args(message).split())
    if not text:
        await message.reply("Укажите текст для сбора.")
        return
    chat_id = message.chat.id
    member_ids = await db.get_member_ids(chat_id, message.from_user.id, MAX_CALL_MEMBERS)
    if not member_ids:
        await message.reply("Никого не найдено.")
        return
    await try_delete_command_message(message)
    caller = await display(db, chat_id, message.from_user)
    header = f"🔔 {caller} вызывает всех: {esc(text)}"
    for i in range(0, len(member_ids), CALL_BATCH):
        mentions = "".join(f'<a href="tg://user?id={uid}">{random.choice(CALL_EMOJIS)}</a>' for uid in member_ids[i:i+CALL_BATCH])
        body = f"{header}\n\n{mentions}" if i == 0 else mentions
        try:
            await message.answer(body)
        except Exception:
            break
        await asyncio.sleep(1)

# --- Обработчик сообщений: Репутация (3.1) и Табу-триггеры (3.2) + РП команды ---
@router.message(F.text)
async def handle_text_messages(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    raw_text = message.text.strip()
    if not raw_text:
        return

    chat_id = message.chat.id

    # 1. Проверяем Табу-триггеры (3.2)
    tabu_triggers = await db.get_triggers(chat_id, "tabu")
    triggered_action = None
    for keyword, action in tabu_triggers:
        if keyword.lower() in raw_text.lower():
            triggered_action = action
            break

    if triggered_action:
        # Удаляем сообщение
        await try_delete_command_message(message)
        # Выполняем команду на автора сообщения (цель)
        # Симулируем команду или обрабатываем её
        # Пример: варн 2н -> вызываем варн на message.from_user
        # Или скажи {User} ... -> выполняем
        simulated_text = triggered_action.format(user=await display(db, chat_id, message.from_user), User=await display(db, chat_id, message.from_user))
        # Разбираем и выполняем действие
        if simulated_text.startswith("варн"):
            # выдать варн пользователю
            parts = simulated_text.split(maxsplit=1)
            duration_part = parts[1] if len(parts) > 1 else "1д"
            duration = parse_warn_duration_or_date(duration_part) or timedelta(days=1)
            expires_at = int(time.time() + duration.total_seconds()) if isinstance(duration, timedelta) else int(duration.timestamp())
            await db.add_temp_warn(chat_id, message.from_user.id, expires_at, issued_by=bot.id, reason="табу-триггер")
            name = await display(db, chat_id, message.from_user)
            await message.answer(f"⚠️ {name} получил(а) варн по табу-триггеру.")
        elif simulated_text.startswith("скажи"):
            said_text = simulated_text[len("скажи"):].strip()
            # Заменяем {User} / {user}
            user_name = await display(db, chat_id, message.from_user)
            said_text = said_text.replace("{User}", user_name).replace("{user}", user_name)
            await message.answer(said_text)
        else:
            # универсально отправляем текст или команду
            await message.answer(simulated_text)
        return

    # 2. Проверяем триггеры репутации (3.1)
    rep_triggers = await db.get_triggers(chat_id, "reputation")
    words = raw_text.split()
    for keyword, sign in rep_triggers:
        # Только полное совпадение слов
        if any(w.lower() == keyword.lower() for w in words):
            delta = 1 if sign == "+" else -1
            # Если сообщение является ответом на чье-то сообщение, меняем репутацию автора того сообщения, иначе автора текущего сообщения (или по правилу)
            target_uid = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else message.from_user.id
            if target_uid != message.from_user.id:
                await db.set_reputation(chat_id, target_uid, delta)
                target_name = await display(db, chat_id, message.reply_to_message.from_user)
                await message.answer(f"⭐ Репутация пользователя <b>{target_name}</b> изменена на {sign}1 (триггер: «{esc(keyword)}»)")
            break

    # 3. РП-команды
    first_word = raw_text.split(maxsplit=1)[0]
    cmd_candidate = (first_word[1:] if first_word.startswith("+") else first_word).lower()
    template = await db.get_rp_command(chat_id, cmd_candidate) if cmd_candidate else None

    if template:
        reply_user = get_reply_user(message)
        if reply_user and reply_user.id == bot.id:
            await try_delete_command_message(message)
            await message.answer(getattr(phrases, "ERR_BOT_TARGET", "Нельзя на бота"))
            return
        if not reply_user and re.search(r"\{(reply|r)\}", template):
            await message.answer(getattr(phrases, "ERR_NEED_REPLY", "Нужен ответ на сообщение"))
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
