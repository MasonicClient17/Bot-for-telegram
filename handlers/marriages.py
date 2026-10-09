from datetime import datetime
from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, get_user_lvl, get_display_name, try_delete, schedule_sync

router = Router()

@router.message(F.text.startswith("+брак"))
async def create_marriage_handler(m: types.Message):
    u_lvl = await get_user_lvl(m.chat.id, m.from_user.id)
    inv_item = await db_query("SELECT count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)='бессрочное бракосочетание' AND count > 0", (m.chat.id, m.from_user.id), fetchone=True)
    if u_lvl < 1 and not inv_item:
        return await m.answer("🌫 У вас нет прав для создания браков или предмета 'Бессрочное бракосочетание'!")

    u1_id, u2_id = None, None
    if m.reply_to_message and m.reply_to_message.from_user:
        u1_id, u2_id = m.from_user.id, m.reply_to_message.from_user.id
    else:
        mentions = []
        if m.entities:
            for entity in m.entities:
                if entity.type == "text_mention" and entity.user: mentions.append(entity.user.id)
                elif entity.type == "mention":
                    un = m.text[entity.offset:entity.offset + entity.length].lstrip("@").lower().strip()
                    res = await db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
                    if res: mentions.append(res[0])
        if len(mentions) >= 2: u1_id, u2_id = mentions[0], mentions[1]

    if not u1_id or not u2_id: return await m.answer("🫗 Использование: <code>+брак @user1 @user2</code> или <code>+брак</code> ответом!")
    if u1_id == u2_id: return await m.answer("🫗 Нельзя заключить брак с самим собой!")

    if await db_query("SELECT * FROM marriages WHERE chat_id=? AND ((user1_id=? OR user2_id=?) OR (user1_id=? OR user2_id=?))", (m.chat.id, u1_id, u1_id, u2_id, u2_id), fetchone=True):
        return await m.answer("🌸 Один из участников уже состоит в браке!")

    if u_lvl < 1 and inv_item:
        await db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND LOWER(item_name)='бессрочное бракосочетание'", (m.chat.id, m.from_user.id), commit=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    await db_query("INSERT INTO marriages VALUES (?,?,?,?)", (m.chat.id, u1_id, u2_id, today_str), commit=True)
    n1 = await get_display_name(m.chat.id, u1_id, f"ID:{u1_id}")
    n2 = await get_display_name(m.chat.id, u2_id, f"ID:{u2_id}")

    schedule_sync(); await try_delete(m)
    await m.answer(f"💍 <b>Совет да любовь!</b> Объявлен новый союз между <b>{html.quote(n1)}</b> и <b>{html.quote(n2)}</b>! 💕")

@router.message(F.text.startswith("-брак"))
async def remove_marriage_handler(m: types.Message):
    if not await check_access(m, "+брак"): return
    u1_id, u2_id = None, None
    if m.reply_to_message and m.reply_to_message.from_user:
        u1_id, u2_id = m.from_user.id, m.reply_to_message.from_user.id
    else:
        mentions = []
        if m.entities:
            for entity in m.entities:
                if entity.type == "text_mention" and entity.user: mentions.append(entity.user.id)
                elif entity.type == "mention":
                    un = m.text[entity.offset:entity.offset + entity.length].lstrip("@").lower().strip()
                    res = await db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
                    if res: mentions.append(res[0])
        if len(mentions) >= 2: u1_id, u2_id = mentions[0], mentions[1]

    if not u1_id or not u2_id: return await m.answer("🫗 Использование: <code>-брак @user1 @user2</code> или <code>-брак</code> ответом!")

    await db_query("DELETE FROM marriages WHERE chat_id=? AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))", (m.chat.id, u1_id, u2_id, u2_id, u1_id), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("💔 Брак был успешно расторгнут.")

@router.message(F.text.lower().in_(["список браков", "браки"]))
async def list_marriages_handler(m: types.Message):
    if not await check_access(m, "список браков"): return
    marriages = await db_query("SELECT user1_id, user2_id, date FROM marriages WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not marriages: return await m.answer("🫙 В этом чате пока нет зарегистрированных браков.")

    txt = "💍 <b>Список любовных союзов чата:</b>\n\n"
    for idx, (u1, u2, mdate) in enumerate(marriages, 1):
        n1 = await get_display_name(m.chat.id, u1, f"ID:{u1}")
        n2 = await get_display_name(m.chat.id, u2, f"ID:{u2}")
        txt += f"{idx}. 💕 <b>{html.quote(n1)}</b> + <b>{html.quote(n2)}</b> <i>(с {mdate})</i>\n"

    await try_delete(m); await m.answer(txt)
  
