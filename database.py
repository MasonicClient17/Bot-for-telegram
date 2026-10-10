import aiosqlite
import json
import logging
import io
from datetime import datetime
from aiogram.types import BufferedInputFile
from config import DB_FILE, STORAGE_CHAT_ID, bot

async def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False, return_lastrowid=False):
    async with aiosqlite.connect(DB_FILE, timeout=10.0) as conn:
        async with conn.execute(sql, params) as cursor:
            if commit:
                await conn.commit()
            if return_lastrowid:
                return cursor.lastrowid
            if fetchone:
                return await cursor.fetchone()
            if fetchall:
                return await cursor.fetchall()

async def init_db():
    queries = [
        "CREATE TABLE IF NOT EXISTS users (chat_id INT, user_id INT, role_level INT DEFAULT 0, warns INT DEFAULT 0, msg_count INT DEFAULT 0, rp_name TEXT, day_count INT DEFAULT 0, week_count INT DEFAULT 0, last_msg_date TEXT, week_number TEXT, joined_at TEXT, tapes INT DEFAULT 0, status TEXT, rep INT DEFAULT 0, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS custom_commands (chat_id INT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name))",
        "CREATE TABLE IF NOT EXISTS mod_roles (chat_id INT, user_id INT, role_level INT DEFAULT 0, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS role_names (chat_id INT PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ')",
        "CREATE TABLE IF NOT EXISTS cmd_levels (chat_id INT, cmd_name TEXT, min_lvl INT, PRIMARY KEY (chat_id, cmd_name))",
        "CREATE TABLE IF NOT EXISTS rules (chat_id INT, section INT, item INT, title TEXT, content TEXT, PRIMARY KEY (chat_id, section, item))",
        "CREATE TABLE IF NOT EXISTS chat_members (chat_id INT, user_id INT, first_name TEXT, username TEXT, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS welcome_messages (chat_id INT PRIMARY KEY, welcome_text TEXT)",
        "CREATE TABLE IF NOT EXISTS user_tags (chat_id INT, user_id INT, tag_name TEXT, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS inventory (chat_id INT, user_id INT, item_name TEXT, count INT DEFAULT 1, PRIMARY KEY (chat_id, user_id, item_name))",
        "CREATE TABLE IF NOT EXISTS merchant_catalog (chat_id INT, item_name TEXT PRIMARY KEY, price INT)",
        "CREATE TABLE IF NOT EXISTS marriages (chat_id INT, user1_id INT, user2_id INT, date TEXT, PRIMARY KEY (chat_id, user1_id, user2_id))",
        "CREATE TABLE IF NOT EXISTS quizzes (quiz_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INT, message_id INT, creator_id INT, question TEXT, correct_answer TEXT, is_active INT DEFAULT 1, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS quiz_answers (quiz_id INT, user_id INT, is_correct INT, PRIMARY KEY (quiz_id, user_id))",
        "CREATE TABLE IF NOT EXISTS chat_norms (chat_id INT PRIMARY KEY, min_messages INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS dynamic_phrases (chat_id INT, key_name TEXT, text_value TEXT, PRIMARY KEY (chat_id, key_name))",
        "CREATE TABLE IF NOT EXISTS dynamic_commands (chat_id INT, action_key TEXT, cmd_name TEXT, PRIMARY KEY (chat_id, action_key))",
        "CREATE TABLE IF NOT EXISTS daily_cookies (chat_id INT, user_id INT, last_date TEXT, PRIMARY KEY (chat_id, user_id))"
    ]
    for q in queries:
        await db_query(q, commit=True)
    
    # Авто-миграция колонок users на случай старой локальной БД
    cols_data = await db_query("PRAGMA table_info(users)", fetchall=True)
    cols = [r[1] for r in cols_data] if cols_data else []
    for col, col_type in [("status", "TEXT"), ("rep", "INT DEFAULT 0")]:
        if col not in cols:
            await db_query(f"ALTER TABLE users ADD COLUMN {col} {col_type}", commit=True)

DEFAULT_PHRASES = {
    "profile_title": "🌿 <b>Уютный профиль участника {user}</b>",
    "welcome_text": "🌿 Приветствие успешно обновлено!",
    "norm_set": "☕ Установлена минимальная недельная норма сообщений: <b>{val}</b>",
    "cookie_get": "🍪 Вы получили печеньку с предсказанием и <b>{tapes}</b> 📼 кассет!\n\n💬 <i>«{text}»</i>",
    "cookie_cooldown": "⏳ Вы уже открывали печеньку сегодня. Загляните завтра!",
}

DEFAULT_CMDS = {
    "ban": "удалить",
    "mute": "-звук",
    "unmute": "+звук",
    "warn": "варн",
    "unwarn": "разварн"
}

async def get_text(chat_id: int, key: str, **kwargs) -> str:
    res = await db_query("SELECT text_value FROM dynamic_phrases WHERE chat_id=? AND key_name=?", (chat_id, key), fetchone=True)
    text = res[0] if res else DEFAULT_PHRASES.get(key, f"[{key}]")
    return text.format(**kwargs)

