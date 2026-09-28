import asyncio
import logging
import os
import re
import random
import json
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command
from aiogram.types import ChatPermissions, FSInputFile

# 1. Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
STORAGE_GROUP_ID = os.getenv("STORAGE_GROUP_ID")

if BOT_TOKEN:
    BOT_TOKEN = BOT_TOKEN.strip().strip('"').strip("'")

if STORAGE_GROUP_ID:
    STORAGE_GROUP_ID = STORAGE_GROUP_ID.strip().strip('"').strip("'")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot_database.db"

# Допустимый набор эмодзи для генерации созыва
CALL_EMOJIS = ["🌸", "☁️", "👁", "🐍", "🌫", "🥛", "🫗", "🍨", "🍧", "🌈", "🍇", "🫙"]

# Базовые пороги уровней для стандартных команд
DEFAULT_CMD_LEVELS = {
    "клиновый сироп": 1,
    "напоить сиропом": 1,
    "дать плод всей боли": 1,
    "дать воды": 1,
    "калл": 1,
    "call": 1,
    "созыв": 1,
    "варн": 2,
    "отругать": 2,
    "актив": 2,
    "стата": 2,
    "статистика": 2,
    "банка с джемом": 3,
    "в банку": 3,
    "вытащить из банки": 3,
    "повысить": 3,
    "+модер": 3,
    "понизить": 3,
    "-модер": 3,
    "+устав": 3,
    "устав+": 3,
}

SYSTEM_RESERVED_WORDS = list(DEFAULT_CMD_LEVELS.keys()) + [
    "устав", "правила", "устав сада", "правила сада", "ники", "звания",
    "+ник", "-ник", "+команда", "-команда", "список команд", "команды",
    "рп команды", "+роль", "сменить"
]

# --- Middleware подсчета активности ---

class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        if isinstance(event, types.Message) and event.from_user and not event.from_user.is_bot and event.chat.type in ["group", "supergroup"]:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO users (chat_id, user_id, msg_count) VALUES (?, ?, 1)
                    ON CONFLICT(chat_id, user_id) DO UPDATE SET msg_count = msg_count + 1
                """, (event.chat.id, event.from_user.id))
                await db.commit()
        return await handler(event, data)

# --- База данных ---

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER,
            user_id INTEGER,
            role_level INTEGER DEFAULT 0,
            warns INTEGER DEFAULT 0,
            msg_count INTEGER DEFAULT 0,
            rp_name TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS roles_custom (
            chat_id INTEGER,
            level INTEGER,
            title TEXT,
            PRIMARY KEY (chat_id, level)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS rules_chapters (
            chat_id INTEGER,
            chapter_num INTEGER,
            title TEXT,
            PRIMARY KEY (chat_id, chapter_num)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS rules_items (
            chat_id INTEGER,
            chapter_num INTEGER,
            rule_num INTEGER,
            text TEXT,
            PRIMARY KEY (chat_id, chapter_num, rule_num)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER,
            cmd_name TEXT,
            cmd_text TEXT,
            PRIMARY KEY (chat_id, cmd_name)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS cmd_levels (
            chat_id INTEGER,
            cmd_name TEXT,
            required_level INTEGER,
            PRIMARY KEY (chat_id, cmd_name)
        )
        """)
        await db.commit()

# --- Вспомогательные функции ---

async def get_user_role(chat_id: int, user_id: int) -> int:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == ChatMemberStatus.CREATOR:
            return 4
    except Exception:
        pass

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_level FROM users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_required_level(chat_id: int, cmd_name: str) -> int:
    cmd_key = cmd_name.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT required_level FROM cmd_levels WHERE chat_id = ? AND cmd_name = ?",
            (chat_id, cmd_key)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
    return DEFAULT_CMD_LEVELS.get(cmd_key, 0)

async def get_display_name(chat_id: int, user: types.User) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT rp_name FROM users WHERE chat_id = ? AND user_id = ?", (chat_id, user.id)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
    return user.full_name

def parse_duration(text: str) -> timedelta:
    if not text:
        return timedelta(minutes=60)
    match = re.search(r"(\d+)\s*(мин|ч|час|дня|день|дней|д)", text.lower())
    if not match:
        return timedelta(minutes=60)
    val = int(match.group(1))
    unit = match.group(2)
    if "мин" in unit:
        return timedelta(minutes=val)
    elif "ч" in unit:
        return timedelta(hours=val)
    elif "д" in unit:
        return timedelta(days=val)
    return timedelta(minutes=60)

