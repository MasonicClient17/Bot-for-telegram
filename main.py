from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatPermissions, Message
from aiogram.enums import ChatMemberStatus
import os

TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН_ОТ_BOTFATHER")

bot = Bot(token=TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            msg_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            chat_id INTEGER,
            user_id INTEGER,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER,
            command_name TEXT,
            response_text TEXT,
            PRIMARY KEY (chat_id, command_name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

async def is_admin(message: Message) -> bool:
    if message.chat.type in ["private"]:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]

def check_reset_weekly():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    today = datetime.now()
    current_week = f"{today.year}-{today.isocalendar()[1]}"
    
    cursor.execute("SELECT value FROM system_state WHERE key = 'last_week'")
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO system_state (key, value) VALUES ('last_week', ?)", (current_week,))
        conn.commit()
    elif row[0] != current_week:
        cursor.execute("UPDATE stats SET msg_count = 0")
        cursor.execute("UPDATE system_state SET value = ? WHERE key = 'last_week'", (current_week,))
        conn.commit()
    
    conn.close()

async def scheduler():
    while True:
        check_reset_weekly()
        await asyncio.sleep(3600)

def parse_time(time_str: str) -> tuple[int, str]:
    if not time_str:
        return 60, "60 мин."
    
    match = re.match(r"^(\d+)\s*([a-zA-Zа-яА-Я]+)?$", time_str.strip())
    if not match:
        return 60, "60 мин."
    
    num = int(match.group(1))
    unit = match.group(2).lower() if match.group(2) else "м"
    
    if unit in ["с", "сек", "s", "sec"]:
        return max(1, num // 60), f"{num} сек."
    elif unit in ["м", "мин", "m", "min"]:
        return num, f"{num} мин."
    elif unit in ["ч", "час", "часов", "h", "hour"]:
        return num * 60, f"{num} час."
    elif unit in ["д", "день", "дней", "d", "day"]:
        return num * 1440, f"{num} дн."
    elif unit in ["н", "неделя", "недель", "w", "week"]:
        return num * 10080, f"{num} нед."
    elif unit in ["мес", "месяц", "месяцев"]:
        return num * 43200, f"{num} мес."
    
    return num, f"{num} мин."

@dp.message(F.text)
async def process_all_messages(message: Message):
    if message.chat.type in ["private"]:
        return

    check_reset_weekly()

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO stats (chat_id, user_id, username, full_name, msg_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            msg_count = msg_count + 1,
            username = excluded.username,
            full_name = excluded.full_name
    """, (
        message.chat.id,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    ))
    conn.commit()

    text = message.text.strip()
    lower_text = text.lower()
    sender_name = message.from_user.full_name

    if lower_text in ["банка с джемом", "в банку"]:
        if await is_admin(message) and message.reply_to_message:
            target = message.reply_to_message.from_user
            try:
                await message.chat.ban(user_id=target.id)
                await message.answer(f"{sender_name} отправил(а) {target.full_name} в банку с джемом.")
            except Exception as e:
                await message.answer(f"Ошибка: {e}")
        conn.close()
        return

    if lower_text == "дать плод всей боли":
        if await is_admin(message) and message.reply_to_message:
            target = message.reply_to_message.from_user
            until_date = datetime.now() + timedelta(days=1)
            try:
                await message.chat.restrict(
                    user_id=target.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                await message.answer(f"{sender_name} напоил(а) клиновым сиропом {target.full_name}. Теперь он(а) не сможет говорить 1 дн.!")
            except Exception as e:
                await message.answer(f"Ошибка: {e}")
        conn.close()
        return

    mute_match = re.match(r"^(напоить клиновым сиропом|напоить сиропом|клиновый сироп)(?:\s+(.*))?$", lower_text)
    if mute_match:
        if await is_admin(message) and message.reply_to_message:
            target = message.reply_to_message.from_user
            time_arg = mute_match.group(2)
            minutes, time_str = parse_time(time_arg)
            until_date = datetime.now() + timedelta(minutes=minutes)
            try:
                await message.chat.restrict(
                    user_id=target.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                await message.answer(f"{sender_name} напоил(а) клиновым сиропом {target.full_name}. Теперь он(а) не сможет говорить {time_str}!")
            except Exception as e:
                await message.answer(f"Ошибка: {e}")
        conn.close()
        return

    if lower_text == "дать воды":
        if await is_admin(message) and message.reply_to_message:
            target = message.reply_to_message.from_user
            try:
                await message.chat.restrict(
                    user_id=target.id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
                await message.answer(f"{target.full_name} дали воды, теперь он(а) может говорить. С возвращением!")
            except Exception as e:
                await message.answer(f"Ошибка: {e}")
        conn.close()
        return

    unban_match = re.match(r"^вытащить из банки\s+(.+)$", lower_text)
    if unban_match:
        if await is_admin(message):
            target_username = unban_match.group(1).lstrip("@")
            cursor.execute("SELECT user_id, full_name FROM stats WHERE chat_id = ? AND LOWER(username) = ?", (message.chat.id, target_username.lower()))
            row = cursor.fetchone()
            if row:
                target_id, target_name = row
                try:
                    await message.chat.unban(user_id=target_id)
                    await message.answer(f"{target_name} вытащили из банки с джемом. С возвращением!")
                except Exception as e:
                    await message.answer(f"Ошибка: {e}")
            else:
                await message.answer("Пользователь не найден в базе чата.")
        conn.close()
        return

    warn_match = re.match(r"^(варн|отругать)(?:\s+(.*))?$", lower_text)
    if warn_match:
        if await is_admin(message) and message.reply_to_message:
            target = message.reply_to_message.from_user
            cursor.execute("INSERT INTO warns (chat_id, user_id, warn_count) VALUES (?, ?, 1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count = warn_count + 1", (message.chat.id, target.id))
            conn.commit()
            cursor.execute("SELECT warn_count FROM warns WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id))
            warns = cursor.fetchone()[0]
            await message.answer(f"{sender_name} отругал(а) {target.full_name}! [Варнов: {warns}/3]")
            if warns >= 3:
                try:
                    await message.chat.ban(user_id=target.id)
                    cursor.execute("UPDATE warns SET warn_count = 0 WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id))
                    conn.commit()
                    await message.answer(f"{target.full_name} набрал(а) 3 варна и отправляется в банку с джемом!")
                except Exception as e:
                    await message.answer(f"Ошибка: {e}")
        conn.close()
        return

    if lower_text in ["актив", "стата", "статистика"]:
        if await is_admin(message):
            cursor.execute("SELECT full_name, username, msg_count FROM stats WHERE chat_id = ? ORDER BY msg_count DESC LIMIT 20", (message.chat.id,))
            rows = cursor.fetchall()
            if not rows:
                await message.answer("Статистика за эту неделю пока пуста.")
            else:
                text_res = "📊 **Статистика сообщений за неделю:**\n\n"
                for idx, (full_name, username, count) in enumerate(rows, 1):
                    user_str = f"@{username}" if username else full_name
                    text_res += f"{idx}. {user_str} — {count} сообщ.\n"
                await message.answer(text_res, parse_mode="Markdown")
        conn.close()
        return

    cmd_name = lower_text.split()[0]
    cursor.execute("SELECT response_text FROM custom_commands WHERE chat_id = ? AND command_name = ?", (message.chat.id, cmd_name))
    row = cursor.fetchone()
    if row:
        await message.answer(row[0])

    conn.close()

async def main():
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