async def get_cmd_name(chat_id: int, action_key: str) -> str:
    res = await db_query("SELECT cmd_name FROM dynamic_commands WHERE chat_id=? AND action_key=?", (chat_id, action_key), fetchone=True)
    return res[0] if res else DEFAULT_CMDS.get(action_key, action_key)

async def backup_to_telegram():
    if not STORAGE_CHAT_ID:
        return logging.warning("[STORAGE] STORAGE_CHAT_ID не задан!")
    data = {
        "rules": await db_query("SELECT chat_id, section, item, title, content FROM rules", fetchall=True),
        "custom_commands": await db_query("SELECT chat_id, command_name, response_text FROM custom_commands", fetchall=True),
        "users": await db_query("SELECT chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes, status, rep FROM users", fetchall=True),
        "mod_roles": await db_query("SELECT chat_id, user_id, role_level FROM mod_roles", fetchall=True),
        "cmd_levels": await db_query("SELECT chat_id, cmd_name, min_lvl FROM cmd_levels", fetchall=True),
        "welcome": await db_query("SELECT chat_id, welcome_text FROM welcome_messages", fetchall=True),
        "user_tags": await db_query("SELECT chat_id, user_id, tag_name FROM user_tags", fetchall=True),
        "chat_members": await db_query("SELECT chat_id, user_id, first_name, username FROM chat_members", fetchall=True),
        "inventory": await db_query("SELECT chat_id, user_id, item_name, count FROM inventory", fetchall=True),
        "merchant_catalog": await db_query("SELECT chat_id, item_name, price FROM merchant_catalog", fetchall=True),
        "marriages": await db_query("SELECT chat_id, user1_id, user2_id, date FROM marriages", fetchall=True),
        "quizzes": await db_query("SELECT quiz_id, chat_id, message_id, creator_id, question, correct_answer, is_active, created_at FROM quizzes", fetchall=True),
        "quiz_answers": await db_query("SELECT quiz_id, user_id, is_correct FROM quiz_answers", fetchall=True),
        "chat_norms": await db_query("SELECT chat_id, min_messages FROM chat_norms", fetchall=True),
        "dynamic_phrases": await db_query("SELECT chat_id, key_name, text_value FROM dynamic_phrases", fetchall=True),
        "dynamic_commands": await db_query("SELECT chat_id, action_key, cmd_name FROM dynamic_commands", fetchall=True)
    }
    file = BufferedInputFile(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'), filename="backup.json")
    try:
        msg = await bot.send_document(STORAGE_CHAT_ID, document=file, caption=f"🌿 <b>Бэкап БД</b> | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        await bot.pin_chat_message(STORAGE_CHAT_ID, msg.message_id, disable_notification=True)
        logging.info("[STORAGE] Бэкап отправлен!")
    except Exception as e:
        logging.error(f"[STORAGE] Ошибка бэкапа: {e}")

async def restore_from_telegram():
    if not STORAGE_CHAT_ID:
        return
    try:
        chat = await bot.get_chat(STORAGE_CHAT_ID)
        if not chat.pinned_message or not chat.pinned_message.document:
            return
        finfo = await bot.get_file(chat.pinned_message.document.file_id)
        downloaded = await bot.download_file(finfo.file_path)
        content = downloaded.getvalue().decode('utf-8') if isinstance(downloaded, io.BytesIO) else downloaded.read().decode('utf-8')
        data = json.loads(content)

        # Безопасное восстановление: совместимо как со старым бэкапом (12 полей), так и с новым (14 полей)
        for u in data.get("users", []):
            if len(u) == 12:
                u_tuple = tuple(u) + (None, 0)
            elif len(u) == 13:
                u_tuple = tuple(u) + (0,)
            else:
                u_tuple = tuple(u[:14])

            await db_query(
                "INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes, status, rep) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                u_tuple,
                commit=True
            )

        for inv in data.get("inventory", []):
            await db_query("INSERT OR REPLACE INTO inventory VALUES (?,?,?,?)", tuple(inv), commit=True)
        for mc in data.get("merchant_catalog", []):
            await db_query("INSERT OR REPLACE INTO merchant_catalog VALUES (?,?,?)", tuple(mc), commit=True)
        for dp in data.get("dynamic_phrases", []):
            await db_query("INSERT OR REPLACE INTO dynamic_phrases VALUES (?,?,?)", tuple(dp), commit=True)
        for dc in data.get("dynamic_commands", []):
            await db_query("INSERT OR REPLACE INTO dynamic_commands VALUES (?,?,?)", tuple(dc), commit=True)
            
        logging.info("[RESTORE] Данные из бэкапа успешно восстановлены!")
    except Exception as e:
        logging.error(f"[RESTORE] Ошибка восстановления: {e}")
        
