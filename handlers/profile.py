from aiogram import Router, F, types, html
from database import db_query, get_text
from utils import get_display_name, get_user_tag

router = Router()

@router.message(F.text.lower().in_(["профиль", "кто я"]))
async def profile_handler(m: types.Message):
    if m.chat.type == "private":
        return

    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    
    user_data = await db_query(
        "SELECT msg_count, tapes, status, rep FROM users WHERE chat_id=? AND user_id=?",
        (m.chat.id, target.id),
        fetchone=True
    )
    
    msg_count = user_data[0] if user_data else 0
    tapes = user_data[1] if user_data else 0
    status = user_data[2] if (user_data and user_data[2]) else "отсутствует"
    rep = user_data[3] if user_data else 0
    
    display_name = await get_display_name(m.chat.id, target.id, target.first_name)
    tag = await get_user_tag(m.chat.id, target.id)
    tag_str = f" [{tag}]" if tag else ""

    # Инвентарь
    items = await db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND count>0", (m.chat.id, target.id), fetchall=True)
    inv_str = ", ".join([f"<b>{i[0]}</b>" + (f" (x{i[1]})" if i[1] > 1 else "") for i in items]) if items else "пусто"

    title = await get_text(m.chat.id, "profile_title", user=html.quote(display_name))
    
    text = (
        f"{title}{tag_str}\n\n"
        f"☕ <b>Статус:</b> {html.quote(status)}\n"
        f"💬 <b>Сообщений:</b> {msg_count}\n"
        f"📼 <b>Кассеты:</b> {tapes}\n"
        f"⭐ <b>Репутация:</b> {rep}\n"
        f"🎒 <b>Владеет:</b> {inv_str}"
    )
    await m.answer(text)

# Установка статуса
@router.message(F.text.lower().startswith("+статус"))
async def set_status(m: types.Message):
    if m.chat.type == "private":
        return
    new_status = m.text[7:].strip()
    if not new_status:
        return await m.answer("☕ Укажите текст статуса (например: <code>+статус пью чай с печеньками</code>)")
    
    await db_query("UPDATE users SET status=? WHERE chat_id=? AND user_id=?", (new_status, m.chat.id, m.from_user.id), commit=True)
    await m.answer(f"🌿 Ваш уютный статус успешно обновлен: <b>{html.quote(new_status)}</b>")

@router.message(F.text.lower().in_(["-статус", "убрать статус"]))
async def clear_status(m: types.Message):
    if m.chat.type == "private":
        return
    await db_query("UPDATE users SET status=NULL WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), commit=True)
    await m.answer("☕ Статус очищен.")