async def resolve_target_user(message: types.Message) -> Optional[types.User]:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    entities = message.entities or []
    for entity in entities:
        if entity.type == "text_mention":
            return entity.user
    return None

# --- Настройка уровней доступа (`сменить`) ---

@dp.message(F.text.re.match(r"^сменить\s+(?:\((.*?)\)|(\S+))\s+(\d+)$", re.IGNORECASE))
async def change_cmd_level(message: types.Message):
    user_role = await get_user_role(message.chat.id, message.from_user.id)
    if user_role < 4:
        return await message.answer("🌫 Только Создатель группы (4 уровень) может менять доступ к командам!")

    match = re.match(r"^сменить\s+(?:\((.*?)\)|(\S+))\s+(\d+)$", message.text, re.IGNORECASE)
    cmd_name = (match.group(1) or match.group(2)).lower().strip()
    new_lvl = int(match.group(3))

    if cmd_name not in DEFAULT_CMD_LEVELS:
        return await message.answer("🌫 Эту команду нельзя перенастроить или она не существует!")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO cmd_levels (chat_id, cmd_name, required_level) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, cmd_name) DO UPDATE SET required_level = ?
        """, (message.chat.id, cmd_name, new_lvl, new_lvl))
        await db.commit()

    await message.answer(f"🌸 Уровень доступа для команды «<b>{cmd_name}</b>» изменен на <b>{new_lvl}</b>.", parse_mode=ParseMode.HTML)

# --- Управление ролями (`+роль`, `повысить`, `понизить`) ---

@dp.message(F.text.re.match(r"^\+роль\s+([1-3])\s+(.+)$", re.IGNORECASE))
async def set_role_title(message: types.Message):
    user_role = await get_user_role(message.chat.id, message.from_user.id)
    if user_role < 4:
        return await message.answer("🌫 Изменять названия ролей может только Создатель группы!")

    match = re.match(r"^\+роль\s+([1-3])\s+(.+)$", message.text, re.IGNORECASE)
    lvl = int(match.group(1))
    title = match.group(2).strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO roles_custom (chat_id, level, title) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, level) DO UPDATE SET title = ?
        """, (message.chat.id, lvl, title, title))
        await db.commit()

    await message.answer(f"🌸 Должность уровня {lvl} переименована в «<b>{title}</b>».", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(повысить|\+модер)\s*([1-2])?$", re.IGNORECASE))
async def promote_user(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "повысить")
    user_role = await get_user_role(message.chat.id, message.from_user.id)
    if user_role < req_lvl:
        return await message.answer(f"🌫 Требуется уровень доступа {req_lvl}+!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение пользователя или упомяните его!")

    match = re.match(r"^(повысить|\+модер)\s*([1-2])?$", message.text, re.IGNORECASE)
    target_lvl = int(match.group(2)) if match.group(2) else 1

    if target_lvl >= user_role:
        return await message.answer("🌫 Нельзя повысить до своего уровня или выше!")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (chat_id, user_id, role_level) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET role_level = ?
        """, (message.chat.id, target.id, target_lvl, target_lvl))
        await db.commit()

    if target_lvl >= 2:
        try:
            await bot.promote_chat_member(
                chat_id=message.chat.id,
                user_id=target.id,
                can_manage_chat=True,
                can_delete_messages=True,
                can_restrict_members=True
            )
        except Exception:
            pass

    await message.answer(f"🌸 Пользователь {target.mention_html()} назначен на уровень <b>{target_lvl}</b>!", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(понизить|-модер)$", re.IGNORECASE))
async def demote_user(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "понизить")
    user_role = await get_user_role(message.chat.id, message.from_user.id)
    if user_role < req_lvl:
        return await message.answer(f"🌫 Требуется уровень доступа {req_lvl}+!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение пользователя!")

    target_role = await get_user_role(message.chat.id, target.id)
    if target_role >= user_role:
        return await message.answer("🌫 Вы не можете понизить этого пользователя!")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET role_level = 0 WHERE chat_id = ? AND user_id = ?",
            (message.chat.id, target.id)
        )
        await db.commit()

    try:
        await bot.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_restrict_members=False
        )
    except Exception:
        pass

    await message.answer(f"🌸 Пользователь {target.mention_html()} разжалован до обычного участника.", parse_mode=ParseMode.HTML)

# --- Модерация ---

@dp.message(F.text.re.match(r"^(клиновый сироп|напоить сиропом)", re.IGNORECASE))
async def mute_syrup(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "клиновый сироп")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение нарушителя!")

    duration = parse_duration(message.text)
    until = datetime.now() + duration

    await bot.restrict_chat_member(
        message.chat.id, target.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until
    )
    await message.answer(f"🫗 {target.mention_html()} напоен сиропом на <b>{duration}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^дать плод всей боли", re.IGNORECASE))
async def mute_fruit_pain(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "дать плод всей боли")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение нарушителя!")

    until = datetime.now() + timedelta(days=1)
    await bot.restrict_chat_member(
        message.chat.id, target.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until
    )
    await message.answer(f"🍇 Пользователь {target.mention_html()} получил плод всей боли (мут на 24 часа).", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^дать воды$", re.IGNORECASE))
async def unmute_water(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "дать воды")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение пользователя!")

    await bot.restrict_chat_member(
        message.chat.id, target.id,
        permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
    )
    await message.answer(f"🥛 {target.mention_html()} получил воды. Мут снят.", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(варн|отругать)", re.IGNORECASE))
async def issue_warn(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "варн")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение нарушителя!")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (chat_id, user_id, warns) VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET warns = warns + 1
        """, (message.chat.id, target.id))
        await db.commit()

        async with db.execute(
            "SELECT warns FROM users WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id)
        ) as cursor:
            warns = (await cursor.fetchone())[0]

    if warns >= 3:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.answer(f"🐍 Пользователь {target.mention_html()} получил 3/3 варнов и отправлен в бан!", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"👁 {target.mention_html()} получил предупреждение [{warns}/3].", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(банка с джемом|в банку)", re.IGNORECASE))
async def ban_user(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "в банку")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение нарушителя!")

    await bot.ban_chat_member(message.chat.id, target.id)
    await message.answer(f"🫙 {target.mention_html()} запечатан в банку с джемом (бан).", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^вытащить из банки$", re.IGNORECASE))
async def unban_user(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "вытащить из банки")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    target = await resolve_target_user(message)
    if not target:
        return await message.answer("🌫 Ответьте на сообщение пользователя!")

    await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
    await message.answer(f"🌸 Пользователь {target.mention_html()} вытащен из банки (разбанен).", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(актив|стата|статистика)$", re.IGNORECASE))
async def show_activity(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "актив")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, msg_count FROM users WHERE chat_id = ? ORDER BY msg_count DESC LIMIT 20",
            (message.chat.id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.answer("🍧 Статистика сообщений пуста.")

    text = "🍧 <b>ТОП-20 активных участников:</b>\n\n"
    for idx, (uid, count) in enumerate(rows, 1):
        try:
            m = await bot.get_chat_member(message.chat.id, uid)
            name = await get_display_name(message.chat.id, m.user)
        except Exception:
            name = f"ID: {uid}"
        text += f"{idx}. {name} — <b>{count}</b> сообщ.\n"

    await message.answer(text, parse_mode=ParseMode.HTML)

# --- Команда созыва (калл / call) ---

@dp.message(F.text.re.match(r"^(калл|call|созыв)(?:\s+(.+))?$", re.IGNORECASE))
async def call_all_users(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "калл")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав для выполнения созыва!")

    match = re.match(r"^(калл|call|созыв)(?:\s+(.+))?$", message.text, re.IGNORECASE)
    call_text = match.group(2) or "Общий созыв участников Сада!"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE chat_id = ?", (message.chat.id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.answer("🌫 В базе данных пока нет известных участников этого чата!")

    mentions = []
    for uid, in rows:
        emo = random.choice(CALL_EMOJIS)
        mentions.append(f'<a href="tg://user?id={uid}">{emo}</a>')

    mentions_str = " ".join(mentions)
    await message.answer(f"🌸 <b>{call_text}</b>\n\n{mentions_str}", parse_mode=ParseMode.HTML)

# --- Устав Сада ---

@dp.message(F.text.re.match(r"^\+устав\s+(\d+)\s+(.+)$", re.IGNORECASE))
async def add_rules_chapter(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "+устав")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    match = re.match(r"^\+устав\s+(\d+)\s+(.+)$", message.text, re.IGNORECASE)
    ch_num = int(match.group(1))
    title = match.group(2).strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO rules_chapters (chat_id, chapter_num, title) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, chapter_num) DO UPDATE SET title = ?
        """, (message.chat.id, ch_num, title, title))
        await db.commit()

    await message.answer(f"🌸 Раздел <b>{ch_num}. {title}</b> успешно создан!", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^\+устав\s+(\d+)\.(\d+)\s+(.+)$", re.IGNORECASE))
async def add_rule_item(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "+устав")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    match = re.match(r"^\+устав\s+(\d+)\.(\d+)\s+(.+)$", message.text, re.IGNORECASE)
    ch_num = int(match.group(1))
    r_num = int(match.group(2))
    rule_text = match.group(3).strip()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM rules_chapters WHERE chat_id = ? AND chapter_num = ?", (message.chat.id, ch_num)
        ) as cursor:
            if not await cursor.fetchone():
                return await message.answer(f"🌫 Сначала создайте раздел {ch_num}: <code>+устав {ch_num} [Название]</code>", parse_mode=ParseMode.HTML)

        if r_num > 1:
            async with db.execute(
                "SELECT 1 FROM rules_items WHERE chat_id = ? AND chapter_num = ? AND rule_num = ?",
                (message.chat.id, ch_num, r_num - 1)
            ) as cursor:
                if not await cursor.fetchone():
                    return await message.answer(f"🌫 Нельзя добавить правило {ch_num}.{r_num}, пока не существует {ch_num}.{r_num-1}!")

        await db.execute("""
            INSERT INTO rules_items (chat_id, chapter_num, rule_num, text) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, chapter_num, rule_num) DO UPDATE SET text = ?
        """, (message.chat.id, ch_num, r_num, rule_text, rule_text))
        await db.commit()

    await message.answer(f"🌸 Добавлено правило <b>{ch_num}.{r_num}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^устав\s+(\d+)\+\s+(.+)$", re.IGNORECASE))
async def append_rule_item(message: types.Message):
    req_lvl = await get_required_level(message.chat.id, "устав+")
    if await get_user_role(message.chat.id, message.from_user.id) < req_lvl:
        return await message.answer("🌫 Недостаточно прав!")

    match = re.match(r"^устав\s+(\d+)\+\s+(.+)$", message.text, re.IGNORECASE)
    ch_num = int(match.group(1))
    rule_text = match.group(2).strip()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(rule_num) FROM rules_items WHERE chat_id = ? AND chapter_num = ?",
            (message.chat.id, ch_num)
        ) as cursor:
            row = await cursor.fetchone()
            next_r = (row[0] or 0) + 1

        await db.execute(
            "INSERT INTO rules_items (chat_id, chapter_num, rule_num, text) VALUES (?, ?, ?, ?)",
            (message.chat.id, ch_num, next_r, rule_text)
        )
        await db.commit()

    await message.answer(f"🌸 Правило автоматически добавлено под номером <b>{ch_num}.{next_r}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(устав сада|устав|правила|правила сада)(?:\s+(\d+)(?:\.(\d+))?)?$", re.IGNORECASE))
async def show_rules(message: types.Message):
    match = re.match(r"^(устав сада|устав|правила|правила сада)(?:\s+(\d+)(?:\.(\d+))?)?$", message.text, re.IGNORECASE)
    ch_filter = match.group(2)
    rule_filter = match.group(3)

    async with aiosqlite.connect(DB_PATH) as db:
        if ch_filter and rule_filter:
            async with db.execute(
                "SELECT text FROM rules_items WHERE chat_id = ? AND chapter_num = ? AND rule_num = ?",
                (message.chat.id, int(ch_filter), int(rule_filter))
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return await message.answer(f"🌸 <b>Правило {ch_filter}.{rule_filter}:</b> {row[0]}", parse_mode=ParseMode.HTML)
                return await message.answer("🌫 Такое правило не найдено.")

        elif ch_filter:
            async with db.execute(
                "SELECT title FROM rules_chapters WHERE chat_id = ? AND chapter_num = ?",
                (message.chat.id, int(ch_filter))
            ) as cursor:
                ch_row = await cursor.fetchone()
                if not ch_row:
                    return await message.answer("🌫 Раздел не найден.")
                
                text = f"<b>{ch_filter}. {ch_row[0]}</b>\n"
                async with db.execute(
                    "SELECT rule_num, text FROM rules_items WHERE chat_id = ? AND chapter_num = ? ORDER BY rule_num",
                    (message.chat.id, int(ch_filter))
                ) as r_cursor:
                    async for r_num, r_text in r_cursor:
                        text += f"{ch_filter}.{r_num}. {r_text}\n"
                return await message.answer(text, parse_mode=ParseMode.HTML)

        else:
            text = "🌸 <b>Устав Сада:</b>\n\n"
            async with db.execute(
                "SELECT chapter_num, title FROM rules_chapters WHERE chat_id = ? ORDER BY chapter_num",
                (message.chat.id,)
            ) as c_cursor:
                chapters = await c_cursor.fetchall()
                if not chapters:
                    return await message.answer("🌸 Устав сада пока пуст.")

                for c_num, c_title in chapters:
                    text += f"<b>{c_num}. {c_title}</b>\n"
                    async with db.execute(
                        "SELECT rule_num, text FROM rules_items WHERE chat_id = ? AND chapter_num = ? ORDER BY rule_num",
                        (message.chat.id, c_num)
                    ) as r_cursor:
                        async for r_num, r_text in r_cursor:
                            text += f"{c_num}.{r_num}. {r_text}\n"
                    text += "\n"
            return await message.answer(text, parse_mode=ParseMode.HTML)

# --- РП-ники ---

@dp.message(F.text.re.match(r"^\+ник\s+(.+)$", re.IGNORECASE))
async def set_nickname(message: types.Message):
    match = re.match(r"^\+ник\s+(.+)$", message.text, re.IGNORECASE)
    new_nick = match.group(1).strip()
    
    target = await resolve_target_user(message)
    user_role = await get_user_role(message.chat.id, message.from_user.id)

    if target and target.id != message.from_user.id:
        if user_role < 1:
            return await message.answer("🌫 Меняют ники другим только модераторы (1+ уровень)!")
        target_user = target
    else:
        target_user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (chat_id, user_id, rp_name) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name = ?
        """, (message.chat.id, target_user.id, new_nick, new_nick))
        await db.commit()

    await message.answer(f"🌸 РП-ник для {target_user.mention_html()} установлен: <b>{new_nick}</b>", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^\-ник$", re.IGNORECASE))
async def reset_nickname(message: types.Message):
    target = await resolve_target_user(message)
    user_role = await get_user_role(message.chat.id, message.from_user.id)

    if target and target.id != message.from_user.id:
        if user_role < 1:
            return await message.answer("🌫 Сбрасывают ники другим только модераторы (1+ уровень)!")
        target_user = target
    else:
        target_user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET rp_name = NULL WHERE chat_id = ? AND user_id = ?",
            (message.chat.id, target_user.id)
        )
        await db.commit()

    await message.answer(f"🌸 РП-ник для {target_user.mention_html()} сброшен.", parse_mode=ParseMode.HTML)

# --- Управление кастомными РП-командами ---

@dp.message(F.text.re.match(r"^\+команда\s+(\S+)\s+(.+)$", re.IGNORECASE))
async def add_custom_cmd(message: types.Message):
    match = re.match(r"^\+команда\s+(\S+)\s+(.+)$", message.text, re.IGNORECASE)
    cmd_name = match.group(1).lower().strip()
    cmd_text = match.group(2).strip()

    if cmd_name in SYSTEM_RESERVED_WORDS:
        return await message.answer("🌫 Запрещено перекрывать служебные и системные команды!")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM custom_commands WHERE chat_id = ? AND cmd_name = ?", (message.chat.id, cmd_name)
        ) as cursor:
            if await cursor.fetchone():
                return await message.answer("🌫 Команда уже существует! Сначала удалите её: <code>-команда [название]</code>", parse_mode=ParseMode.HTML)

        await db.execute(
            "INSERT INTO custom_commands (chat_id, cmd_name, cmd_text) VALUES (?, ?, ?)",
            (message.chat.id, cmd_name, cmd_text)
        )
        await db.commit()

    await message.answer(f"🌸 РП-команда «<b>{cmd_name}</b>» создана!", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^\-команда\s+(\S+)$", re.IGNORECASE))
async def del_custom_cmd(message: types.Message):
    match = re.match(r"^\-команда\s+(\S+)$", message.text, re.IGNORECASE)
    cmd_name = match.group(1).lower().strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM custom_commands WHERE chat_id = ? AND cmd_name = ?", (message.chat.id, cmd_name)
        )
        await db.commit()

    await message.answer(f"🌸 РП-команда «<b>{cmd_name}</b>» удалена.", parse_mode=ParseMode.HTML)

