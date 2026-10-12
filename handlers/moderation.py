from aiogram import Router, F, types
from config import bot
from database import db_query
from utils import (
    is_authorized_chat,
    get_text,
    get_cmd_name,
    resolve_target,
    check_access,
    get_user_lvl,
    try_delete
)
from datetime import datetime, timedelta

router = Router()

@router.message(F.text)
async def moderation_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip()
    args = text.split()
    if not args:
        return

    cmd_candidate = args[0].lower()

    c_ban = await get_cmd_name(m.chat.id, "ban")
    c_mute = await get_cmd_name(m.chat.id, "mute")
    c_unmute = await get_cmd_name(m.chat.id, "unmute")
    c_warn = await get_cmd_name(m.chat.id, "warn")
    c_unwarn = await get_cmd_name(m.chat.id, "unwarn")
    c_unban = "разбан"

    allowed_triggers = {
        c_ban.lower(): "ban",
        c_unban: "ban",
        c_mute.lower(): "mute",
        c_unmute.lower(): "unmute",
        c_warn.lower(): "warn",
        c_unwarn.lower(): "unwarn"
    }

    if cmd_candidate not in allowed_triggers:
        return

    action_key = allowed_triggers[cmd_candidate]
    if not await check_access(m, action_key):
        no_acc = await get_text(m.chat.id, "no_access")
        await m.answer(no_acc)
        return

    target_id = await resolve_target(m)
    if not target_id:
        err_msg = await get_text(m.chat.id, "user_not_found")
        await m.answer(err_msg)
        return

    # Strict security: admins cannot affect peers or superiors
    actor_lvl = await get_user_lvl(m.chat.id, m.from_user.id)
    target_lvl = await get_user_lvl(m.chat.id, target_id)
    if actor_lvl < 4 and actor_lvl <= target_lvl:
        await m.answer("🌫️ Вы не можете применить санкции к равному по рангу или вышестоящему участнику.")
        return

    await try_delete(m)

    member_row = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
    target_name = member_row[0] if member_row else "Участник"

    if cmd_candidate == c_ban.lower():
        reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"
        try:
            await bot.ban_chat_member(m.chat.id, target_id)
            success_text = await get_text(m.chat.id, "ban_success", target=target_name, reason=reason)
            await m.answer(success_text)
        except Exception as e:
            await m.answer(f"🌫️ Ошибка при бане: {e}")

    elif cmd_candidate == c_unban:
        try:
            await bot.unban_chat_member(m.chat.id, target_id, only_if_banned=True)
            await m.answer(f"🌃 Участник {target_name} был разбанен.")
        except Exception as e:
            await m.answer(f"🌫️ Ошибка при разбане: {e}")

    elif cmd_candidate == c_mute.lower():
        reason = " ".join(args[3:]) if len(args) > 3 else "Не указана"
        duration_str = args[2] if len(args) > 2 else "1h"
        
        delta = timedelta(hours=1)
        if duration_str.endswith("m"):
            delta = timedelta(minutes=int(duration_str[:-1]))
        elif duration_str.endswith("h"):
            delta = timedelta(hours=int(duration_str[:-1]))
        elif duration_str.endswith("d"):
            delta = timedelta(days=int(duration_str[:-1]))

        until_date = datetime.now() + delta
        try:
            await bot.restrict_chat_member(
                m.chat.id,
                target_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            success_text = await get_text(m.chat.id, "mute_success", target=target_name, time=duration_str, reason=reason)
            await m.answer(success_text)
        except Exception as e:
            await m.answer(f"🌫️ Ошибка при муте: {e}")

    elif cmd_candidate == c_unmute.lower():
        try:
            await bot.restrict_chat_member(
                m.chat.id,
                target_id,
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            success_text = await get_text(m.chat.id, "unmute_success", target=target_name)
            await m.answer(success_text)
        except Exception as e:
            await m.answer(f"🌫️ Ошибка при размуте: {e}")

    elif cmd_candidate == c_warn.lower():
        reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"
        await db_query("UPDATE users SET warns = warns + 1 WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), commit=True)
        row = await db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
        warns = row[0] if row else 1
        
        success_text = await get_text(m.chat.id, "warn_success", target=target_name, warns=warns, reason=reason)
        await m.answer(success_text)

    elif cmd_candidate == c_unwarn.lower():
        await db_query("UPDATE users SET warns = MAX(0, warns - 1) WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), commit=True)
        row = await db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
        warns = row[0] if row else 0
        
        success_text = await get_text(m.chat.id, "unwarn_success", target=target_name, warns=warns)
        await m.answer(success_text)
        
