import re
from typing import Optional, Union
from aiogram import types
from config import GROUP_ID, STORAGE_CHAT_ID, SUPERUSER_ID
from database import db_query
from phrases import DEFAULT_COMMANDS, DEFAULT_PHRASES

async def is_authorized_chat(chat_id: int) -> bool:
    """Проверяет, работает ли бот в разрешенном чате."""
    if chat_id in (GROUP_ID, STORAGE_CHAT_ID):
        return True
    return False

async def get_text(chat_id: int, key: str, **kwargs) -> str:
    """Возвращает динамический текст из БД или из phrases.py по умолчанию."""
    res = await db_query("SELECT text_value FROM dynamic_phrases WHERE chat_id=? AND key_name=?", (chat_id, key), fetchone=True)
    text = res[0] if res else DEFAULT_PHRASES.get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text

async def get_cmd_name(chat_id: int, action_key: str) -> str:
    """Возвращает переименованный триггер команды или значение по умолчанию."""
    res = await db_query("SELECT cmd_name FROM dynamic_commands WHERE chat_id=? AND action_key=?", (chat_id, action_key), fetchone=True)
    return res[0] if res else DEFAULT_COMMANDS.get(action_key, action_key)

async def get_user_lvl(chat_id: int, user_id: int) -> int:
    """Возвращает уровень прав пользователя (0 - обычный, 1 - хелпер, 2 - модер, 3 - админ, 4 - суперпользователь)."""
    if user_id == SUPERUSER_ID:
        return 4
    
    res_mod = await db_query("SELECT role_level FROM mod_roles WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    if res_mod and res_mod[0] is not None:
        return res_mod[0]
    
    res_user = await db_query("SELECT role_level FROM users WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    return res_user[0] if (res_user and res_user[0] is not None) else 0

async def check_access(message: types.Message, action_key: str) -> bool:
    """Проверяет права доступа пользователя к команде."""
    if not await is_authorized_chat(message.chat.id):
        return False
        
    user_lvl = await get_user_lvl(message.chat.id, message.from_user.id)
    if user_lvl >= 4:
        return True
        
    res = await db_query("SELECT min_lvl FROM cmd_levels WHERE chat_id=? AND cmd_name=?", (message.chat.id, action_key), fetchone=True)
    min_lvl = res[0] if res else 1
    return user_lvl >= min_lvl

async def resolve_target(message: types.Message) -> Optional[int]:
    """Извлекает ID целевого пользователя из ответа на сообщение или упоминания через @username."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
        
    args = message.text.split()
    if len(args) > 1:
        clean_arg = args[1].lstrip("@").strip()
        if clean_arg.isdigit():
            return int(clean_arg)
        res = await db_query(
            "SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?",
            (message.chat.id, clean_arg.lower()),
            fetchone=True
        )
        if res:
            return res[0]
    return None

async def try_delete(message: types.Message):
    """Безопасно удаляет сообщение пользователя, чтобы не засорять чат."""
    try:
        await message.delete()
    except Exception:
        pass
      
