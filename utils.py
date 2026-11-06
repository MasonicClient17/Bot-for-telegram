"""Общие помощники для модулей с командами (handlers, profile, quota)."""
import html
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, types
from aiogram.types import Message

import phrases
from config import LEVEL_OWNER, get_creator_id, get_quota_utc_offset, get_weekly_quota
from db import Database

GROUP_TYPES = {"group", "supergroup"}


def esc(value) -> str:
    """Экранирование для ParseMode.HTML: имена и тексты пользователей нельзя вставлять как есть."""
    return html.escape(str(value), quote=False)


# ---------- распознавание команд ----------

def kw(*words: str):
    """Точное совпадение ПЕРВОГО слова сообщения (без учёта регистра)."""
    wanted = {w.casefold() for w in words}

    def check(message: Message) -> bool:
        if not message.text:
            return False
        parts = message.text.split(maxsplit=1)
        return bool(parts) and parts[0].casefold() in wanted

    return F.func(check)


def kw_phrase(*words: str):
    """Точное совпадение первых N слов сообщения, например «кто я» или «снять варны»."""
    wanted = [w.casefold() for w in words]

    def check(message: Message) -> bool:
        if not message.text:
            return False
        parts = message.text.split(maxsplit=len(wanted))
        return len(parts) >= len(wanted) and [p.casefold() for p in parts[:len(wanted)]] == wanted

    return F.func(check)


def get_args(message: Message, skip: int = 1) -> str:
    """Текст после первых `skip` слов команды."""
    parts = (message.text or "").split(maxsplit=skip)
    return parts[skip].strip() if len(parts) > skip else ""


def is_number(value: str) -> bool:
    return value.isascii() and value.isdigit()


# ---------- чат и пользователи ----------

def is_group(message: Message) -> bool:
    return message.chat.type in GROUP_TYPES


async def try_delete_command_message(message: Message):
    if is_group(message):
        try:
            await message.delete()
        except Exception as e:
            logging.debug("Не удалось удалить сообщение с командой: %s", e)


def get_reply_user(message: Message) -> types.User | None:
    """Автор сообщения, на которое ответили (в форумах игнорируем корень топика)."""
    reply = message.reply_to_message
    if not reply or not reply.from_user or reply.forum_topic_created:
        return None
    return reply.from_user


OWNER_CACHE_SECONDS = 600
_owner_cache: dict[int, tuple[int | None, float]] = {}


async def get_chat_owner_id(bot: Bot, chat_id: int) -> int | None:
    """ID владельца группы в Telegram (кэшируется на 10 минут, чтобы не дёргать API на каждую команду)."""
    if chat_id > 0:  # личный чат
        return None
    cached = _owner_cache.get(chat_id)
    if cached and time.monotonic() - cached[1] < OWNER_CACHE_SECONDS:
        return cached[0]
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception as e:
        logging.debug("get_chat_administrators(%s) не удался: %s", chat_id, e)
        return cached[0] if cached else None
    owner_id = next((a.user.id for a in admins if a.status == "creator"), None)
    _owner_cache[chat_id] = (owner_id, time.monotonic())
    return owner_id


async def level_of(db: Database, bot: Bot, chat_id: int, user_id: int) -> int:
    """Эффективный уровень: из базы (создатель бота — CREATOR_LEVEL) и не ниже LEVEL_OWNER у владельца группы."""
    level = await db.get_moderator_level(chat_id, user_id, get_creator_id())
    if level < LEVEL_OWNER and user_id == await get_chat_owner_id(bot, chat_id):
        return LEVEL_OWNER
    return level


async def chat_quota(db: Database, chat_id: int) -> int:
    """Недельная норма чата: значение из /норма, иначе общее по умолчанию (WEEKLY_QUOTA)."""
    return await db.get_weekly_quota(chat_id, default=get_weekly_quota())


async def display(db: Database, chat_id: int, user: types.User) -> str:
    """Имя для вставки в сообщение: запоминает пользователя и экранирует HTML."""
    if not user.is_bot:  # боты в статистику не попадают
        await db.touch_user(chat_id, user.id, user.username, user.first_name)
    name = await db.get_display_name(chat_id, user.id, fallback=user.full_name)
    return esc(name)


# ---------- даты и вывод ----------

def _local(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=get_quota_utc_offset())


def format_date(ts: int) -> str:
    return _local(ts).strftime("%d.%m.%Y")


def format_datetime(ts: int) -> str:
    return _local(ts).strftime("%d.%m.%Y %H:%M")


async def answer_long(message: Message, text: str):
    while text:
        chunk, text = text[:4000], text[4000:]
        await message.answer(chunk)


# ---------- цель команды ----------

async def resolve_target(message: Message, args: str, db: Database, bot: Bot):
    """Цель команды: ответ на сообщение ИЛИ упоминание в конце (@username / тап по имени).
    Возвращает (User | None, args без упоминания)."""
    args = args.strip()

    reply_user = get_reply_user(message)
    if reply_user:
        return reply_user, args

    # Упоминание без username (text_mention) в самом конце
    for ent in reversed(message.entities or []):
        if ent.type == "text_mention" and ent.user:
            mention_text = ent.extract_from(message.text)
            if args.endswith(mention_text):
                return ent.user, args[: -len(mention_text)].strip()
            break

    # @username в конце
    tokens = args.rsplit(maxsplit=1)
    if tokens and tokens[-1].startswith("@") and len(tokens[-1]) > 1:
        rest = tokens[0] if len(tokens) == 2 else ""
        user_id = await db.get_user_id_by_username(message.chat.id, tokens[-1])
        if user_id:
            try:
                member = await bot.get_chat_member(message.chat.id, user_id)
                return member.user, rest
            except Exception as e:
                logging.debug("get_chat_member не удался: %s", e)
    return None, args


async def prepare_target(message: Message, args: str, db: Database, bot: Bot,
                         min_level: int, hierarchy: bool = True, usage: str = ""):
    """Проверяет права и цель. При проблеме сам отвечает на сообщение и возвращает None.
    При успехе возвращает (target, args без упоминания)."""
    if not is_group(message):
        await message.reply(phrases.ERR_GROUP_ONLY)
        return None
    chat_id = message.chat.id
    my_level = await level_of(db, bot, chat_id, message.from_user.id)
    if my_level < min_level:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return None
    target, rest = await resolve_target(message, args, db, bot)
    if not target:
        text = phrases.ERR_USER_NOT_FOUND
        if usage:
            text += "\n" + phrases.USAGE_PREFIX.format(usage=esc(usage))
        await message.reply(text)
        return None
    if target.id == bot.id:
        await message.reply(phrases.ERR_BOT_TARGET)
        return None
    if hierarchy and await level_of(db, bot, chat_id, target.id) >= my_level:
        await message.reply(phrases.ERR_NO_PERMISSION)
        return None
    return target, rest
