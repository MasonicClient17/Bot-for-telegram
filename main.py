import asyncio
import logging
import re
import sqlite3
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatPermissions, Message

# Настройка логирования
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных SQLite
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Таблица активности пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            message_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    
    # Таблица варнов (предупреждений)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warn_system (
            chat_id INTEGER,
            user_id INTEGER,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    
    # Таблица кастомных РП-команд
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER,
            command_name TEXT,
            response_text TEXT,
            PRIMARY KEY (chat_id, command_name)
        )
    """)
    
    conn.commit()
    conn.close()

init_db()


# Проверка, является ли пользователь администратором
async def is_admin(message: Message) -> bool:
    if message.chat.type in ["private"]:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ["administrator", "creator"]


# Вспомогательная функция для парсинга времени мута
def parse_time(time_str: str):
    if not time_str:
        return 60, "60 мин."
    
    match = re.match(r"^(\d+)\s*(мин|мин.|минут|минуты|ч|час|часа|часов|д|ден|день|дня|дней)?$", time_str.lower().strip())
    if not match:
        return 60, "60 мин."
    
    num = int(match.group(1))
    unit = match.group(2)
    
    if unit in ["ч", "час", "часа", "часов"]:
        return num * 60, f"{num} ч."
    elif unit in ["д", "ден", "день", "дня", "дней"]:
        return num * 1440, f"{num} дн."
    else:
        return num, f"{num} мин."


# === ДОБАВЛЕНИЕ КАСТОМНЫХ РП-КОМАНД ===
@dp.message(F.text.startswith("+комманда") | F.text.startswith("+команда"))
async def add_custom_command(message: Message):
    if not await is_admin(message):
        return
    
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Использование: `+команда [название] [текст ответа]`\n\n"
            "**Доступные переменные:**\n"
            "• `{Username}` — имя отправителя\n"
            "• `{Reply}` — имя того, кому ответили\n"
            "• `{Reply_message}` — текст исходного сообщения", 
            parse_mode="Markdown"
        )
        return
    
    cmd_name = parts[1].lower()
    response_text = parts[2]
    
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custom_commands (chat_id, command_name, response_text)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, command_name) DO UPDATE SET response_text = excluded.response_text
    """, (message.chat.id, cmd_name, response_text))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Команда `{cmd_name}` успешно сохранена!", parse_mode="Markdown")


# === УДАЛЕНИЕ КАСТОМНЫХ РП-КОМАНД ===
@dp.message(F.text.startswith("-комманда") | F.text.startswith("-команда"))
async def delete_custom_command(message: Message):
    if not await is_admin(message):
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `-команда [название]`", parse_mode="Markdown")
        return
    
    cmd_name = parts[1].lower().strip()
    
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM custom_commands WHERE chat_id = ? AND command_name = ?",
        (message.chat.id, cmd_name)
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted > 0:
        await message.answer(f"🗑 Команда `{cmd_name}` удалена!", parse_mode="Markdown")
    else:
        await message.answer(f"⚠️ Команда `{cmd_name}` не найдена.", parse_mode="Markdown")


# === СПИСОК ВСЕХ КАСТОМНЫХ РП-КОМАНД ===
@dp.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_custom_commands(message: Message):
    if message.chat.type in ["private"]:
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT command_name FROM custom_commands WHERE chat_id = ? ORDER BY command_name ASC",
        (message.chat.id,)
    )
    commands = cursor.fetchall()
    conn.close()

    if not commands:
        await message.answer("📝 В этом чате пока нет созданных кастомных команд.")
        return

    cmd_list = "\n".join([f"• `{cmd[0]}`" for cmd in commands])
    await message.answer(
        f"📜 **Список кастомных РП-команд чата:**\n\n{cmd_list}",
        parse_mode="Markdown"
    )


# === ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ И КОМАНД ===
@dp.message(F.text)
async def process_all_messages(message: Message):
    if message.chat.type in ["private"]:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.lower().strip()

    # 1. Обновляем статистику сообщений пользователя
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_activity (chat_id, user_id, username, first_name, message_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            message_count = message_count + 1,
            username = excluded.username,
            first_name = excluded.first_name
    """, (chat_id, user_id, message.from_user.username, message.from_user.first_name))
    conn.commit()
    conn.close()

    # 2. Модерация (только для админов)
    if await is_admin(message):
        
        # БАН: "банка с джемом" или "в банку"
        if text in ["банка с джемом", "в банку"] and message.reply_to_message:
            target_user = message.reply_to_message.from_user
            try:
                await message.chat.ban(target_user.id)
                await message.answer(f"🫙 Пользователь {target_user.first_name} отправлен в банку с джемом (забанен)!")
            except Exception as e:
                await message.answer(f"Не удалось забанить пользователя: {e}")
            return

        # РАЗБАН ПО USERNAME: "вытащить из банки @username"
        elif text.startswith("вытащить из банки"):
            parts = text.split()
            if len(parts) > 3 and parts[3].startswith("@"):
                target_username = parts[3].replace("@", "")
                conn = sqlite3.connect("bot_database.db")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT user_id FROM user_activity WHERE chat_id = ? AND LOWER(username) = ?",
                    (chat_id, target_username.lower())
                )
                res = cursor.fetchone()
                conn.close()
                if res:
                    try:
                        await message.chat.unban(res[0])
                        await message.answer(f"🔓 Пользователь @{target_username} вытащен из банки (разбанен)!")
                    except Exception as e:
                        await message.answer(f"Не удалось разбанить: {e}")
                else:
                    await message.answer("Пользователь не найден в базе данных.")
            return

        # МУТ НА 1 ДЕНЬ: "дать плод всей боли"
        elif text == "дать плод всей боли" and message.reply_to_message:
            target_user = message.reply_to_message.from_user
            until_date = datetime.now() + timedelta(days=1)
            try:
                await message.chat.restrict(
                    target_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                await message.answer(f"🍎 {target_user.first_name} вкусил плод всей боли и замолк на 1 день.")
            except Exception as e:
                await message.answer(f"Не удалось выдать мут: {e}")
            return

        # НАСТРАИВАЕМЫЙ МУТ: "клиновый сироп [время]" / "напоить сиропом [время]"
        elif (text.startswith("клиновый сироп") or text.startswith("напоить сиропом")) and message.reply_to_message:
            target_user = message.reply_to_message.from_user
            time_part = text.replace("клиновый сироп", "").replace("напоить сиропом", "").strip()
            minutes, display_time = parse_time(time_part)
            until_date = datetime.now() + timedelta(minutes=minutes)
            try:
                await message.chat.restrict(
                    target_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                await message.answer(f"🍁 {target_user.first_name} напоен кленовым сиропом и молчит {display_time}.")
            except Exception as e:
                await message.answer(f"Не удалось выдать мут: {e}")
            return

        # СНЯТИЕ МУТА: "дать воды"
        elif text == "дать воды" and message.reply_to_message:
            target_user = message.reply_to_message.from_user
            try:
                await message.chat.restrict(
                    target_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
                await message.answer(f"💧 {target_user.first_name} получил воды и снова может говорить!")
            except Exception as e:
                await message.answer(f"Не удалось снять мут: {e}")
            return

        # ВАРН: "варн" или "отругать"
        elif text in ["варн", "отругать"] and message.reply_to_message:
            target_user = message.reply_to_message.from_user
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT warn_count FROM warn_system WHERE chat_id = ? AND user_id = ?",
                (chat_id, target_user.id)
            )
            res = cursor.fetchone()
            current_warns = (res[0] if res else 0) + 1

            if current_warns >= 3:
                cursor.execute(
                    "DELETE FROM warn_system WHERE chat_id = ? AND user_id = ?",
                    (chat_id, target_user.id)
                )
                conn.commit()
                conn.close()
                try:
                    await message.chat.ban(target_user.id)
                    await message.answer(f"🫙 {target_user.first_name} получил [3/3] варнов и отправлен в банку с джемом!")
                except Exception as e:
                    await message.answer(f"Не удалось забанить за варны: {e}")
            else:
                cursor.execute("""
                    INSERT INTO warn_system (chat_id, user_id, warn_count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count = excluded.warn_count
                """, (chat_id, target_user.id, current_warns))
                conn.commit()
                conn.close()
                await message.answer(f"⚠️ {target_user.first_name} получил предупреждение! [{current_warns}/3]")
            return

        # СТАТИСТИКА: "актив", "стата", "статистика"
        elif text in ["актив", "стата", "статистика"]:
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT first_name, message_count FROM user_activity WHERE chat_id = ? ORDER BY message_count DESC LIMIT 20",
                (chat_id,)
            )
            top_users = cursor.fetchall()
            conn.close()

            if not top_users:
                await message.answer("Статистика пока пуста.")
                return

            stat_msg = "📊 **ТОП-20 самых активных участников:**\n\n"
            for idx, (name, count) in enumerate(top_users, start=1):
                stat_msg += f"{idx}. {name} — {count} сообщ.\n"
            
            await message.answer(stat_msg, parse_mode="Markdown")
            return

    # 3. Проверка кастомных РП-команд (доступно всем участникам)
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT response_text FROM custom_commands WHERE chat_id = ? AND command_name = ?",
        (chat_id, text)
    )
    custom_cmd = cursor.fetchone()
    conn.close()

    if custom_cmd:
        template = custom_cmd[0]
        
        username = message.from_user.first_name if message.from_user else "Кто-то"
        reply_user_name = "кого-то"
        reply_msg_text = ""
        
        if message.reply_to_message:
            if message.reply_to_message.from_user:
                reply_user_name = message.reply_to_message.from_user.first_name
            if message.reply_to_message.text:
                reply_msg_text = message.reply_to_message.text
            elif message.reply_to_message.caption:
                reply_msg_text = message.reply_to_message.caption

        formatted_response = template.format(
            Username=username,
            Reply=reply_user_name,
            Reply_message=reply_msg_text
        )
        
        await message.answer(formatted_response)
        return


# === ЗАПУСК БОТА ===
async def main():
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
                                                
