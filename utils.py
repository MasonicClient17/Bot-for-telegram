import re
import random
from aiogram import types
from database import db_query

async def get_user_tag(chat_id: int, user_id: int) -> str:
    res = await db_query("SELECT tag_name FROM user_tags WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    return res[0] if res else ""

async def get_display_name(chat_id: int, user_id: int, fallback: str) -> str:
    user = await db_query("SELECT rp_name FROM users WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    if user and user[0]:
        return user[0]
    return fallback

async def try_delete(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

async def check_access(message: types.Message, cmd_name: str) -> bool:
    if message.from_user.id == message.chat.id or message.chat.type == "private":
        return True
    
    # Проверка создателя
    member = await message.chat.get_member(message.from_user.id)
    if member.status in ["creator", "administrator"]:
        return True

    # Проверка уровней в базе
    user_lvl = await db_query("SELECT role_level FROM users WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id), fetchone=True)
    lvl = user_lvl[0] if user_lvl else 0
    
    req_lvl = await db_query("SELECT min_lvl FROM cmd_levels WHERE chat_id=? AND cmd_name=?", (message.chat.id, cmd_name), fetchone=True)
    if req_lvl and lvl < req_lvl[0]:
        return False
    return lvl >= 1 or req_lvl is not None

def parse_rp_text(text: str) -> str:
    # Заменяем {c} или {chance} на случайное число от 0 до 100%
    def replace_chance(match):
        return f"{random.randint(0, 100)}%"
    
    parsed = re.sub(r"\{c\}|\{chance\}", replace_chance, text, flags=re.I)
    return parsed

def schedule_sync():
    pass
    
