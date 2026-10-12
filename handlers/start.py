from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import Command
from config import STORAGE_CHAT_ID
from database import db_query, backup_to_telegram
from utils import (
    is_authorized_chat,
    get_text,
    get_cmd_name,
    resolve_target,
    check_access,
    try_delete
)

router = Router()

@router.message(Command("start"))
async def start_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return
    await m.answer("🌌 <b>Бот успешно запущен и готов к работе!</b>")

@router.message(F.text)
async def save_backup_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return
    
    text_lower = m.text.lower().strip()
    save_trigger = await get_cmd_name(m.chat.id, "save")
    
    if text_lower == save_trigger.lower():
        if m.chat.id != STORAGE_CHAT_ID and not await check_access(m, "save"):
            return
        await try_delete(m)
        try:
            await backup_to_telegram()
            msg_text = await get_text(m.chat.id, "backup_success")
            await m.answer(msg_text)
        except Exception as e:
            err_text = await get_text(m.chat.id, "backup_error", error=str(e))
            await m.answer(err_text)
        return
    return

@router.message(F.text)
async def profile_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text_lower = m.text.lower().strip()
    cmd_profile = await get_cmd_name(m.chat.id, "profile")
    cmd_whoami = await get_cmd_name(m.chat.id, "whoami")
    cmd_whois = await get_cmd_name(m.chat.id, "whois")

    if text_lower not in (cmd_profile.lower(), cmd_whoami.lower(), cmd_whois.lower()):
        return

    target_id = await resolve_target(m) or m.from_user.id
    
    target_row = await db_query(
        "SELECT joined_at, tapes, msg_count, status, rep FROM users WHERE chat_id=? AND user_id=?",
        (m.chat.id, target_id),
        fetchone=True
    )
    
    member_row = await db_query(
        "SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?",
        (m.chat.id, target_id),
        fetchone=True
    )
    
    norm_row = await db_query(
        "SELECT min_messages FROM chat_norms WHERE chat_id=?",
        (m.chat.id,),
        fetchone=True
    )

    user_name = member_row[0] if member_row else "Участник"
    joined_at = target_row[0] if target_row else datetime.now().strftime("%d.%m.%Y")
    tapes = target_row[1] if target_row else 0
    msg_count = target_row[2] if target_row else 0
    status = target_row[3] if target_row else "Участник"
    rep = target_row[4] if target_row else 0
    min_norm = norm_row[0] if norm_row else 0

    profile_text = await get_text(
        m.chat.id,
        "profile",
        user=user_name,
        joined_at=joined_at,
        tapes=tapes,
        msg_count=msg_count,
        min_norm=min_norm,
        status=status,
        rep=rep
    )
    
    await m.answer(profile_text)
    
