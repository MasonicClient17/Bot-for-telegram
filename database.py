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
        "CREATE TABLE IF NOT EXISTS users (chat_id INT, user_id INT, role_level INT DEFAULT 0, warns INT DEFAULT 0, msg_count INT DEFAULT 0, rp_name TEXT, day_count INT DEFAULT 0, week_count INT DEFAULT 0, last_msg_date TEXT, week_number TEXT, joined_at TEXT, tapes INT DEFAULT 0, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS custom_commands (chat_id INT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name))",
        "CREATE TABLE IF NOT EXISTS mod_roles (chat_id INT, user_id INT, role_level INT DEFAULT 0, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS role_names (chat_id INT PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ')",
        "CREATE TABLE IF NOT EXISTS cmd_levels (chat_id INT, cmd_name TEXT, min_lvl INT, PRIMARY KEY (chat_id, cmd_name))",
        "CREATE TABLE IF NOT EXISTS rules (chat_id INT, section INT, item INT, title TEXT, content TEXT, PRIMARY KEY (chat_id, section, item))",
        "CREATE TABLE IF NOT EXISTS chat_members (chat_id INT, user_id INT, first_name TEXT, username TEXT, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS welcome_messages (chat_id INT PRIMARY KEY, welcome_text TEXT)",
        "CREATE TABLE IF NOT EXISTS user_tags (chat_id INT, user_id INT, tag_name TEXT, PRIMARY KEY (chat_id, user_id))",
        "CREATE TABLE IF NOT EXISTS inventory (chat_id INT, user_id INT, item_name TEXT, count INT DEFAULT 1, PRIMARY KEY (chat_id, user_id, item_name))",
        "CREATE TABLE IF NOT EXISTS merchant_catalog (chat_id INT, item_name TEXT PRIMARY KEY, price INT, is_master_item INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS master_items (chat_id INT, item_name TEXT PRIMARY KEY, base_price INT)",
        "CREATE TABLE IF NOT EXISTS marriages (chat_id INT, user1_id INT, user2_id INT, date TEXT, PRIMARY KEY (chat_id, user1_id, user2_id))",
        "CREATE TABLE IF NOT EXISTS quizzes (quiz_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INT, message_id INT, creator_id INT, question TEXT, correct_answer TEXT, is_active INT DEFAULT 1, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS quiz_answers (quiz_id INT, user_id INT, is_correct INT, PRIMARY KEY (quiz_id, user_id))",
        "CREATE TABLE IF NOT EXISTS deliveries (delivery_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INT, dyle_user_id INT, item_name TEXT, count INT, cost INT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS chat_norms (chat_id INT PRIMARY KEY, min_messages INT DEFAULT 0)"
        
    ]
    for q in queries:
        await db_query(q, commit=True)
    
    cols_data = await db_query("PRAGMA table_info(users)", fetchall=True)
    cols = [r[1] for r in cols_data] if cols_data else []
    for col, col_type in [("day_count", "INT DEFAULT 0"), ("week_count", "INT DEFAULT 0"), ("last_msg_date", "TEXT"), ("week_number", "TEXT"), ("joined_at", "TEXT"), ("tapes", "INT DEFAULT 0")]:
        if col not in cols:
            await db_query(f"ALTER TABLE users ADD COLUMN {col} {col_type}", commit=True)

    master_defaults = [("Освобождение от нормы", 1000), ("Бессрочное бракосочетание", 100)]
    for iname, iprice in master_defaults:
        await db_query("INSERT OR IGNORE INTO master_items (chat_id, item_name, base_price) VALUES (0, ?, ?)", (iname, iprice), commit=True)

