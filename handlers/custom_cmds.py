import re
from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import Filter
from database import db_query
from config import STORAGE_CHAT_ID
from utils import is_authorized_chat, check_access, try_delete, get_text, resolve_target
from phrases import DEFAULT_COMMANDS

router = Router()

class CustomCommandFilter(Filter):
    async def __call__(self, m: types.Message) -> bool:
        if not m.text or not await is_authorized_chat(m.chat.id):
            return False
        cmd = m.text.strip().lower().split()[0]
        res = await db_query(
            "SELECT 1 FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?",
            (m.chat.id, cmd), fetchone=True
        )
        return bool(res)

@router.message(F.text.lower() == "сохранить")
async def save_backup_cmd(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return
    if m.chat.id != STORAGE_CHAT_ID and not await check_access(m, "save"):
        return
    await try_delete(m)
    try:
        from database import backup_to_telegram
        await backup_to_telegram()
        msg_text = await get_text(m.chat.id, "backup_success")
        await m.answer(msg_text)
    except Exception as e:
        err_text = await get_text(m.chat.id, "backup_error", error=str(e))
        await m.answer(err_text)

@router.message(F.text.lower().in_({"профиль", "кто я", "кто ты"}))
async def profile_cmd(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return
    target_id = await resolve_target(m) or m.from_user.id
    
    target_row = await db_query(
        "SELECT joined_at, tapes, msg_count, status, rep FROM users WHERE chat_id=? AND user_id=?",
        (m.chat.id, target_id), fetchone=True
    )
    member_row = await db_query(
        "SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?",
        (m.chat.id, target_id), fetchone=True
    )
    norm_row = await db_query(
        "SELECT min_messages FROM chat_norms WHERE chat_id=?",
        (m.chat.id,), fetchone=True
    )

    user_name = member_row[0] if member_row else "Участник"
    joined_at = target_row[0] if target_row else datetime.now().strftime("%d.%m.%Y")
    tapes = target_row[1] if target_row else 0
    msg_count = target_row[2] if target_row else 0
    status = target_row[3] if target_row else "Участник"
    rep = target_row[4] if target_row else 0
    min_norm = norm_row[0] if norm_row else 0

    profile_text = await get_text(
        m.chat.id, "profile",
        user=user_name, joined_at=joined_at, tapes=tapes,
        msg_count=msg_count, min_norm=min_norm, status=status, rep=rep
    )
    await m.answer(profile_text)

@router.message(F.text.lower().startswith("изменить"))
async def rename_cmd(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return
    if not await check_access(m, "ban"):
        no_acc = await get_text(m.chat.id, "no_access")
        await m.answer(no_acc)
        return
    
    text = m.text.strip()
    match_brackets = re.findall(r'\[(.*?)\]', text)
    if len(match_brackets) >= 2:
        old_name = match_brackets[0].strip().lower()
        new_name = match_brackets[1].strip().lower()
    else:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await m.answer("🌫️ Использование: <code>изменить [старое] [новое]</code>")
            return
        old_name = parts[1].strip().lower()
        new_name = parts[2].strip().lower()

    action_key = None
    for key, default_trigger in DEFAULT_COMMANDS.items():
        if default_trigger.lower() == old_name:
            action_key = key
            break
        res = await db_query(
            "SELECT action_key FROM dynamic_commands WHERE chat_id=? AND LOWER(cmd_name)=?",
            (m.chat.id, old_name), fetchone=True
        )
        if res:
            action_key = res[0]
            break

    if not action_key:
        action_key = old_name

    await db_query(
        "INSERT OR REPLACE INTO dynamic_commands (chat_id, action_key, cmd_name) VALUES (?,?,?)",
        (m.chat.id, action_key, new_name), commit=True
    )
    await try_delete(m)
    success_msg = await get_text(m.chat.id, "cmd_changed", old_cmd=old_name, new_cmd=new_name)
    await m.answer(success_msg)

@router.message(CustomCommandFilter())
async def custom_command_handler(m: types.Message):
    text_lower = m.text.strip().lower().split()[0]
    custom_res = await db_query(
        "SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?",
        (m.chat.id, text_lower), fetchone=True
    )
    if custom_res:
        await try_delete(m)
        await m.answer(custom_res[0])
        
