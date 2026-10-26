import html
import logging
import re
from datetime import timedelta

from aiogram import Router, F, Bot, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import phrases
from backup import send_backup
from config import get_creator_id, get_storage_chat_id
from db import Database

router = Router()
# Сообщения без отправителя (каналы и т.п.) обрабатывать не нужно
router.message.filter(F.from_user)

GROUP_TYPES = {"group", "supergroup"}
MAX_MOD_LEVEL = 4          # 1 — мут, 2 — варн/бан, 3 — назначение модеров, 4 — /save
TAG_MIN_LEVEL = 1          # кто может ставить тэги (0 — все, как было раньше)
MAX_NAME_LEN = 32
MAX_RP_TEXT_LEN = 1000
MAX_TAG_LEN = 32

SYSTEM_COMMANDS = {
    "мут", "размут", "варн", "бан", "снять", "модер", "актив",
    "ник", "тэг", "команда", "команды", "save", "start",
}

COMMAND_NAME_RE = re.compile(r"[\w-]{1,32}")
DURATION_RE = re.compile(r"(\d+)([мmчhдd])", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{(user|U|reply|r|random|rn)\}")


# ---------- помощники ----------

def esc(value) -> str:
    """Экранирование для ParseMode.HTML: имена и тексты пользователей нельзя вставлять как есть."""
    return html.escape(str(value), quote=False)


def kw(*words: str):
    """Точное совпадение ПЕРВОГО слова сообщения (без учёта регистра)."""
    wanted = {w.casefold() for w in words}

    def check(message: Message) -> bool:
        if not message.text:
            return False
        parts = message.text.split(maxsplit=1)
        return bool(parts) and parts[0].casefold() in wanted

    return F.func(check)


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


async def level_of(db: Database, chat_id: int, user_id: int) -> int:
    return await db.get_moderator_level(chat_id, user_id, get_creator_id())


async def display(db: Database, chat_id: int, user: types.User) -> str:
    """Имя для вставки в сообщение: запоминает пользователя и экранирует HTML."""
    await db.touch_user(chat_id, user.id, user.username, user.first_name)
    name = await db.get_display_name(chat_id, user.id, fallback=user.full_name)
    return esc(name)


def normalize_cmd_name(raw: str) -> str:
    return raw.strip().lstrip("+").lower()


async def answer_long(message: Message, text: str):
    while text:
        chunk, text = text[:4000], text[4000:]
        await message.answer(chunk)


async def resolve_target(message: Message, command: CommandObject, db: Database, bot: Bot):
    """Цель команды: ответ на сообщение ИЛИ упоминание в конце (@username / тап по имени).
    Возвращает (User | None, args без упоминания)."""
    args = (command.args or "").strip()

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


async def prepare_target(message: Message, command: CommandObject, db: Database, bot: Bot,
                         min_level: int, hierarchy: bool = True):
    """Проверяет права и цель. При проблеме сам отвечает и возвращает None.
    При успехе возвращает (target, args)."""
    if not is_group(message):
        await message.answer(phrases.ERR_GROUP_ONLY)
        return None
    chat_id = message.chat.id
    my_level = await level_of(db, chat_id, message.from_user.id)
    if my_level < min_level:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return None
    target, args = await resolve_target(message, command, db, bot)
    if not target:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return None
    if target.id == bot.id:
        await message.answer(phrases.ERR_BOT_TARGET)
        return None
    if hierarchy and await level_of(db, chat_id, target.id) >= my_level:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return None
    return target, args


# ---------- публичные и системные команды ----------

@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message):
    await try_delete_command_message(message)
    await message.answer(phrases.START_MESSAGE)


# ---------- РП-ники и тэги ----------

@router.message(kw("+ник"))
async def cmd_set_rp_name(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=1)
    name = " ".join(parts[1].split()) if len(parts) > 1 else ""
    if not name:
        await message.answer(phrases.USAGE_NICK)
        return
    if len(name) > MAX_NAME_LEN:
        await message.answer(phrases.ERR_TOO_LONG.format(limit=MAX_NAME_LEN))
        return
    await db.set_rp_name(message.chat.id, message.from_user.id, name)
    await message.answer(phrases.RP_NAME_SET.format(name=esc(name)))


