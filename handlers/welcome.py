import re
from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, schedule_sync, try_delete, get_display_name

router = Router()

@router.message(F.new_chat_members)
async def welcome_new_members(m: types.Message):
    res = await db_query("SELECT welcome_text FROM welcome_messages WHERE chat_id=?", (m.chat.id,), fetchone=True)
    for user in m.new_chat_members:
        if user.is_bot: continue
        un = user.username.lower() if user.username else ""
        await db_query("INSERT INTO chat_members VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username", (m.chat.id, user.id, user.first_name, un), commit=True)
        if not res or not res[0]: continue
        uname = await get_display_name(m.chat.id, user.id, user.first_name)
        txt = html.quote(res[0])
        txt = txt.replace("{user}", html.quote(uname)).replace("{chat}", html.quote(m.chat.title or "Сад"))
        await m.answer(f"🌸 {txt}")

@router.message(F.text.startswith("+приветствие"))
async def set_welcome(m: types.Message):
    if not await check_access(m, "+приветствие"): return
    text = m.text[13:].strip()
    if not text:
        return await m.answer("🫗 Укажите текст приветствия!\nПример: <code>+приветствие Добро пожаловать в {chat}, {user}!</code>\n\nПеременные: <code>{user}</code>, <code>{chat}</code>")
    await db_query("INSERT INTO welcome_messages VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET welcome_text=excluded.welcome_text", (m.chat.id, text), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("🌸 Приветствие для новых участников успешно установлено!")

@router.message(F.text.startswith("-приветствие"))
async def remove_welcome(m: types.Message):
    if not await check_access(m, "-приветствие"): return
    await db_query("DELETE FROM welcome_messages WHERE chat_id=?", (m.chat.id,), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("🗑 Приветствие отключено.")

@router.message(F.text.lower() == "приветствие")
async def show_welcome(m: types.Message):
    res = await db_query("SELECT welcome_text FROM welcome_messages WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not res or not res[0]:
        return await m.answer("🫙 Приветствие в этом чате не установлено.")
    await m.answer(f"🌸 <b>Текущее приветствие:</b>\n\n{html.quote(res[0])}")
  
