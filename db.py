import asyncio
import os
import sqlite3

import aiosqlite

from config import DB_NAME


class Database:
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_path)

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    # --- низкоуровневые помощники ---

    async def _exec(self, sql: str, params: tuple = ()) -> int:
        async with self.conn.execute(sql, params) as cur:
            rowcount = cur.rowcount
        await self.conn.commit()
        return rowcount

    async def _fetchone(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def init_db(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS member_stats (
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                message_count INTEGER DEFAULT 0,
                rp_name TEXT,
                tag TEXT,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS warns (
                chat_id INTEGER,
                user_id INTEGER,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS moderators (
                chat_id INTEGER,
                user_id INTEGER,
                level INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS rp_commands (
                chat_id INTEGER,
                name TEXT,
                text TEXT,
                PRIMARY KEY (chat_id, name)
            );
        """)
        await self.conn.commit()

    # --- бэкап ---

    async def make_snapshot(self, target_path: str):
        """Консистентная копия БД (VACUUM INTO), а не копирование «живого» файла."""
        last_error = None
        for _ in range(5):
            if os.path.exists(target_path):
                os.remove(target_path)
            try:
                await self.conn.commit()
                await self.conn.execute("VACUUM INTO ?", (target_path,))
                return
            except sqlite3.OperationalError as e:  # например, пока идёт чужая транзакция
                last_error = e
                await asyncio.sleep(0.3)
        raise last_error

    # --- пользователи и активность ---

    async def _upsert_user(self, chat_id, user_id, username, first_name, inc: int):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, username, first_name, message_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                message_count = message_count + ?,
                username = excluded.username,
                first_name = excluded.first_name
        """, (chat_id, user_id, username, first_name, inc, inc))

    async def update_activity(self, chat_id: int, user_id: int, username: str | None, first_name: str | None):
        await self._upsert_user(chat_id, user_id, username, first_name, 1)

    async def touch_user(self, chat_id: int, user_id: int, username: str | None, first_name: str | None):
        """Запоминает пользователя (ник, username), не увеличивая счётчик сообщений."""
        await self._upsert_user(chat_id, user_id, username, first_name, 0)

    async def get_display_name(self, chat_id: int, user_id: int, fallback: str = "User") -> str:
        row = await self._fetchone("""
            SELECT rp_name, tag, first_name, username FROM member_stats
            WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))
        if not row:
            return fallback
        rp_name, tag, first_name, username = row
        # Приоритет: РП-ник > Тэг > Telegram first_name > @username
        return rp_name or tag or first_name or (f"@{username}" if username else fallback)

    async def set_rp_name(self, chat_id: int, user_id: int, rp_name: str):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, rp_name) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name = excluded.rp_name
        """, (chat_id, user_id, rp_name or None))

    async def set_tag(self, chat_id: int, user_id: int, tag: str):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, tag) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET tag = excluded.tag
        """, (chat_id, user_id, tag or None))

    async def get_user_id_by_username(self, chat_id: int, username: str) -> int | None:
        row = await self._fetchone("""
            SELECT user_id FROM member_stats
            WHERE chat_id = ? AND LOWER(username) = LOWER(?)
        """, (chat_id, username.lstrip("@")))
        return row[0] if row else None

    async def get_top_users(self, chat_id: int, limit: int, offset: int):
        return await self._fetchall("""
            SELECT user_id, message_count FROM member_stats
            WHERE chat_id = ? AND message_count > 0
            ORDER BY message_count DESC, user_id
            LIMIT ? OFFSET ?
        """, (chat_id, limit, offset))

    async def get_total_users_count(self, chat_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) FROM member_stats WHERE chat_id = ? AND message_count > 0", (chat_id,))
        return row[0] if row else 0

    async def get_random_user(self, chat_id: int) -> int | None:
        row = await self._fetchone("""
            SELECT user_id FROM member_stats
            WHERE chat_id = ? AND message_count > 0
            ORDER BY RANDOM() LIMIT 1
        """, (chat_id,))
        return row[0] if row else None

    # --- РП-команды ---

    async def add_rp_command(self, chat_id: int, name: str, text: str) -> bool:
        """False, если команда с таким именем уже есть."""
        rows = await self._exec(
            "INSERT OR IGNORE INTO rp_commands (chat_id, name, text) VALUES (?, ?, ?)",
            (chat_id, name.lower(), text))
        return rows == 1

    async def get_rp_command(self, chat_id: int, name: str) -> str | None:
        row = await self._fetchone(
            "SELECT text FROM rp_commands WHERE chat_id = ? AND name = ?", (chat_id, name.lower()))
        return row[0] if row else None

    async def get_all_rp_commands(self, chat_id: int):
        return await self._fetchall(
            "SELECT name FROM rp_commands WHERE chat_id = ? ORDER BY name", (chat_id,))

    async def delete_rp_command(self, chat_id: int, name: str) -> bool:
        rows = await self._exec(
            "DELETE FROM rp_commands WHERE chat_id = ? AND name = ?", (chat_id, name.lower()))
        return rows > 0

    # --- модерация и варны ---

    async def get_moderator_level(self, chat_id: int, user_id: int, creator_id: int) -> int:
        if creator_id and user_id == creator_id:
            return 99
        row = await self._fetchone(
            "SELECT level FROM moderators WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 0

    async def set_moderator_level(self, chat_id: int, user_id: int, level: int):
        await self._exec("""
            INSERT INTO moderators (chat_id, user_id, level) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET level = excluded.level
        """, (chat_id, user_id, level))

    async def add_warn(self, chat_id: int, user_id: int) -> int:
        await self._exec("""
            INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1
        """, (chat_id, user_id))
        row = await self._fetchone(
            "SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 1

    async def decrease_warn(self, chat_id: int, user_id: int, amount: int) -> int:
        await self._exec("""
            INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, 0)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET count = MAX(0, count - ?)
        """, (chat_id, user_id, amount))
        row = await self._fetchone(
            "SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 0

    async def reset_warns(self, chat_id: int, user_id: int):
        await self._exec("DELETE FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        