@router.message(Command("ник", ignore_case=True))
@router.message(kw("-ник"))
async def cmd_reset_rp_name(message: Message, db: Database):
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, "")
    await message.answer(phrases.RP_NAME_RESET)


@router.message(kw("тэг"))
async def cmd_set_tag(message: Message, db: Database):
    await try_delete_command_message(message)
    chat_id = message.chat.id
    if await level_of(db, chat_id, message.from_user.id) < TAG_MIN_LEVEL:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    reply_user = get_reply_user(message)
    if reply_user:
        parts = message.text.split(maxsplit=1)
        tag_text = " ".join(parts[1].split()) if len(parts) > 1 else ""
        target_id = reply_user.id
        await db.touch_user(chat_id, reply_user.id, reply_user.username, reply_user.first_name)
    else:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(phrases.USAGE_TAG)
            return
        tag_text = " ".join(parts[2].split())
        target_id = await db.get_user_id_by_username(chat_id, parts[1])
        if not target_id:
            await message.answer(phrases.ERR_USER_NOT_FOUND)
            return

    if not tag_text:
        await message.answer(phrases.USAGE_TAG)
        return
    if len(tag_text) > MAX_TAG_LEN:
        await message.answer(phrases.ERR_TOO_LONG.format(limit=MAX_TAG_LEN))
        return

    await db.set_tag(chat_id, target_id, tag_text)
    target_display = esc(await db.get_display_name(chat_id, target_id))
    await message.answer(phrases.TAG_SET.format(user=target_display, tag=esc(tag_text)))


# ---------- РП-команды ----------

