import re
from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, get_user_lvl, resolve_target, get_display_name, try_delete, schedule_sync

router = Router()

@router.message(F.text.startswith("+ник"))
async def set_nick(m: types.Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: <code>+ник [ник]</code>")
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m.chat.id, m.from_user.id) < 1:
        return await m.answer("🌫 Менять ники другим могут только модераторы.")
    await db_query("INSERT INTO users (chat_id, user_id, rp_name) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name=excluded.rp_name", (m.chat.id, tid, p[1].strip()), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🏷 РП-ник для {html.quote(tname)}: <b>{html.quote(p[1].strip())}</b>")

@router.message(F.text == "-ник")
async def rem_nick(m: types.Message):
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m.chat.id, m.from_user.id) < 1:
        return await m.answer("🌫 Сбрасывать ники другим могут только модераторы.")
    await db_query("UPDATE users SET rp_name=NULL WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🏷 ник {html.quote(tname)} сброшен.")

@router.message(F.text.startswith("+тэг"))
async def set_tag_handler(m: types.Message):
    if not await check_access(m, "+ник"): return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2: return await m.answer("Использование: <code>+тэг [название]</code>")
    
    tid, tname, tstr = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
        
    tag_val = parts[1].strip()
    if tstr and (tstr.startswith("@") or tstr.isdigit()):
        tag_val = re.sub(re.escape(tstr), "", tag_val, flags=re.I).strip()
    if not tag_val: return await m.answer("🫗 Укажите название тэга!")

    await db_query("INSERT INTO user_tags (chat_id, user_id, tag_name) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tag_name=excluded.tag_name", (m.chat.id, tid, tag_val), commit=True)
    schedule_sync(); await try_delete(m)
    disp_name = await get_display_name(m.chat.id, tid, tname)
    await m.answer(f"🏷 Пользователю {html.quote(disp_name)} присвоен тэг: <b>{html.quote(tag_val)}</b>")

@router.message(F.text.startswith("-тэг"))
async def rem_tag_handler(m: types.Message):
    if not await check_access(m, "+ник"): return
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
        
    await db_query("DELETE FROM user_tags WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    disp_name = await get_display_name(m.chat.id, tid, tname)
    await m.answer(f"🏷 Тэг у {html.quote(disp_name)} был удалён.")
  
