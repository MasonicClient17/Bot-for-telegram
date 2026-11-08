import asyncio
import logging
import math
import random
import re
import time
from datetime import timedelta

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
    level_of, prepare_target, try_delete_command_message, get_reply_user,
)

router = Router()
# Сообщения без отправителя (каналы и т.п.) обрабатывать не нужно
router.message.filter(F.from_user)

TAG_MIN_LEVEL = LEVEL_HELPER  # кто может ставить тэги (0 — все)
SAVE_MIN_LEVEL = LEVEL_OWNER  # ручной бэкап /save
MAX_NAME_LEN = 32
MAX_RP_TEXT_LEN = 1000
MAX_TAG_LEN = 32

# «калл» — общий сбор: каждый участник упоминается скрытой ссылкой-смайликом
CALL_COOLDOWN_SECONDS = 120   # пауза между сборами в одном чате (модераторы 1+ без паузы)
CALL_BATCH = 50               # упоминаний в одном сообщении (лимит Telegram — 100 на сообщение)
MAX_CALL_MEMBERS = 500
MAX_CALL_TEXT_LEN = 500
CALL_EMOJIS = list("😀😎🤠🥳😺🐶🦊🐼🐸🐵🦁🐯🐰🐨🐙🦄🐝🦋🌸🌻🍀🌈⭐🔥💎🎈🎵🎲🚀🍕🍩🍉🍒🧩🎯🏆🌟💫🍄🐢🦉")
_last_call: dict[int, float] = {}

SYSTEM_COMMANDS = {
    "мут", "размут", "варн", "-варн", "бан", "модер", "актив", "рест", "-рест",
    "ник", "-ник", "тэг", "команда", "-команда", "команды", "save", "start", "калл", "помощь",
    "кто", "норма", "неактив", "чистка",
}

COMMAND_NAME_RE = re.compile(r"[\w-]{1,32}")
DURATION_RE = re.compile(r"(\d+)([мmчhдd])", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{(user|U|reply|r|random|rn)\}")


# ---------- помощники ----------

def normalize_cmd_name(raw: str) -> str:
    return raw.strip().lstrip("+").lower()


# ---------- публичные и системные команды ----------

@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message):
    await try_delete_command_message(message)
    await message.answer(phrases.START_MESSAGE)


# ---------- РП-ники и тэги ----------
# Правило для команд без «/»: сообщение удаляется, только когда команда ВЫПОЛНЕНА.
# Ошибка в слове — бот молчит. Ошибка в структуре — бот отвечает пояснением и ничего не удаляет
# (вдруг это обычная фраза, например «актив сегодня слабый»).

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


# ---------- РП-команды ----------

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

    # Свою команду может удалить автор, чужую (и старую, без автора) — модератор уровня 1+
    is_author = author_id is not None and author_id == message.from_user.id
    if not is_author and await level_of(db, bot, chat_id, message.from_user.id) < LEVEL_HELPER:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return

    await try_delete_command_message(message)
    await db.delete_rp_command(chat_id, cmd_name)
    await message.answer(phrases.COMMAND_DELETED.format(name=esc(cmd_name)))


# ---------- справка ----------

@router.message(Command("помощь", ignore_case=True))
@router.message(kw("помощь"))
async def cmd_help(message: Message):
    if get_args(message):
        await message.reply(phrases.USAGE_HELP)
        return
    await try_delete_command_message(message)
    await message.answer(phrases.HELP_TEXT)


# ---------- модерация ----------
# Сообщение с командой удаляется только после успешного выполнения; при ошибке бот отвечает на него.

WARN_DURATION_RE = re.compile(r"([0-9]{1,4})([чднм])", re.IGNORECASE)
WARN_UNITS = {
    "ч": timedelta(hours=1),
    "д": timedelta(days=1),
    "н": timedelta(weeks=1),
    "м": timedelta(days=30),      # месяц = 30 дней
}
MAX_WARN_DURATION = timedelta(days=365)
MAX_REASON_LEN = 200


def parse_mute_args(args: str | None):
    """'10м причина' -> (timedelta(minutes=10), '10м', 'причина'); без срока — навсегда.
    Внимание: в муте «м» — минуты (в варне «м» — месяцы)."""
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


def parse_warn_duration(token: str) -> timedelta | None:
    """'2д' -> 2 дня, '1н' -> неделя, '3м' -> 90 дней. Неверный формат или нулевой срок -> None."""
    match = WARN_DURATION_RE.fullmatch(token)
    if not match:
        return None
    value = int(match.group(1))
    if value == 0:
        return None
    return WARN_UNITS[match.group(2).lower()] * value


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
        # Всё, что не передано в restrict_chat_member, Telegram считает запрещённым —
        # поэтому возвращаем права по умолчанию самого чата.
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
    """варн [число][ч|д|н|м] [причина] [@username] — варн с истечением; 3-й активный варн = бан."""
    prepared = await prepare_target(message, get_args(message), db, bot, min_level=LEVEL_ADMIN,
                                    usage=phrases.USAGE_WARN_LINE)
    if not prepared:
        return
    target, rest = prepared

    parts = rest.split(maxsplit=1)
    duration = parse_warn_duration(parts[0]) if parts else None
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

    # Защита: не чаще одного варна в час на пользователя
    last_warn = await db.get_last_warn_time(chat_id, target.id)
    if last_warn and now - last_warn < WARN_COOLDOWN_SECONDS:
        minutes_left = math.ceil((WARN_COOLDOWN_SECONDS - (now - last_warn)) / 60)
        await message.reply(phrases.ERR_WARN_COOLDOWN.format(user=name, minutes=minutes_left))
        return

    # Лимит: при выдаче 3-го активного варна — бан (сначала бан, и только при успехе чистим варны)
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
    """-варн [число] [@username] — снимает варны (число по умолчанию 1)."""
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
    """Связка роли «Админ» с админкой в Telegram: выдаёт её при назначении и снимает при снятии роли.
    Возвращает строку для ответа ('' — ничего менять не пришлось)."""
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
    """/модер [уровень 0–2] [@username]. Владелец (3) не выдаётся: это владелец группы в Telegram."""
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


# ---------- бэкап ----------

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


# ---------- общий сбор ----------

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
    try:  # админы, которых бот ещё ни разу не видел в чате
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

    # Если «калл» написан ответом на сообщение — сбор тоже уходит ответом на него
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
        await asyncio.sleep(1)  # лимит Telegram: ~20 сообщений в минуту на группу


# ---------- вызов РП-команд пользователей ----------
# Сообщения здесь НЕ считаются: подсчёт делает activity.ActivityMiddleware для всех сообщений сразу.

@router.message(F.text)
async def handle_rp_command(message: Message, db: Database, bot: Bot):
    if not is_group(message):
        return
    raw_text = message.text.strip()
    if not raw_text or raw_text.startswith("/"):
        return

    chat_id = message.chat.id
    first_word = raw_text.split(maxsplit=1)[0]
    cmd_candidate = (first_word[1:] if first_word.startswith("+") else first_word).lower()
    template = await db.get_rp_command(chat_id, cmd_candidate) if cmd_candidate else None

    if template:
        reply_user = get_reply_user(message)
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
        # Один проход: подставленное имя не может само оказаться плейсхолдером
        text = PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], esc(template))
        await message.answer(text)
        return
