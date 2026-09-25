import asyncio
import logging
import math
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

    # Таблица кастомных ников
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_nicknames (
            chat_id INTEGER,
            user_id INTEGER,
            nickname TEXT,
            PRIMARY KEY (chat_id, user_id)
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


# Вспомогательная функция для получения отображаемого имени (РП-ник или first_name)
def get_display_name(chat_id: int, user_id: int, default_name: str) -> str:
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nickname FROM custom_nicknames WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    )
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else default_name


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


# === УСТАНОВКА КАСТОМНОГО НИКА (+ник) ===
@dp.message(F.text.startswith("+ник"))
async def set_custom_nickname(message: Message):
    if message.chat.type in ["private"]:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `+ник [твой ник]`", parse_mode="Markdown")
        return

    new_nick = parts[1].strip()
    chat_id = message.chat.id

    # Если команда отправлена в ответ на сообщение другого пользователя
    if message.reply_to_message:
        if not await is_admin(message):
            await message.answer("⚠️ Менять ники другим участникам могут только администраторы.")
            return
        target_user = message.reply_to_message.from_user
    else:
        target_user = message.from_user

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custom_nicknames (chat_id, user_id, nickname)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET nickname = excluded.nickname
    """, (chat_id, target_user.id, new_nick))
    conn.commit()
    conn.close()

    await message.answer(
        f"🏷 РП-ник для {target_user.first_name} успешно изменён на: **{new_nick}**",
        parse_mode="Markdown"
    )


# === СБРОС КАСТОМНОГО НИКА (-ник) ===
@dp.message(F.text == "-ник")
async def remove_custom_nickname(message: Message):
    if message.chat.type in ["private"]:
        return

    chat_id = message.chat.id

    # Если ответ на сообщение — сбросить ник другому (только для админов)
    if message.reply_to_message:
        if not await is_admin(message):
            await message.answer("⚠️ Сбрасывать ники другим участникам могут только администраторы.")
            return
        target_user = message.reply_to_message.from_user
    else:
        # Иначе сбрасываем свой ник (доступно каждому)
        target_user = message.from_user

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM custom_nicknames WHERE chat_id = ? AND user_id = ?",
        (chat_id, target_user.id)
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted > 0:
        await message.answer(f"🗑 РП-ник пользователя {target_user.first_name} сброшен.")
    else:
        await message.answer(f"⚠️ У {target_user.first_name} не было установленного РП-ника.")


# === СПИСОК НИКНЕЙМОВ / ЗВАНИЙ (с пагинацией) ===
@dp.message(F.text.lower().startswith("ники") | F.text.lower().startswith("звания"))
async def list_custom_nicknames(message: Message):
    if message.chat.type in ["private"]:
        return

    parts = message.text.split()
    page = 1
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])

    if page < 1:
        page = 1

    chat_id = message.chat.id
    limit = 10
    offset = (page - 1) * limit

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Получаем общее количество сохранённых ников
    cursor.execute("SELECT COUNT(*) FROM custom_nicknames WHERE chat_id = ?", (chat_id,))
    total_count = cursor.fetchone()[0]

    if total_count == 0:
        conn.close()
        await message.answer("📝 В этом чате пока ни у кого нет кастомных РП-ников.")
        return

    total_pages = math.ceil(total_count / limit)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * limit

    # Выбираем ники для нужной страницы
    cursor.execute("""
        SELECT n.user_id, n.nickname, a.first_name 
        FROM custom_nicknames n
        LEFT JOIN user_activity a ON n.chat_id = a.chat_id AND n.user_id = a.user_id
        WHERE n.chat_id = ?
        ORDER BY n.nickname ASC
        LIMIT ? OFFSET ?
    """, (chat_id, limit, offset))
    
    nicknames = cursor.fetchall()
    conn.close()

    list_msg = f"🏷 **Кастомные ники чата (Страница {page}/{total_pages}):**\n\n"
    for idx, (uid, nick, original_name) in enumerate(nicknames, start=offset + 1):
        name_display = original_name if original_name else f"ID: {uid}"
        list_msg += f"{idx}. **{nick}** *(ориг: {name_display})*\n"

    list_msg += f"\n💡 _Используй `ники [номер страницы]` для навигации._"

    await message.answer(list_msg, parse_mode="Markdown")


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
            "• `{Username}` — РП-ник (или имя) отправителя\n"
            "• `{Reply}` — РП-ник (или имя) того, кому ответили\n"
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
        
        # Подтягиваем РП-ники (или стандартное имя, если ник не задан)
        user_first_name = message.from_user.first_name if message.from_user else "Кто-то"
        sender_name = get_display_name(chat_id, user_id, user_first_name)

        reply_user_name = "кого-то"
        reply_msg_text = ""
        
        if message.reply_to_message:
            if message.reply_to_message.from_user:
                r_user = message.reply_to_message.from_user
                reply_user_name = get_display_name(chat_id, r_user.id, r_user.first_name)
            if message.reply_to_message.text:
                reply_msg_text = message.reply_to_message.text
            elif message.reply_to_message.caption:
                reply_msg_text = message.reply_to_message.caption

        formatted_response = template.format(
            Username=sender_name,
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
        
