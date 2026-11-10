import asyncio
import os
import sqlite3
import time

import aiosqlite

from config import CREATOR_LEVEL, DB_NAME, MAX_ASSIGNABLE_LEVEL


def pick_display_name(rp_name, tag, first_name, username, fallback: str = "User") -> str:
    """Приоритет: РП-ник > тэг > Telegram first_name > @username > fallback."""
    return rp_name or tag or first_name or (f"@{username}" if username else fallback)


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

    async def _fetchone_dict(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return dict(zip([c[0] for c in cur.description], row))

    async def _fetchall_dict(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            names = [c[0] for c in cur.description]
            return [dict(zip(names, r)) for r in rows]

    async def _ensure_columns(self, table: str, columns: dict):
        existing = {row[1] for row in await self._fetchall(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        await self.conn.commit()

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
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                weekly_quota INTEGER
            );
            CREATE TABLE IF NOT EXISTS temp_warns (
                chat_id INTEGER,
                user_id INTEGER,
                expires_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS quota_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                recipient_id INTEGER DEFAULT 0,
                message_id INTEGER,
                chat_title TEXT,
                user_name TEXT,
                week_count INTEGER,
                quota INTEGER,
                text TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS rp_commands (
                chat_id INTEGER,
                name TEXT,
                text TEXT,
                author_id INTEGER,
                PRIMARY KEY (chat_id, name)
            );
            CREATE TABLE IF NOT EXISTS triggers (
                chat_id INTEGER,
                type TEXT,
                keyword TEXT,
                action TEXT,
                PRIMARY KEY (chat_id, type, keyword)
            );
        """)
        await self._ensure_columns("rp_commands", {"author_id": "INTEGER"})
        await self._ensure_columns("member_stats", {
            "week_count": "INTEGER DEFAULT 0",
            "joined_at": "INTEGER",
            "first_seen": "INTEGER",
            "is_member": "INTEGER DEFAULT 1",
            "reputation": "INTEGER DEFAULT 0",
            "rest_until": "INTEGER",
            "cassettes": "INTEGER DEFAULT 0",
            "last_daily_claim": "TEXT",
        })
        await self._ensure_columns("chat_settings", {
            "daily_reward": "TEXT",
            "rest_price": "INTEGER DEFAULT 1",
        })
        await self._exec("UPDATE moderators SET level = ? WHERE level > ?", (MAX_ASSIGNABLE_LEVEL, MAX_ASSIGNABLE_LEVEL))
        await self._ensure_columns("temp_warns", {
            "issued_at": "INTEGER",
            "issued_by": "INTEGER",
            "reason": "TEXT",
        })

    async def make_snapshot(self, target_path: str):
        last_error = None
        for _ in range(5):
            if os.path.exists(target_path):
                os.remove(target_path)
            try:
                await self.conn.commit()
                await self.conn.execute("VACUUM INTO ?", (target_path,))
                return
            except sqlite3.OperationalError as e:
                last_error = e
                await asyncio.sleep(0.3)
        raise last_error

    async def _upsert_user(self, chat_id, user_id, username, first_name, inc: int):
        await self._exec("""
            INSERT INTO member_stats
                (chat_id, user_id, username, first_name, message_count, week_count, first_seen, is_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                message_count = message_count + ?,
                week_count = COALESCE(week_count, 0) + ?,
                username = excluded.username,
                first_name = excluded.first_name,
                is_member = CASE WHEN ? > 0 THEN 1 ELSE is_member END
        """, (chat_id, user_id, username, first_name, inc, inc, int(time.time()), inc, inc, inc))

    async def record_message(self, chat_id: int, user_id: int, username: str | None, first_name: str | None):
        await self._upsert_user(chat_id, user_id, username, first_name, 1)

    async def touch_user(self, chat_id: int, user_id: int, username: str | None, first_name: str | None):
        await self._upsert_user(chat_id, user_id, username, first_name, 0)

    async def get_display_name(self, chat_id: int, user_id: int, fallback: str = "User") -> str:
        row = await self._fetchone("""
            SELECT rp_name, tag, first_name, username FROM member_stats
            WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))
        if not row:
            return fallback
        return pick_display_name(*row, fallback=fallback)

    async def set_rp_name(self, chat_id: int, user_id: int, rp_name: str):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, rp_name, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name = excluded.rp_name
        """, (chat_id, user_id, rp_name or None, int(time.time())))

    async def set_tag(self, chat_id: int, user_id: int, tag: str):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, tag, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET tag = excluded.tag
        """, (chat_id, user_id, tag or None, int(time.time())))

    async def get_user_id_by_username(self, chat_id: int, username: str) -> int | None:
        row = await self._fetchone("""
            SELECT user_id FROM member_stats
            WHERE chat_id = ? AND LOWER(username) = LOWER(?)
        """, (chat_id, username.lstrip("@")))
        return row[0] if row else None

    async def get_top_users(self, chat_id: int, limit: int, offset: int):
        return await self._fetchall("""
            SELECT user_id, COALESCE(week_count, 0), message_count FROM member_stats
            WHERE chat_id = ? AND message_count > 0 AND COALESCE(is_member, 1) = 1
            ORDER BY COALESCE(week_count, 0) DESC, message_count DESC, user_id
            LIMIT ? OFFSET ?
        """, (chat_id, limit, offset))

    async def get_total_users_count(self, chat_id: int) -> int:
        row = await self._fetchone("""
            SELECT COUNT(*) FROM member_stats
            WHERE chat_id = ? AND message_count > 0 AND COALESCE(is_member, 1) = 1
        """, (chat_id,))
        return row[0] if row else 0

    async def get_random_user(self, chat_id: int) -> int | None:
        row = await self._fetchone("""
            SELECT user_id FROM member_stats
            WHERE chat_id = ? AND message_count > 0
            ORDER BY RANDOM() LIMIT 1
        """, (chat_id,))
        return row[0] if row else None

    async def get_member_ids(self, chat_id: int, exclude_user_id: int, limit: int) -> list[int]:
        rows = await self._fetchall("""
            SELECT user_id FROM member_stats
            WHERE chat_id = ? AND user_id != ? AND COALESCE(is_member, 1) = 1
            ORDER BY message_count DESC, user_id
            LIMIT ?
        """, (chat_id, exclude_user_id, limit))
        return [r[0] for r in rows]

    async def add_rp_command(self, chat_id: int, name: str, text: str, author_id: int) -> bool:
        rows = await self._exec(
            "INSERT OR IGNORE INTO rp_commands (chat_id, name, text, author_id) VALUES (?, ?, ?, ?)",
            (chat_id, name.lower(), text, author_id))
        return rows == 1

    async def get_rp_command_info(self, chat_id: int, name: str):
        row = await self._fetchone(
            "SELECT author_id FROM rp_commands WHERE chat_id = ? AND name = ?", (chat_id, name.lower()))
        return (True, row[0]) if row else (False, None)

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

    async def get_moderator_level(self, chat_id: int, user_id: int, creator_id: int) -> int:
        if creator_id and user_id == creator_id:
            return CREATOR_LEVEL
        row = await self._fetchone(
            "SELECT level FROM moderators WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 0

    async def get_stored_moderator_level(self, chat_id: int, user_id: int) -> int:
        row = await self._fetchone(
            "SELECT level FROM moderators WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 0

    async def set_moderator_level(self, chat_id: int, user_id: int, level: int):
        await self._exec("""
            INSERT INTO moderators (chat_id, user_id, level) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET level = excluded.level
        """, (chat_id, user_id, level))

    async def get_total_warns(self, chat_id: int, user_id: int) -> int:
        row = await self._fetchone(
            "SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        permanent = row[0] if row else 0
        row = await self._fetchone(
            "SELECT COUNT(*) FROM temp_warns WHERE chat_id = ? AND user_id = ? AND expires_at > ?",
            (chat_id, user_id, int(time.time())))
        return permanent + (row[0] if row else 0)

    async def add_temp_warn(self, chat_id: int, user_id: int, expires_at: int,
                            issued_by: int = 0, reason: str | None = None) -> int:
        await self._exec("""
            INSERT INTO temp_warns (chat_id, user_id, expires_at, issued_at, issued_by, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, user_id, expires_at, int(time.time()), issued_by, reason))
        return await self.get_total_warns(chat_id, user_id)

    async def get_last_warn_time(self, chat_id: int, user_id: int) -> int | None:
        row = await self._fetchone(
            "SELECT MAX(issued_at) FROM temp_warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row and row[0] else None

    async def get_warned_users(self, chat_id: int):
        """Возвращает список пользователей, у которых есть активные варны."""
        rows = await self._fetchall("""
            SELECT DISTINCT user_id FROM temp_warns
            WHERE chat_id = ? AND expires_at > ?
        """, (chat_id, int(time.time())))
        warned_ids = {r[0] for r in rows}
        perm_rows = await self._fetchall("""
            SELECT user_id FROM warns WHERE chat_id = ? AND count > 0
        """, (chat_id,))
        for r in perm_rows:
            warned_ids.add(r[0])
        return list(warned_ids)

    async def get_user_warn_details(self, chat_id: int, user_id: int):
        """Возвращает список деталей активных варнов пользователя."""
        return await self._fetchall_dict("""
            SELECT issued_at, expires_at, issued_by, reason FROM temp_warns
            WHERE chat_id = ? AND user_id = ? AND expires_at > ?
            ORDER BY issued_at DESC
        """, (chat_id, user_id, int(time.time())))

    async def decrease_warn(self, chat_id: int, user_id: int, amount: int) -> int:
        row = await self._fetchone(
            "SELECT count FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        permanent = row[0] if row else 0
        take = min(permanent, amount)
        if take:
            await self._exec(
                "UPDATE warns SET count = count - ? WHERE chat_id = ? AND user_id = ?",
                (take, chat_id, user_id))
        remaining = amount - take
        if remaining > 0:
            await self._exec("""
                DELETE FROM temp_warns WHERE rowid IN (
                    SELECT rowid FROM temp_warns
                    WHERE chat_id = ? AND user_id = ? AND expires_at > ?
                    ORDER BY expires_at LIMIT ?
                )
            """, (chat_id, user_id, int(time.time()), remaining))
        return await self.get_total_warns(chat_id, user_id)

    async def reset_warns(self, chat_id: int, user_id: int):
        await self._exec("DELETE FROM warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await self._exec("DELETE FROM temp_warns WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))

    async def cleanup_expired_warns(self):
        await self._exec("DELETE FROM temp_warns WHERE expires_at <= ?", (int(time.time()),))

    async def get_meta(self, key: str) -> str | None:
        row = await self._fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return row[0] if row else None

    async def set_meta(self, key: str, value: str):
        await self._exec("""
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))

    async def record_join(self, chat_id: int, user_id: int, username, first_name, ts: int):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, username, first_name, joined_at, first_seen, is_member)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                joined_at = excluded.joined_at,
                is_member = 1,
                username = excluded.username,
                first_name = excluded.first_name
        """, (chat_id, user_id, username, first_name, ts, ts))

    async def mark_left(self, chat_id: int, user_id: int):
        await self._exec(
            "UPDATE member_stats SET is_member = 0 WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))

    async def get_group_chat_ids(self) -> list[int]:
        rows = await self._fetchall("SELECT DISTINCT chat_id FROM member_stats WHERE chat_id < 0")
        return [r[0] for r in rows]

    async def get_quota_candidates(self, chat_id: int, quota: int, grace_cutoff: int):
        return await self._fetchall_dict("""
            SELECT user_id, username, first_name, rp_name, week_count, joined_at, first_seen
            FROM member_stats
            WHERE chat_id = ? AND is_member = 1 AND COALESCE(week_count, 0) < ?
              AND COALESCE(joined_at, first_seen, 0) <= ?
              AND COALESCE(rest_until, 0) <= ?
            ORDER BY week_count, user_id
        """, (chat_id, quota, grace_cutoff, int(time.time())))

    async def reset_week_counts(self):
        await self._exec("UPDATE member_stats SET week_count = 0")

    async def has_pending_report(self, chat_id: int, user_id: int) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM quota_reports WHERE chat_id = ? AND user_id = ? AND status = 'pending'",
            (chat_id, user_id))
        return row is not None

    async def create_report(self, chat_id, user_id, chat_title, user_name, week_count, quota, text) -> int:
        async with self.conn.execute("""
            INSERT INTO quota_reports
                (chat_id, user_id, chat_title, user_name, week_count, quota, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, user_id, chat_title, user_name, week_count, quota, text, int(time.time()))) as cur:
            report_id = cur.lastrowid
        await self.conn.commit()
        return report_id

    async def set_report_delivery(self, report_id: int, recipient_id: int, message_id: int):
        await self._exec(
            "UPDATE quota_reports SET recipient_id = ?, message_id = ? WHERE id = ?",
            (recipient_id, message_id, report_id))

    async def get_report(self, report_id: int):
        return await self._fetchone_dict("SELECT * FROM quota_reports WHERE id = ?", (report_id,))

    async def set_report_status(self, report_id: int, status: str):
        await self._exec("UPDATE quota_reports SET status = ? WHERE id = ?", (status, report_id))

    async def delete_report(self, report_id: int):
        await self._exec("DELETE FROM quota_reports WHERE id = ?", (report_id,))

    async def get_weekly_quota(self, chat_id: int, default: int) -> int:
        row = await self._fetchone("SELECT weekly_quota FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return row[0] if row and row[0] else default

    async def set_weekly_quota(self, chat_id: int, quota: int):
        await self._exec("""
            INSERT INTO chat_settings (chat_id, weekly_quota) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET weekly_quota = excluded.weekly_quota
        """, (chat_id, quota))

    async def get_profile(self, chat_id: int, user_id: int):
        return await self._fetchone_dict("""
            SELECT rp_name, tag, first_name, username,
                   COALESCE(week_count, 0) AS week_count, message_count,
                   joined_at, first_seen, COALESCE(reputation, 0) AS reputation,
                   COALESCE(cassettes, 0) AS cassettes
            FROM member_stats WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))

    async def count_inactive_members(self, chat_id: int, quota: int) -> int:
        row = await self._fetchone("""
            SELECT COUNT(*) FROM member_stats
            WHERE chat_id = ? AND COALESCE(is_member, 1) = 1 AND COALESCE(week_count, 0) < ?
        """, (chat_id, quota))
        return row[0] if row else 0

    async def get_inactive_members(self, chat_id: int, quota: int, limit: int):
        return await self._fetchall_dict("""
            SELECT user_id, rp_name, tag, first_name, username, COALESCE(week_count, 0) AS week_count,
                   COALESCE(rest_until, 0) AS rest_until
            FROM member_stats
            WHERE chat_id = ? AND COALESCE(is_member, 1) = 1 AND COALESCE(week_count, 0) < ?
            ORDER BY week_count, user_id
            LIMIT ?
        """, (chat_id, quota, limit))

    async def set_rest(self, chat_id: int, user_id: int, until: int):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, rest_until, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET rest_until = excluded.rest_until
        """, (chat_id, user_id, until, int(time.time())))

    async def clear_rest(self, chat_id: int, user_id: int) -> bool:
        rows = await self._exec("""
            UPDATE member_stats SET rest_until = NULL
            WHERE chat_id = ? AND user_id = ? AND COALESCE(rest_until, 0) > ?
        """, (chat_id, user_id, int(time.time())))
        return rows > 0

    # --- Новые методы для Кассет, Репутации и Триггеров ---

    async def add_cassettes(self, chat_id: int, user_id: int, amount: int):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, cassettes, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET cassettes = COALESCE(cassettes, 0) + ?
        """, (chat_id, user_id, max(0, amount), int(time.time()), amount))

    async def get_cassettes(self, chat_id: int, user_id: int) -> int:
        row = await self._fetchone("SELECT COALESCE(cassettes, 0) FROM member_stats WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else 0

    async def set_reputation(self, chat_id: int, user_id: int, delta: int):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, reputation, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET reputation = COALESCE(reputation, 0) + ?
        """, (chat_id, user_id, delta, int(time.time()), delta))

    async def get_daily_reward(self, chat_id: int) -> str | None:
        row = await self._fetchone("SELECT daily_reward FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return row[0] if row else None

    async def set_daily_reward(self, chat_id: int, val: str):
        await self._exec("""
            INSERT INTO chat_settings (chat_id, daily_reward) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET daily_reward = excluded.daily_reward
        """, (chat_id, val))

    async def get_rest_price(self, chat_id: int) -> int:
        row = await self._fetchone("SELECT COALESCE(rest_price, 1) FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return row[0] if row and row[0] else 1

    async def set_rest_price(self, chat_id: int, price: int):
        await self._exec("""
            INSERT INTO chat_settings (chat_id, rest_price) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET rest_price = excluded.rest_price
        """, (chat_id, price))

    async def add_trigger(self, chat_id: int, t_type: str, keyword: str, action: str):
        await self._exec("""
            INSERT INTO triggers (chat_id, type, keyword, action) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, type, keyword) DO UPDATE SET action = excluded.action
        """, (chat_id, t_type, keyword.lower(), action))

    async def get_triggers(self, chat_id: int, t_type: str):
        return await self._fetchall("SELECT keyword, action FROM triggers WHERE chat_id = ? AND type = ?", (chat_id, t_type))

    async def get_last_daily_claim(self, chat_id: int, user_id: int) -> str | None:
        row = await self._fetchone("SELECT last_daily_claim FROM member_stats WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return row[0] if row else None

    async def set_last_daily_claim(self, chat_id: int, user_id: int, date_str: str):
        await self._exec("""
            INSERT INTO member_stats (chat_id, user_id, last_daily_claim, first_seen) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET last_daily_claim = excluded.last_daily_claim
        """, (chat_id, user_id, date_str, int(time.time())))
