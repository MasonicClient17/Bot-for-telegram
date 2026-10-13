import re
from datetime import datetime
from aiogram import Router, F, types
from aiogram.handler import SkipHandler
from database import db_query
from config import STORAGE_CHAT_ID
from utils import is_authorized_chat, check_access, try_delete, get_text, get_cmd_name, resolve_target
from phrases import DEFAULT_COMMANDS

router = Router()

@router.message(F.text)
async def custom_cmds_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        raise SkipHandler()

    text = m.text.strip()
    text_lower = text.lower()

    # 1. Сохранение бэкапа
    save_trigger = await get_cmd_name(m.chat.id, "save")
    if text_lower in (save_trigger.lower(), f"/{save_trigger.lower()}"):
        if m.chat.id != STORAGE_CHAT_ID and not await check_access(m, "save"):
            raise SkipHandler()
        await try_delete(m)
        try:
            from database import backup_to_telegram
            await backup_to_telegram()
            msg_text = await get_text(m.chat.id, "backup_success")
            await m.answer(msg_text)
        except Exception as e:
            err_text = await get_text(m.chat.id, "backup_error", error=str(e))
            await m.answer(err_text)
        return

    # 2. Профиль
    cmd_profile = await get_cmd_name(m.chat.id, "profile")
    cmd_whoami = await get_cmd_name(m.chat.id, "whoami")
    cmd_whois = await get_cmd_name(m.chat.id, "whois")

    if text_lower in (cmd_profile.lower(), cmd_whoami.lower(), cmd_whois.lower()):
        target_id = await resolve_target(m) or m.from_user.id
        target_row = await db_query("SELECT joined_at, tapes, msg_count, status, rep FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
        member_row = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
        norm_row = await db_query("SELECT min_messages FROM chat_norms WHERE chat_id=?", (m.chat.id,), fetchone=True)

        user_name = member_row[0] if member_row else "Участник"
        joined_at = target_row[0] if target_row else datetime.now().strftime("%d.%m.%Y")
        tapes = target_row[1] if target_row else 0
        msg_count = target_row[2] if target_row else 0
        status = target_row[3] if target_row else "Участник"
        rep = target_row[4] if target_row else 0
        min_norm = norm_row[0] if norm_row else 0

        profile_text = await get_text(m.chat.id, "profile", user=user_name, joined_at=joined_at, tapes=tapes, msg_count=msg_count, min_norm=min_norm, status=status, rep=rep)
        await m.answer(profile_text)
        return

    # 3. Изменить команду
    if text_lower.startswith("изменить"):
        if not await check_access(m, "ban"):
            no_acc = await get_text(m.chat.id, "no_access")
            await m.answer(no_acc)
            return
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await m.answer("🌫️ Использование: <code>изменить [старое] [новое]</code>")
            return
        old_name, new_name = parts[1].strip().lower(), parts[2].strip().lower()
        
        action_key = old_name
        for key, default_trigger in DEFAULT_COMMANDS.items():
            if default_trigger.lower() == old_name:
                action_key = key
                break

        await db_query("INSERT OR REPLACE INTO dynamic_commands (chat_id, action_key, cmd_name) VALUES (?,?,?)", (m.chat.id, action_key, new_name), commit=True)
        await try_delete(m)
        success_msg = await get_text(m.chat.id, "cmd_changed", old_cmd=old_name, new_cmd=new_name)
        await m.answer(success_msg)
        return

    # 4. Кастомные команды
    custom_res = await db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, text_lower.split()[0]), fetchone=True)
    if custom_res:
        await try_delete(m)
        await m.answer(custom_res[0])
        return

    raise SkipHandler()
    
