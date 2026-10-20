import aiosqlite
import os

DB_NAME = "database.db"

class Database:
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def init_db(self):
        async with self.conn.cursor() as cursor:
            # Активность и пользователи
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_stats (
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    message_count INTEGER DEFAULT 0,
                    rp_name TEXT,
                    tag TEXT,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            # Варны
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS warns (
                    chat_id INTEGER,
                    user_id INTEGER,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            # Модераторы
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS moderators (
                    chat_id INTEGER,
                    user_id INTEGER,
                    level INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            # РП-команды
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS rp_commands (
                    chat_id INTEGER,
                    name TEXT,
                    text TEXT,
                    PRIMARY KEY (chat_id, name)
                )
            """)
            await self.conn.commit()

    async def update_activity(self, chat_id: int, user_id: int, username: str, first_name: str):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO member_stats (chat_id, user_id, username, first_name, message_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    message_count = message_count + 1,
                    username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name)
            """, (chat_id, user_id, username, first_name, username, first_name))
            await self.conn.commit()

    async def get_display_name(self, chat_id: int, user_id: int) -> str:
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                SELECT rp_name, tag, first_name, username FROM member_stats
                WHERE chat_id = ? AND user_id = ?
            """, (chat_id, user_id))
            row = await cursor.fetchone()
            if not row:
                return "User"
            rp_name, tag, first_name, username = row
            # Приоритет: РП-ник > Тэг > Telegram First Name
            if rp_name:
                return rp_name
            if tag:
                return tag
            if first_name:
                return first_name
            if username:
                return f"@{username}"
            return "User"

    async def set_rp_name(self, chat_id: int, user_id: int, rp_name: str):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO member_stats (chat_id, user_id, rp_name)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name = ?
            """, (chat_id, user_id, rp_name, rp_name))
            await self.conn.commit()

    async def set_tag(self, chat_id: int, user_id: int, tag: str):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO member_stats (chat_id, user_id, tag)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET tag = ?
            """, (chat_id, user_id, tag, tag))
            await self.conn.commit()

    async def get_user_id_by_username(self, chat_id: int, username: str) -> int | None:
        clean_username = username.lstrip("@")
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                SELECT user_id FROM member_stats
                WHERE chat_id = ? AND LOWER(username) = LOWER(?)
            """, (chat_id, clean_username))
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_top_users(self, chat_id: int, limit: int, offset: int):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                SELECT user_id, message_count FROM member_stats
                WHERE chat_id = ?
                ORDER BY message_count DESC
                LIMIT ? OFFSET ?
            """, (chat_id, limit, offset))
            return await cursor.fetchall()

    async def get_total_users_count(self, chat_id: int) -> int:
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM member_stats WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_random_user(self, chat_id: int) -> int | None:
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT user_id FROM member_stats WHERE chat_id = ?", (chat_id,))
            rows = await cursor.fetchall()
            if not rows:
                return None
            import random
            return random.choice(rows)[0]

    # РП команды
    async def add_rp_command(self, chat_id: int, name: str, text: str):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO rp_commands (chat_id, name, text) VALUES (?, ?, ?)
            """, (chat_id, name.lower(), text))
            await self.conn.commit()

    async def get_rp_command(self, chat_id: int, name: str) -> str | None:
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                SELECT text FROM rp_commands WHERE chat_id = ? AND name = ?
            """, (chat_id, name.lower()))
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_all_rp_commands(self, chat_id: int):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT name FROM rp_commands WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchall()

    async def delete_rp_command(self, chat_id: int, name: str):
        async with self.conn.cursor() as cursor:
            await cursor.execute("DELETE FROM rp_commands WHERE chat_id = ? AND name = ?", (chat_id, name.lower()))
            await self.conn.commit()

    # Модерация и варны
    async def get_moderator_level(self, chat_id: int, user_id: int, creator_id: int) -> int:
        if user_id == creator_id:
            return 99
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT level FROM moderators WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def set_moderator_level(self, chat_id: int, user_id: int, level: int):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO moderators (chat_id, user_id, level) VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET level = ?
            """, (chat_id, user_id, level, level))
            await self.conn.commit()

    async def add_warn(self, chat_id: int, user_id: int) -> int:
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, 1)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1
            """, (chat_id, user_id))
            await cursor.execute("SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            row = await cursor.fetchone()
            count = row[0] if row else 1
            await self.conn.commit()
            return count

    async def decrease_warn(self, chat_id: int, user_id: int, amount: int) -> int:
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            row = await cursor.fetchone()
            current = row[0] if row else 0
            new_count = max(0, current - amount)
            await cursor.execute("""
                INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET count = ?
            """, (chat_id, user_id, new_count, new_count))
            await self.conn.commit()
            return new_count
            
