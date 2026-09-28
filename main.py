import asyncio
import logging
import re
import sqlite3
import itertools
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatPermissions
from aiogram.enums import ParseMode

# ==========================================
# 1. НАСТРОЙКИ И ИНИЦИАЛИЗАЦИЯ
# ==========================================
BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА_ЗДЕСЬ"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключение к SQLite
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

def db_query(query: str, params: tuple = (), commit: bool = False):
    try:
        cursor.execute(query, params)
        if commit:
            conn.commit()
        return cursor.fetchall()
    except Exception as e:
        logging.error(f"Ошибка БД: {e}")
        return None

# Инициализация таблиц
db_query("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    level INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
""", commit=True)

db_query("""
CREATE TABLE IF NOT EXISTS cmd_levels (
    chat_id INTEGER,
    cmd_name TEXT,
    min_lvl INTEGER,
    PRIMARY KEY (chat_id, cmd_name)
);
""", commit=True)

db_query("""
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id INTEGER,
    user_id INTEGER,
    first_name TEXT,
    PRIMARY KEY (chat_id, user_id)
);
""", commit=True)

# Дефолтные уровни доступа для команд
DEFAULT_CMD_LEVELS = {
    "калл": 0,                   # Все
    "клиновый сироп": 1,        # Хелпер
    "напоить сиропом": 1,       # Хелпер
    "дать воды": 1,             # Хелпер
    "дать плод всей боли": 2,   # Модератор
    "в банку": 2,               # Модератор
    "сменить": 3,               # Админ / Создатель
}

LEVEL_NAMES = {
    0: "Все участники",
    1: "Хелпер+",
    2: "Модератор+",
    3: "Администратор+",
    4: "Создатель"
}

# Список эмодзи для подсвечивания вызова в калл
CALL_EMOJIS = ["🌸", "☁️", "👁", "🐍", "🌫", "🥛", "🫗", "🍨", "🍧", "🌈", "🍇", "🫙"]

# ==========================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_user_level(chat_id: int, user_id: int) -> int:
    res = db_query("SELECT level FROM users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    if res and res[0][0] is not None:
        return res[0][0]
    return 0

def get_required_level(chat_id: int, cmd_name: str) -> int:
    cmd_clean = cmd_name.strip().lower()
    res = db_query("SELECT min_lvl FROM cmd_levels WHERE chat_id = ? AND cmd_name = ?", (chat_id, cmd_clean))
    if res and res[0][0] is not None:
        return res[0][0]
    return DEFAULT_CMD_LEVELS.get(cmd_clean, 0)

def track_user(chat_id: int, user_id: int, first_name: str):
    if user_id and not user_id == bot.id:
        db_query("""
            INSERT INTO chat_members (chat_id, user_id, first_name) 
            VALUES (?, ?, ?) 
            ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name = excluded.first_name;
        """, (chat_id, user_id, first_name), commit=True)

def parse_duration_and_reason(args_text: str):
    """
    Разбирает аргументы вида: [число] [единица_времени] [причина]
    Если единица времени опущена — по умолчанию минуты.
    """
    if not args_text or not args_text.strip():
        return 10, "Не указана"

    pattern = r"^(\d+)\s*([a-zA-яa-zA-Z]+)?(?:\s+(.*))?$"
    match = re.match(pattern, args_text.strip())

    if not match:
        return 10, args_text.strip()

    num = int(match.group(1))
    unit_raw = match.group(2)
    reason = match.group(3)

    time_units = {
        "м": 1, "мин": 1, "минута": 1, "минуты": 1, "минут": 1,
        "ч": 60, "час": 60, "часа": 60, "часов": 60,
        "д": 1440, "дн": 1440, "день": 1440, "дня": 1440, "дней": 1440,
        "н": 10080, "нед": 10080, "неделя": 10080, "недели": 10080, "недель": 10080
    }

    if unit_raw:
        unit_lower = unit_raw.lower()
        if unit_lower in time_units:
            minutes = num * time_units[unit_lower]
            final_reason = reason if reason else "Не указана"
            return minutes, final_reason
        else:
            combined_reason = f"{unit_raw} {reason}".strip() if reason else unit_raw
            return num, combined_reason
    else:
        return num, "Не указана"

async def check_access(m: Message, cmd_name: str) -> bool:
    req_lvl = get_required_level(m.chat.id, cmd_name)
    user_lvl = get_user_level(m.chat.id, m.from_user.id)
    if user_lvl < req_lvl:
        await m.answer(f"🌫 Недостаточно уровня допуска! Требуется уровень: {req_lvl} ({LEVEL_NAMES.get(req_lvl, '')}).")
        return False
    return True

# ==========================================
# 3. ХЭНДЛЕРЫ КОМАНД МОДЕРАЦИИ И УПРАВЛЕНИЯ
# ==========================================

# Сменить уровень доступа команды
@dp.message(F.text.lower().startswith("сменить"))
async def change_cmd_level_handler(m: Message):
    if not await check_access(m, "сменить"):
        return

    pattern = r"^сменить\s*\((.+?)\)\s*(\d+)$"
    match = re.search(pattern, m.text.strip(), re.IGNORECASE)

    if not match:
        return await m.answer("🫗 Неверный формат команды!\nПример: `сменить (калл) 1` или `сменить (дать плод всей боли) 4`", parse_mode=ParseMode.MARKDOWN)

    cmd_target = match.group(1).strip().lower()
    new_lvl = int(match.group(2))

    if not (0 <= new_lvl <= 4):
        return await m.answer("🫗 Уровень доступа должен быть от 0 до 4!")

    db_query("""
        INSERT INTO cmd_levels (chat_id, cmd_name, min_lvl) 
        VALUES (?, ?, ?) 
        ON CONFLICT(chat_id, cmd_name) DO UPDATE SET min_lvl = excluded.min_lvl;
    """, (m.chat.id, cmd_target, new_lvl), commit=True)

    await m.answer(f"🌸 Уровень допуска для команды ({cmd_target}) изменён на {new_lvl} ({LEVEL_NAMES[new_lvl]}).")

# Команда Созыва (калл)
@dp.message(F.text.lower().startswith("калл"))
async def call_all_handler(m: Message):
    if not await check_access(m, "калл"):
        return

    members = db_query("SELECT user_id FROM chat_members WHERE chat_id = ?", (m.chat.id,))
    if not members:
        return await m.answer("🫙 В базе данных ещё нет записанных участников!")

    call_reason = m.text[4:].strip()
    header = f"🌈 Общий сбор!\nПричина: {call_reason}\n\n" if call_reason else "🌈 Общий сбор!\n\n"

    mentions = []
    emoji_cycle = itertools.cycle(CALL_EMOJIS)

    for (uid,) in members:
        emoji = next(emoji_cycle)
        mentions.append(f'<a href="tg://user?id={uid}">{emoji}</a>')

    # Отправляем блоками по 50 человек, чтобы не превысить лимит длины сообщения
    chunk_size = 50
    for i in range(0, len(mentions), chunk_size):
        chunk = mentions[i:i + chunk_size]
        text = header + " ".join(chunk) if i == 0 else " ".join(chunk)
        await m.answer(text, parse_mode=ParseMode.HTML)

# Мут (Напоить сиропом / Клиновый сироп / Дать воды)
@dp.message(F.text.lower().startswith(("напоить сиропом", "клиновый сироп", "дать воды")))
async def mute_handler(m: Message):
    cmd_name = "напоить сиропом"
    if not await check_access(m, cmd_name):
        return

    if not m.reply_to_message:
        return await m.answer("🫗 Ответьте этой командой на сообщение пользователя, которого нужно напоить сиропом!")

    target_user = m.reply_to_message.from_user
    args = re.sub(r"^(напоить сиропом|клиновый сироп|дать воды)", "", m.text, flags=re.IGNORECASE).strip()

    minutes, reason = parse_duration_and_reason(args)

    try:
        until_date = int(m.date.timestamp()) + (minutes * 60)
        await m.chat.restrict(
            user_id=target_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await m.answer(f"🥛 Пользователь {target_user.first_name} отправлен молчать на {minutes} мин.\nПричина: {reason}")
    except Exception as e:
        await m.answer(f"👁 Не удалось ограничить пользователя: {e}")

# Бан (Дать плод всей боли)
@dp.message(F.text.lower().startswith("дать плод всей боли"))
async def ban_handler(m: Message):
    if not await check_access(m, "дать плод всей боли"):
        return

    if not m.reply_to_message:
        return await m.answer("🫗 Ответьте этой командой на сообщение пользователя!")

    target_user = m.reply_to_message.from_user
    reason = m.text[19:].strip() or "Не указана"

    try:
        await m.chat.ban(user_id=target_user.id)
        await m.answer(f"🍇 Пользователь {target_user.first_name} вкусил плод всей боли и изгнан.\nПричина: {reason}")
    except Exception as e:
        await m.answer(f"👁 Не удалось забанить пользователя: {e}")

# Кик (В банку)
@dp.message(F.text.lower().startswith("в банку"))
async def kick_handler(m: Message):
    if not await check_access(m, "в банку"):
        return

    if not m.reply_to_message:
        return await m.answer("🫗 Ответьте этой командой на сообщение пользователя!")

    target_user = m.reply_to_message.from_user

    try:
        await m.chat.ban(user_id=target_user.id)
        await m.chat.unban(user_id=target_user.id)
        await m.answer(f"🫙 Пользователь {target_user.first_name} запечатан в банку и исключен из чата.")
    except Exception as e:
        await m.answer(f"👁 Не удалось исключить пользователя: {e}")

# ==========================================
# 4. ОСНОВНОЙ ТРЕКЕР СООБЩЕНИЙ (ФОН)
# ==========================================
@dp.message()
async def global_message_tracker(m: Message):
    if m.chat.type in ["group", "supergroup"] and m.from_user:
        # Автоматически фиксируем активных участников для работы команды 'калл'
        track_user(m.chat.id, m.from_user.id, m.from_user.first_name)

# ==========================================
# 5. ЗАПУСК БОТА
# ==========================================
async def main():
    logging.basicConfig(level=logging.INFO)
    print("🌸 Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
