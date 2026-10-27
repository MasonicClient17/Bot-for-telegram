import logging
import os

from dotenv import load_dotenv

load_dotenv()

# Путь к БД. На Railway укажи DB_PATH=/data/database.db и подключи Volume в /data —
# тогда база переживает редеплои.
DB_NAME = os.getenv("DB_PATH", "database.db")


def _int_env(name: str) -> int:
    raw = os.getenv(name, "").strip().strip("\"'")
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        logging.error("Переменная %s должна быть числом, а сейчас: %r", name, raw)
        return 0


def get_creator_id() -> int:
    return _int_env("CREATOR_ID")


def get_storage_chat_id() -> int:
    return _int_env("STORAGE_CHAT_ID")


def get_backup_interval_hours() -> float:
    try:
        return float(os.getenv("BACKUP_INTERVAL_HOURS", "6"))
    except ValueError:
        return 6.0


def get_weekly_quota() -> int:
    try:
        return max(1, int(os.getenv("WEEKLY_QUOTA", "50")))
    except ValueError:
        return 50


def get_quota_utc_offset() -> float:
    """Сдвиг часового пояса относительно UTC для границы недели (понедельник 00:00)."""
    try:
        return float(os.getenv("QUOTA_UTC_OFFSET_HOURS", "0"))
    except ValueError:
        return 0.0
