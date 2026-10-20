import os
import logging
from aiogram import Router, F, Bot, types
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command, CommandObject
from db import Database
import phrases

router = Router()

SYSTEM_COMMANDS = {
    "мут", "размут", "варн", "бан", "снять", 
    "модер", "актив", "ник", "тэг", "команды", "save"
}

def get_creator_id() -> int:
    return int(os.getenv("CREATOR_ID", "0"))

def get_storage_chat_id() -> int:
    return int(os.getenv("STORAGE_CHAT_ID", "0"))

async def try_delete_command_message(message: Message):
    """Вспомогательная функция для авто-удаления текста команды пользователя."""
    if message.chat.type in ["group", "supergroup"]:
        try:
            await message.delete()
        except Exception as e:
            logging.debug(f"Не удалось удалить сообщение с командой: {e}")

# --- Публичные и системные команды ---

@router.message(Command("start"))
async def cmd_start(message: Message):
    await try_delete_command_message(message)
    await message.answer(phrases.START_MESSAGE)

# --- Управление РП-никами и Тэгами ---

@router.message(F.text.startswith("+ник"))
async def cmd_set_rp_name(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return
    name = parts[1].strip()
    await db.set_rp_name(message.chat.id, message.from_user.id, name)
    await message.answer(phrases.RP_NAME_SET.format(name=name))

@router.message(Command("ник"))
@router.message(F.text == "-ник")
async def cmd_reset_rp_name(message: Message, db: Database):
    await try_delete_command_message(message)
    await db.set_rp_name(message.chat.id, message.from_user.id, "")
    await message.answer(phrases.RP_NAME_RESET)

@router.message(F.text.startswith("тэг"))
async def cmd_set_tag(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return
    target_username = parts[1]
    tag_text = parts[2]
    target_id = await db.get_user_id_by_username(message.chat.id, target_username)
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return
    await db.set_tag(message.chat.id, target_id, tag_text)
    target_display = await db.get_display_name(message.chat.id, target_id)
    await message.answer(phrases.TAG_SET.format(user=target_display, tag=tag_text))

# --- Пользовательские РП-команды ---

@router.message(F.text.startswith("+команда"))
async def cmd_create_rp_command(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return
    cmd_name = parts[1].strip().lower()
    cmd_text = parts[2].strip()

    if cmd_name in SYSTEM_COMMANDS:
        await message.answer(phrases.ERR_SYSTEM_COMMAND)
        return

    existing = await db.get_rp_command(message.chat.id, cmd_name)
    if existing:
        await message.answer(phrases.ERR_COMMAND_EXISTS)
        return

    await db.add_rp_command(message.chat.id, cmd_name, cmd_text)
    await message.answer(phrases.COMMAND_CREATED.format(name=cmd_name))

@router.message(Command("команды"))
async def cmd_list_rp_commands(message: Message, db: Database):
    await try_delete_command_message(message)
    commands = await db.get_all_rp_commands(message.chat.id)
    if not commands:
        await message.answer(phrases.COMMANDS_EMPTY)
        return
    text = phrases.COMMANDS_LIST_HEADER
    for (name,) in commands:
        text += phrases.COMMANDS_LIST_ITEM.format(name=name)
    await message.answer(text)

@router.message(F.text.startswith("-команда"))
async def cmd_delete_rp_command(message: Message, db: Database):
    await try_delete_command_message(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return
    cmd_name = parts[1].strip().lower()
    
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 2:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    await db.delete_rp_command(message.chat.id, cmd_name)
    await message.answer(phrases.COMMAND_DELETED.format(name=cmd_name))

# --- Активность (топ) ---

@router.message(Command("актив"))
async def cmd_active(message: Message, command: CommandObject, db: Database):
    await try_delete_command_message(message)
    page = 1
    if command.args and command.args.isdigit():
        page = max(1, int(command.args))
    
    limit = 20
    offset = (page - 1) * limit
    total_users = await db.get_total_users_count(message.chat.id)
    if total_users == 0:
        await message.answer(phrases.EMPTY_ACTIVITY)
        return

    total_pages = (total_users + limit - 1) // limit
    top_users = await db.get_top_users(message.chat.id, limit, offset)

    text = phrases.ACTIVITY_HEADER.format(page=page, total=total_pages)
    for idx, (user_id, count) in enumerate(top_users, start=offset + 1):
        name = await db.get_display_name(message.chat.id, user_id)
        text += phrases.ACTIVITY_LINE.format(index=idx, name=name, count=count)

    await message.answer(text)

# --- Модерация ---

@router.message(Command("мут"))
async def cmd_mute(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 1:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return
    
    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    reason = command.args or "Нарушение"
    
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    if target_id == bot.id:
        await message.answer(phrases.ERR_BOT_TARGET)
        return

    try:
        await bot.restrict_chat_member(message.chat.id, target_id, permissions=types.ChatPermissions(can_send_messages=False))
        target_name = await db.get_display_name(message.chat.id, target_id)
        await message.answer(phrases.MUTE_SUCCESS.format(user=target_name, reason=reason))
    except Exception as e:
        await message.answer(f"Ошибка мута: {e}")

@router.message(Command("размут"))
async def cmd_unmute(message: Message, db: Database, bot: Bot):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 1:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return
    
    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    try:
        await bot.restrict_chat_member(
            message.chat.id, 
            target_id, 
            permissions=types.ChatPermissions(
                can_send_messages=True, 
                can_send_media_messages=True, 
                can_send_other_messages=True
            )
        )
        target_name = await db.get_display_name(message.chat.id, target_id)
        await message.answer(phrases.UNMUTE_SUCCESS.format(user=target_name))
    except Exception as e:
        await message.answer(f"Ошибка размута: {e}")

@router.message(Command("варн"))
async def cmd_warn(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 2:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    reason = command.args or "Без причины"
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    if target_id == bot.id:
        await message.answer(phrases.ERR_BOT_TARGET)
        return

    warn_count = await db.add_warn(message.chat.id, target_id)
    target_name = await db.get_display_name(message.chat.id, target_id)

    if warn_count >= 3:
        await bot.ban_chat_member(message.chat.id, target_id)
        await message.answer(phrases.WARN_LIMIT_REACHED.format(user=target_name))
    else:
        await message.answer(phrases.WARN_SUCCESS.format(user=target_name, count=warn_count, reason=reason))

@router.message(Command("бан"))
async def cmd_ban(message: Message, command: CommandObject, db: Database, bot: Bot):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 2:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    reason = command.args or "Нарушение"
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    if target_id == bot.id:
        await message.answer(phrases.ERR_BOT_TARGET)
        return

    await bot.ban_chat_member(message.chat.id, target_id)
    target_name = await db.get_display_name(message.chat.id, target_id)
    await message.answer(phrases.BAN_SUCCESS.format(user=target_name, reason=reason))

@router.message(Command("снять"))
async def cmd_unwarn(message: Message, command: CommandObject, db: Database):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 2:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    if not target_id:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    amount = int(command.args) if command.args and command.args.isdigit() else 1
    new_total = await db.decrease_warn(message.chat.id, target_id, amount)
    target_name = await db.get_display_name(message.chat.id, target_id)
    await message.answer(phrases.UNWARN_SUCCESS.format(user=target_name, count=amount, total=new_total))

@router.message(Command("модер"))
async def cmd_moder(message: Message, command: CommandObject, db: Database):
    await try_delete_command_message(message)
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, get_creator_id())
    if level < 3:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    target_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
    if not target_id or not command.args:
        await message.answer(phrases.ERR_USER_NOT_FOUND)
        return

    args = command.args.split()
    if not args[0].isdigit():
        return
    new_level = int(args[0])

    await db.set_moderator_level(message.chat.id, target_id, new_level)
    target_name = await db.get_display_name(message.chat.id, target_id)
    await message.answer(phrases.MODER_SET.format(user=target_name, level=new_level))

@router.message(Command("save"))
async def cmd_save(message: Message, db: Database, bot: Bot):
    await try_delete_command_message(message)
    storage_id = get_storage_chat_id()
    creator_id = get_creator_id()
    level = await db.get_moderator_level(message.chat.id, message.from_user.id, creator_id)

    if level < 4 and message.from_user.id != creator_id:
        await message.answer(phrases.ERR_NO_PERMISSION)
        return

    if message.chat.id != storage_id:
        await message.answer(phrases.ERR_NOT_STORAGE_CHAT)
        return

    await db.conn.commit()
    await bot.send_document(
        chat_id=storage_id,
        document=FSInputFile("database.db"),
        caption=phrases.BACKUP_SUCCESS
    )

# --- Обработчик обычных сообщений и кастомных РП-команд ---

@router.message()
async def handle_custom_rp_and_activity(message: Message, db: Database, bot: Bot):
    if not message.text or message.chat.type not in ["group", "supergroup"]:
        return

    raw_text = message.text.strip()

    # Игнорируем стандартные команды с / или системные ключевые слова (команды не засчитываем в актив)
    if raw_text.startswith("/") or raw_text.startswith("+ник") or raw_text.startswith("-ник") or raw_text.startswith("тэг") or raw_text.startswith("+команда") or raw_text.startswith("-команда"):
        return

    # Проверяем, является ли сообщение пользовательской РП-командой
    cmd_candidate = raw_text.lstrip("+").split()[0].lower()
    rp_text_template = await db.get_rp_command(message.chat.id, cmd_candidate)

    if rp_text_template:
        # Утилизируем исходный текст РП-команды
        await try_delete_command_message(message)

        target_user = None
        if message.reply_to_message:
            target_user = message.reply_to_message.from_user

        if target_user and target_user.id == bot.id:
            await message.answer(phrases.ERR_BOT_TARGET)
            return

        sender_id = message.from_user.id
        sender_name = await db.get_display_name(message.chat.id, sender_id)

        reply_name = ""
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_name = await db.get_display_name(message.chat.id, message.reply_to_message.from_user.id)

        random_user_id = await db.get_random_user(message.chat.id)
        random_name = await db.get_display_name(message.chat.id, random_user_id) if random_user_id else "Кто-то"

        formatted_text = rp_text_template \
            .replace("{user}", sender_name).replace("{U}", sender_name) \
            .replace("{reply}", reply_name).replace("{r}", reply_name) \
            .replace("{random}", random_name).replace("{rn}", random_name)

        await message.answer(formatted_text)
        return

    # Если это обычное текстовое сообщение в чате (не команда) — обновляем счетчик активности
    if message.from_user and not message.from_user.is_bot:
        await db.update_activity(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        