@router.message(kw("+команда"))
async def cmd_create_rp_command(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        await message.answer(phrases.USAGE_COMMAND_CREATE)
        return
    cmd_name = normalize_cmd_name(parts[1])
    cmd_text = parts[2].strip()

    if not COMMAND_NAME_RE.fullmatch(cmd_name):
        await message.answer(phrases.ERR_BAD_COMMAND_NAME)
        return
    if cmd_name in SYSTEM_COMMANDS:
        await message.answer(phrases.ERR_SYSTEM_COMMAND)
        return
    if len(cmd_text) > MAX_RP_TEXT_LEN:
        await message.answer(phrases.ERR_TOO_LONG.format(limit=MAX_RP_TEXT_LEN))
        return

    if not await db.add_rp_command(message.chat.id, cmd_name, cmd_text):
        await message.answer(phrases.ERR_COMMAND_EXISTS)
        return
    await message.answer(phrases.COMMAND_CREATED.format(name=esc(cmd_name)))


@router.message(Command("команды", ignore_case=True))
async def cmd_list_rp_commands(message: Message, db: Database):
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
async def cmd_delete_rp_command(message: Message, db: Database):
    await try_delete_command_message(message)
    if await level_of(db, message.chat.id, message.from_user.id) < 2:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(phrases.USAGE_COMMAND_DELETE)
        return
    cmd_name = normalize_cmd_name(parts[1].split()[0])
    if not await db.delete_rp_command(message.chat.id, cmd_name):
        await message.answer(phrases.ERR_COMMAND_NOT_FOUND)
        return
    await message.answer(phrases.COMMAND_DELETED.format(name=esc(cmd_name)))


# ---------- активность ----------

@router.message(Command("актив", ignore_case=True))
async def cmd_active(message: Message, command: CommandObject, db: Database):
    await try_delete_command_message(message)
    chat_id = message.chat.id
    total_users = await db.get_total_users_count(chat_id)
    if total_users == 0:
        await message.answer(phrases.EMPTY_ACTIVITY)
        return

    limit = 20
    total_pages = (total_users + limit - 1) // limit
    page = 1
    if command.args and command.args.strip().isdigit():
        page = int(command.args.strip())
    page = min(max(1, page), total_pages)
    offset = (page - 1) * limit

    top_users = await db.get_top_users(chat_id, limit, offset)
    text = phrases.ACTIVITY_HEADER.format(page=page, total=total_pages)
    for idx, (user_id, count) in enumerate(top_users, start=offset + 1):
        name = esc(await db.get_display_name(chat_id, user_id))
        text += phrases.ACTIVITY_LINE.format(index=idx, name=name, count=count)
    await message.answer(text)


# ---------- модерация ----------

def parse_mute_args(args: str | None):
    """'10м причина' -> (timedelta(minutes=10), '10м', 'причина'); без срока — навсегда."""
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


@router.message(Command("мут", ignore_case=True))
async def cmd_mute(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=1)
    if not prepared:
        return
    target, args = prepared
    until, duration_text, reason = parse_mute_args(args)
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except Exception as e:
        await message.answer(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.MUTE_SUCCESS.format(
        user=name, duration=esc(duration_text), reason=esc(reason)))


@router.message(Command("размут", ignore_case=True))
async def cmd_unmute(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=1, hierarchy=False)
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
        await message.answer(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.UNMUTE_SUCCESS.format(user=name))


@router.message(Command("варн", ignore_case=True))
async def cmd_warn(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=2)
    if not prepared:
        return
    target, args = prepared
    chat_id = message.chat.id
    reason = args or "Без причины"
    warn_count = await db.add_warn(chat_id, target.id)
    name = await display(db, chat_id, target)

    if warn_count >= 3:
        try:
            await bot.ban_chat_member(chat_id, target.id)
        except Exception as e:
            await message.answer(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
            return
        await db.reset_warns(chat_id, target.id)
        await message.answer(phrases.WARN_LIMIT_REACHED.format(user=name))
    else:
        await message.answer(phrases.WARN_SUCCESS.format(user=name, count=warn_count, reason=esc(reason)))


@router.message(Command("бан", ignore_case=True))
async def cmd_ban(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=2)
    if not prepared:
        return
    target, args = prepared
    reason = args or "Нарушение"
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
    except Exception as e:
        await message.answer(phrases.ERR_ACTION_FAILED.format(error=esc(e)))
        return
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.BAN_SUCCESS.format(user=name, reason=esc(reason)))


@router.message(Command("снять", ignore_case=True))
async def cmd_unwarn(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=2, hierarchy=False)
    if not prepared:
        return
    target, args = prepared
    amount = 1
    if args.isdigit():
        amount = min(max(1, int(args)), 3)
    new_total = await db.decrease_warn(message.chat.id, target.id, amount)
    name = await display(db, message.chat.id, target)
    await message.answer(phrases.UNWARN_SUCCESS.format(user=name, count=amount, total=new_total))


@router.message(Command("модер", ignore_case=True))
async def cmd_moder(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    prepared = await prepare_target(message, command, db, bot, min_level=3)
    if not prepared:
        return
    target, args = prepared
    chat_id = message.chat.id
    arg = args.split()
    if not arg or not arg[0].isdigit():
        await message.answer(phrases.USAGE_MODER.format(max=MAX_MOD_LEVEL))
        return
    new_level = int(arg[0])
    my_level = await level_of(db, chat_id, message.from_user.id)
    # Нельзя выдать уровень выше максимального и не ниже собственного (кроме создателя)
    if new_level > MAX_MOD_LEVEL or (new_level >= my_level and my_level != 99):
        await message.answer(phrases.ERR_BAD_LEVEL)
        return
    await db.set_moderator_level(chat_id, target.id, new_level)
    name = await display(db, chat_id, target)
    await message.answer(phrases.MODER_SET.format(user=name, level=new_level))


# ---------- бэкап ----------

@router.message(Command("save", ignore_case=True))
async def cmd_save(message: Message, db: Database, bot: Bot):
    await try_delete_command_message(message)
    storage_id = get_storage_chat_id()

    if await level_of(db, message.chat.id, message.from_user.id) < 4:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return
    if not storage_id or message.chat.id != storage_id:
        await message.answer(phrases.ERR_NOT_STORAGE_CHAT)
        return

    try:
        await send_backup(bot, db, storage_id, caption=phrases.BACKUP_SUCCESS)
    except Exception as e:
        logging.exception("Ошибка ручного бэкапа")
        await message.answer(phrases.ERR_BACKUP_FAILED.format(error=esc(e)))


# ---------- РП-команды пользователей и подсчёт активности ----------

@router.message(F.text)
async def handle_custom_rp_and_activity(message: Message, db: Database, bot: Bot):
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

    if not message.from_user.is_bot:
        await db.update_activity(
            chat_id=chat_id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
    )
        
