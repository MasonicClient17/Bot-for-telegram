import aiosqlite
import os
from config import STORAGE_CHAT_ID, bot

DB_NAME = "bot_database.db"

async def db_query(query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False, commit: bool = False):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(query, params) as cursor:
            if commit:
                await db.commit()
            if fetchone:
                return await cursor.fetchone()
            if fetchall:
                return await cursor.fetchall()
            return None

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER,
                user_id INTEGER,
                role_level INTEGER DEFAULT 0,
                warns INTEGER DEFAULT 0,
                msg_count INTEGER DEFAULT 0,
                rp_name TEXT,
                day_count INTEGER DEFAULT 1,
                week_count INTEGER DEFAULT 1,
                last_msg_date TEXT,
                week_number TEXT,
                joined_at TEXT,
                tapes INTEGER DEFAULT 0,
                status TEXT,
                rep INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_members (
                chat_id INTEGER,
                user_id INTEGER,
                first_name TEXT,
                username TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mod_roles (
                chat_id INTEGER,
                user_id INTEGER,
                role_level INTEGER,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cmd_levels (
                chat_id INTEGER,
                cmd_name TEXT,
                min_lvl INTEGER,
                PRIMARY KEY (chat_id, cmd_name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dynamic_commands (
                chat_id INTEGER,
                action_key TEXT,
                cmd_name TEXT,
                PRIMARY KEY (chat_id, action_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dynamic_phrases (
                chat_id INTEGER,
                key_name TEXT,
                text_value TEXT,
                PRIMARY KEY (chat_id, key_name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_norms (
                chat_id INTEGER PRIMARY KEY,
                min_messages INTEGER DEFAULT 10
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS marriages (
                chat_id INTEGER,
                user1_id INTEGER,
                user2_id INTEGER,
                date TEXT,
                PRIMARY KEY (chat_id, user1_id, user2_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_cookies (
                chat_id INTEGER,
                user_id INTEGER,
                last_date TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_reminders (
                chat_id INTEGER,
                user_id INTEGER,
                reminder_text TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_commands (
                chat_id INTEGER,
                command_name TEXT,
                response_text TEXT,
                PRIMARY KEY (chat_id, command_name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_tags (
                chat_id INTEGER,
                user_id INTEGER,
                tag TEXT,
                PRIMARY KEY (chat_id, user_id, tag)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                quiz_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                creator_id INTEGER,
                question TEXT,
                correct_answer TEXT,
                status INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_answers (
                quiz_id INTEGER,
                user_id INTEGER,
                user_name TEXT,
                answer TEXT,
                is_correct INTEGER,
                PRIMARY KEY (quiz_id, user_id)
            )
        """)
        await db.commit()

async def backup_to_telegram():
    if not STORAGE_CHAT_ID:
        return
    if os.path.exists(DB_NAME):
        from aiogram.types import FSInputFile
        await bot.send_document(STORAGE_CHAT_ID, document=FSInputFile(DB_NAME), caption="💾 Автоматический бэкап базы данных")

async def restore_from_telegram():
    pass
    
