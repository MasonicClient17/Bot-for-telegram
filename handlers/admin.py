,import re
from datetime import datetime
from aiogram import Router, F, types, html
from aiogram.types import ChatPermissions
from config import LEVEL_NAMES
from database import db_query
from utils import check_access, resolve_target, get_display_name, parse_mod_args, try_delete, schedule_sync

router = Router()

@router.message(F.text.lower().startswith(("+тессак", "-тессак", "тессак")))
async def admin_tapes_handler(m: types.Message):
    if not await check_access(m, "+тессак"): return
    text = m.text.strip()
    if text.lower().startswith("+тессак"): mode, rest = "add", text[7:].strip()
    elif text.lower().startswith("-тессак"): mode, rest = "sub", text[7:].strip()
    else: mode, rest = "set", text[6:].strip()

    match = re.match(r"^(\d+)(.*)$", rest)
    if not match: return await m.answer("🫗 Формат: <code>тессак [число] [пользователь]</code>")

    amount = int(match.group(1))
    tid, tname, _ = await resolve_target(m)
    sender_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)

    is_self = False
    if not tid or tid == m.from_user.id:
        target_id, target_name, is_self = m.from_user.id, sender_name, True
    else:
        target_id, target_name = tid, await get_display_name(m.chat.id, tid, tname)

    current_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
    current_tapes = current_tapes_res[0] if current_tapes_res else 0

    new_val = current_tapes + amount if mode == "add" else (max(0, current_tapes - amount) if mode == "sub" else amount)
    await db_query("INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=excluded.tapes", (m.chat.id, target_id, new_val), commit=True)
    
    schedule_sync(); await try_delete(m)
    safe_s, safe_t = html.quote(sender_name), html.quote(target_name)
    await m.answer(f"🌸 <b>{safe_s}</b> материализовал(а) {new_val}📼 из ниоткуда" + ("" if is_self else f" и отдал(а) их <b>{safe_t}</b>."))

@router.message(F.text.lower().startswith(("напоить сиропом", "клиновый сироп", "дать воды")))
async def mute_handler(m: types.Message):
    if not await check_access(m, "напоить сиропом"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid: return await m.answer("🌸 Ответьте на сообщение пользователя!")
    await try_delete(m)
    safe_tname = html.quote(tname)
    if m.text.lower().startswith("дать воды"):
        try:
            await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
            return await m.answer(f"🥛 {safe_tname} получил(а) воды!")
        except Exception as e: return await m.answer(f"👁 Ошибка: {e}")
    mins, r_str = parse_mod_args(m.text, tstr, ["напоить сиропом", "клиновый сироп"])
    try:
        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=int(datetime.now().timestamp()) + mins*60)
        await m.answer(f"🫗 {safe_tname} отправлен молчать на {mins} мин.{r_str}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@router.message(F.text.lower().startswith("дать плод всей боли"))
async def mute_24h_handler(m: types.Message):
    if not await check_access(m, "дать плод всей боли"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid: return await m.answer("🌸 Ответьте на сообщение пользователя!")
    reason = parse_mod_args(m.text, tstr, ["дать плод всей боли"])[1]
    try:
        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=int(datetime.now().timestamp()) + 86400)
        await try_delete(m); await m.answer(f"🍇 {html.quote(tname)} вкусил(а) плод всей боли...{reason}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@router.message(F.text.lower().startswith(("варн", "отругать")))
async def give_warn_handler(m: types.Message):
    if not await check_access(m, "варн"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid: return await m.answer("🌸 Ответьте на сообщение пользователя!")
    reason = parse_mod_args(m.text, tstr, ["варн", "отругать"])[1]

    await db_query("INSERT INTO users (chat_id, user_id, warns) VALUES (?,?,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warns=warns+1", (m.chat.id, tid), commit=True)
    warns_res = await db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True)
    warns = warns_res[0] if warns_res else 0
    
    schedule_sync(); await try_delete(m)
    safe_tname = html.quote(tname)
    if warns >= 3:
        await db_query("UPDATE users SET warns=0 WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
        try:
            await m.chat.ban(tid)
            await m.answer(f"🫙 {safe_tname} получил(а) 3/3 предупреждений и запечатан(а) в банку с джемом!{reason}")
        except Exception as e: await m.answer(f"👁 Не удалось забанить: {e}")
    else:
        await m.answer(f"🌫 {safe_tname} получил(а) предупреждение [{warns}/3].{reason}")

@router.message(F.text.lower().startswith(("-варн", "снять варн")))
async def remove_warn_handler(m: types.Message):
    if not await check_access(m, "-варн"): return
    tid, tname, _ = await resolve_target(m)
    if not tid: return await m.answer("🌸 Ответьте на сообщение пользователя!")
    warns_res = await db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True)
    warns = warns_res[0] if warns_res else 0
    if warns <= 0: return await m.answer(f"🌸 У {html.quote(tname)} нет предупреждений.")

    await db_query("UPDATE users SET warns=? WHERE chat_id=? AND user_id=?", (warns - 1, m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 У {html.quote(tname)} снято предупреждение. Теперь: [{warns - 1}/3].")

@router.message(F.text.lower().startswith(("-варны", "снять все варны")))
async def clear_warns_handler(m: types.Message):
    if not await check_access(m, "-варны"): return
    tid, tname, _ = await resolve_target(m)
    if not tid: return await m.answer("🌸 Ответьте на сообщение пользователя!")
    await db_query("UPDATE users SET warns=0 WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Все предупреждения с {html.quote(tname)} сняты! [0/3].")

@router.message(F.text.lower().startswith(("в банку", "банка с джемом")))
async def ban_handler(m: types.Message):
    if not await check_access(m, "в банку"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid: return await m.answer("🫗 Ответьте на сообщение пользователя!")
    reason = parse_mod_args(m.text, tstr, ["в банку", "банка с джемом"])[1]
    try:
        await m.chat.ban(tid); await try_delete(m)
        await m.answer(f"🫙 {html.quote(tname)} запечатан(а) в банку с джемом.{reason}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@router.message(F.text.lower().startswith("вытащить из банки"))
async def unban_handler(m: types.Message):
    if not await check_access(m, "в банку"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Укажите пользователя")
    try:
        await m.chat.unban(tid, only_if_banned=True)
        await try_delete(m)
        await m.answer(f"🌸 {html.quote(tname)} достали из банки!")
    except Exception as e:
        await m.answer(f"👁 Ошибка: {e}")
        
@router.message(F.text.lower().startswith("сменить"))
async def change_cmd_level_handler(m: types.Message):
    if not await check_access(m, "сменить"): return
    mat = re.search(r"^сменить\s*\((.+?)\)\s*(\d+)$", m.text.strip(), re.I)
    if not mat: return await m.answer("🫗 Формат: <code>сменить (команда) уровень</code>")
    cmd, lvl = mat.group(1).strip().lower(), int(mat.group(2))
    if not (0 <= lvl <= 4): return await m.answer("🫗 Уровень должен быть от 0 до 4!")
    await db_query("INSERT INTO cmd_levels VALUES (?,?,?) ON CONFLICT(chat_id, cmd_name) DO UPDATE SET min_lvl=excluded.min_lvl", (m.chat.id, cmd, lvl), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Уровень допуска для ({html.quote(cmd)}) изменён на {lvl} ({LEVEL_NAMES[lvl]}).")
  