async def backup_to_telegram():
    if not STORAGE_CHAT_ID:
        return logging.warning("[STORAGE] STORAGE_CHAT_ID не задан!")
    data = {
        "rules": await db_query("SELECT chat_id, section, item, title, content FROM rules", fetchall=True),
        "custom_commands": await db_query("SELECT chat_id, command_name, response_text FROM custom_commands", fetchall=True),
        "users": await db_query("SELECT chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes FROM users", fetchall=True),
        "mod_roles": await db_query("SELECT chat_id, user_id, role_level FROM mod_roles", fetchall=True),
        "cmd_levels": await db_query("SELECT chat_id, cmd_name, min_lvl FROM cmd_levels", fetchall=True),
        "welcome": await db_query("SELECT chat_id, welcome_text FROM welcome_messages", fetchall=True),
        "user_tags": await db_query("SELECT chat_id, user_id, tag_name FROM user_tags", fetchall=True),
        "chat_members": await db_query("SELECT chat_id, user_id, first_name, username FROM chat_members", fetchall=True),
        "inventory": await db_query("SELECT chat_id, user_id, item_name, count FROM inventory", fetchall=True),
        "merchant_catalog": await db_query("SELECT chat_id, item_name, price, is_master_item FROM merchant_catalog", fetchall=True),
        "master_items": await db_query("SELECT chat_id, item_name, base_price FROM master_items", fetchall=True),
        "marriages": await db_query("SELECT chat_id, user1_id, user2_id, date FROM marriages", fetchall=True),
        "quizzes": await db_query("SELECT quiz_id, chat_id, message_id, creator_id, question, correct_answer, is_active, created_at FROM quizzes", fetchall=True),
        "quiz_answers": await db_query("SELECT quiz_id, user_id, is_correct FROM quiz_answers", fetchall=True),
        "deliveries": await db_query("SELECT delivery_id, chat_id, dyle_user_id, item_name, count, cost, created_at FROM deliveries", fetchall=True),
        "chat_norms": await db_query("SELECT chat_id, min_messages FROM chat_norms", fetchall=True)
    }
    file = BufferedInputFile(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'), filename="backup.json")
    try:
        msg = await bot.send_document(
            STORAGE_CHAT_ID,
            document=file,
            caption=f"📦 <b>Бэкап БД (Полный)</b> | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await bot.pin_chat_message(STORAGE_CHAT_ID, msg.message_id, disable_notification=True)
        except Exception as e:
            logging.warning(f"[STORAGE] Не удалось закрепить: {e}")
        logging.info("[STORAGE] Бэкап отправлен!")
    except Exception as e:
        logging.error(f"[STORAGE] Ошибка бэкапа: {e}")

async def restore_from_telegram():
    if not STORAGE_CHAT_ID:
        return logging.warning("[RESTORE] STORAGE_CHAT_ID не указан.")
    try:
        chat = await bot.get_chat(STORAGE_CHAT_ID)
        if not chat.pinned_message or not chat.pinned_message.document or chat.pinned_message.document.file_name != "backup.json":
            return
        
        finfo = await bot.get_file(chat.pinned_message.document.file_id)
        downloaded = await bot.download_file(finfo.file_path)
        
        if isinstance(downloaded, io.BytesIO):
            content = downloaded.getvalue().decode('utf-8')
        else:
            content = downloaded.read().decode('utf-8')

        data = json.loads(content)

        for r in data.get("rules", []): await db_query("INSERT OR REPLACE INTO rules VALUES (?,?,?,?,?)", tuple(r), commit=True)
        for c in data.get("custom_commands", []): await db_query("INSERT OR REPLACE INTO custom_commands VALUES (?,?,?)", tuple(c), commit=True)
        for u in data.get("users", []):
            if len(u) == 4:
                await db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name) VALUES (?,?,?,?)", tuple(u), commit=True)
            elif len(u) == 5:
                await db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns) VALUES (?,?,?,?,?)", tuple(u), commit=True)
            elif len(u) == 11:
                await db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(u[:11]), commit=True)
            elif len(u) >= 12:
                await db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", tuple(u[:12]), commit=True)
        for cl in data.get("cmd_levels", []): await db_query("INSERT OR REPLACE INTO cmd_levels VALUES (?,?,?)", tuple(cl), commit=True)
        for w in data.get("welcome", []): await db_query("INSERT OR REPLACE INTO welcome_messages VALUES (?,?)", tuple(w), commit=True)
        for ut in data.get("user_tags", []): await db_query("INSERT OR REPLACE INTO user_tags VALUES (?,?,?)", tuple(ut), commit=True)
        for cm in data.get("chat_members", []): await db_query("INSERT OR REPLACE INTO chat_members VALUES (?,?,?,?)", tuple(cm), commit=True)
        for inv in data.get("inventory", []): await db_query("INSERT OR REPLACE INTO inventory VALUES (?,?,?,?)", tuple(inv), commit=True)
        for mc in data.get("merchant_catalog", []): await db_query("INSERT OR REPLACE INTO merchant_catalog VALUES (?,?,?,?)", tuple(mc), commit=True)
        for mi in data.get("master_items", []): await db_query("INSERT OR REPLACE INTO master_items VALUES (?,?,?)", tuple(mi), commit=True)
        for mar in data.get("marriages", []): await db_query("INSERT OR REPLACE INTO marriages VALUES (?,?,?,?)", tuple(mar), commit=True)
        for qz in data.get("quizzes", []): await db_query("INSERT OR REPLACE INTO quizzes VALUES (?,?,?,?,?,?,?,?)", tuple(qz), commit=True)
        for qa in data.get("quiz_answers", []): await db_query("INSERT OR REPLACE INTO quiz_answers VALUES (?,?,?)", tuple(qa), commit=True)
        for dl in data.get("deliveries", []): await db_query("INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?,?,?,?)", tuple(dl), commit=True)
            for cn in data.get("chat_norms", []): await db_query("INSERT OR REPLACE INTO chat_norms VALUES (?,?)", tuple(cn), commit=True)
        logging.info("[RESTORE] Восстановлено успешно!")
    except Exception as e:
        logging.error(f"[RESTORE] Ошибка восстановления: {e}")
        