@dp.message(F.text.re.match(r"^(список команд|команды|рп команды)$", re.IGNORECASE))
async def list_custom_cmds(message: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT cmd_name FROM custom_commands WHERE chat_id = ?", (message.chat.id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.answer("🌈 В этом чате пока нет кастомных РП-команд.")

    cmds = ", ".join([f"<code>{r[0]}</code>" for r in rows])
    await message.answer(f"🌈 <b>Кастомные РП-команды чата:</b>\n{cmds}", parse_mode=ParseMode.HTML)

# --- Обработка кастомных РП-команд (ФОЛЛБЕК — стоит НИЖЕ системных команд) ---

@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def process_custom_rp(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    chat_id = message.chat.id
    first_word = text.split()[0].lower()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT cmd_text FROM custom_commands WHERE chat_id = ? AND cmd_name = ?",
            (chat_id, first_word)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                template = row[0]
                caller_name = await get_display_name(chat_id, message.from_user)
                
                reply_name = "Никто"
                reply_msg = ""
                if message.reply_to_message and message.reply_to_message.from_user:
                    reply_name = await get_display_name(chat_id, message.reply_to_message.from_user)
                    reply_msg = message.reply_to_message.text or ""

                random_name = "Случайный Гость"
                async with db.execute(
                    "SELECT user_id FROM users WHERE chat_id = ? ORDER BY RANDOM() LIMIT 1", (chat_id,)
                ) as r_cursor:
                    r_row = await r_cursor.fetchone()
                    if r_row:
                        try:
                            r_member = await bot.get_chat_member(chat_id, r_row[0])
                            random_name = await get_display_name(chat_id, r_member.user)
                        except Exception:
                            pass

                res_text = template.format(
                    Username=caller_name,
                    Reply=reply_name,
                    Reply_message=reply_msg,
                    Random=random_name
                )
                await message.answer(f"🌈 {res_text}", parse_mode=ParseMode.HTML)

# --- Выгрузка бэкапа в JSON ---

async def export_db_to_dict() -> dict:
    """Извлекает всю информацию из SQLite и формирует словарь для JSON."""
    data = {}
    tables = ["users", "roles_custom", "rules_chapters", "rules_items", "custom_commands", "cmd_levels"]
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for table in tables:
            async with db.execute(f"SELECT * FROM {table}") as cursor:
                rows = await cursor.fetchall()
                data[table] = [dict(row) for row in rows]
                
    return data

@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    if not STORAGE_GROUP_ID or str(message.chat.id) != str(STORAGE_GROUP_ID).strip():
        return

    try:
        chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status != ChatMemberStatus.CREATOR:
            return await message.answer("🌫 Команду бэкапа может вызывать только Создатель группы!")
    except Exception:
        return

    msg = await message.answer("🔄 Выгружаю бэкап данных...")
    backup_filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    try:
        data = await export_db_to_dict()
        with open(backup_filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        document = FSInputFile(backup_filename)
        await message.answer_document(
            document=document,
            caption=f"📦 <b>Бэкап данных Сада успешно сформирован!</b>\n📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            parse_mode=ParseMode.HTML
        )
        await msg.delete()

    except Exception as e:
        await message.answer(f"⚠️ Ошибка при формировании бэкапа: <code>{e}</code>", parse_mode=ParseMode.HTML)

    finally:
        if os.path.exists(backup_filename):
            os.remove(backup_filename)

# --- Запуск бота ---

async def main():
    await init_db()
    
    # Подключаем middleware учета активности
    dp.message.outer_middleware(ActivityMiddleware())
    
    logging.basicConfig(level=logging.INFO)
    print("🌸 Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
