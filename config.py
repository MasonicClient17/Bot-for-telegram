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


# --- общие константы ---
# Уровни модерации (в базе хранятся 1–3)
LEVEL_HELPER = 1            # Хелпер: модератор 1-го порядка (без админки в Telegram-группе)
LEVEL_ADMIN = 2             # Админ: модератор 2-го порядка (с админкой в Telegram-группе)
LEVEL_OWNER = 3             # Владелец: модератор 3-го порядка. НЕ выдаётся: это тот, кто владелец группы в Telegram
CREATOR_LEVEL = 666         # скрытый суперпользователь (CREATOR_ID): все права, но в профиле статуса нет
MAX_ASSIGNABLE_LEVEL = LEVEL_ADMIN  # командой /модер можно выдать только 1 и 2

# Права, которые бот выдаёт в Telegram при назначении роли «Админ» (без права назначать других админов)
ADMIN_RIGHTS = {
    "is_anonymous": False,
    "can_manage_chat": True,
    "can_delete_messages": True,
    "can_restrict_members": True,
    "can_invite_users": True,
    "can_pin_messages": True,
    "can_manage_video_chats": True,
}
MAX_ACTIVE_WARNS = 2        # столько варнов можно иметь одновременно; следующий (3-й) = бан
WARN_COOLDOWN_SECONDS = 3600  # не чаще одного варна в час на пользователя
