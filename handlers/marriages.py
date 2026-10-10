from datetime import datetime
from aiogram import Router, F, types, html
from database import db_query
from utils import get_display_name, try_delete, schedule_sync

router = Router()

@router.message(F.text.lower().startswith(("+брак", "брак", "пожениться")))
async def create_marriage_handler(m: types.Message):
    if m.chat.type == "private":
        return await m.answer("☕ Заключать браки нужно в общем чате!")

    u1_id, u2_id = None, None

    # Если команда отправлена ответом на сообщение
    if m.reply_to_message and m.reply_to_message.from_user:
        u1_id = m.from_user.id
        u2_id = m.reply_to_message.from_user.id
    else:
        mentions = []
        if m.entities:
            for entity in m.entities:
                if entity.type == "text_mention" and entity.user:
                    mentions.append(entity.user.id)
                elif entity.type == "mention":
                    un = m.text[entity.offset:entity.offset + entity.length].lstrip("@").lower().strip()
                    res = await db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
                    if res:
                        mentions.append(res[0])
        
        if len(mentions) == 1:
            u1_id = m.from_user.id
            u2_id = mentions[0]
        elif len(mentions) >= 2:
            u1_id = mentions[0]
            u2_id = mentions[1]

    if not u1_id or not u2_id:
        return await m.answer("☕ <b>Использование:</b> ответьте на сообщение участника командой <code>+брак</code> или напишите <code>+брак @user</code>")

    if u1_id == u2_id:
        return await m.answer("🌿 Нельзя заключить брак с самим собой!")

    # Проверка, не состоит ли кто-то уже в браке
    existing = await db_query(
        "SELECT * FROM marriages WHERE chat_id=? AND (user1_id=? OR user2_id=? OR user1_id=? OR user2_id=?)",
        (m.chat.id, u1_id, u1_id, u2_id, u2_id),
        fetchone=True
    )
    if existing:
        return await m.answer("🌿 Один из участников уже состоит в браке! Сначала нужно оформить развод.")

    today_str = datetime.now().strftime("%Y-%m-%d")
    await db_query("INSERT INTO marriages VALUES (?,?,?,?)", (m.chat.id, u1_id, u2_id, today_str), commit=True)
    
    n1 = await get_display_name(m.chat.id, u1_id, f"ID:{u1_id}")
    n2 = await get_display_name(m.chat.id, u2_id, f"ID:{u2_id}")

    schedule_sync()
    await try_delete(m)
    await m.answer(f"💍 <b>Совет да любовь!</b> Объявлен новый союз между <b>{html.quote(n1)}</b> и <b>{html.quote(n2)}</b>! 💕✨")


@router.message(F.text.lower().startswith(("-брак", "развод", "расстаться")))
async def remove_marriage_handler(m: types.Message):
    if m.chat.type == "private":
        return

    u1_id, u2_id = None, None

    if m.reply_to_message and m.reply_to_message.from_user:
        u1_id = m.from_user.id
        u2_id = m.reply_to_message.from_user.id
    else:
        # Если без ответа, проверяем брак самого пользователя
        my_marriage = await db_query(
            "SELECT user1_id, user2_id FROM marriages WHERE chat_id=? AND (user1_id=? OR user2_id=?)",
            (m.chat.id, m.from_user.id, m.from_user.id),
            fetchone=True
        )
        if my_marriage:
            u1_id, u2_id = my_marriage[0], my_marriage[1]

    if not u1_id or not u2_id:
        return await m.answer("☕ Вы не состоите в браке или не указали, чей брак нужно расторгнуть.")

    await db_query(
        "DELETE FROM marriages WHERE chat_id=? AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))",
        (m.chat.id, u1_id, u2_id, u2_id, u1_id),
        commit=True
    )
    
    schedule_sync()
    await try_delete(m)
    await m.answer("💔 Брак успешно расторгнут. Теперь вы снова свободны.")


@router.message(F.text.lower().in_(["список браков", "браки", "союзы"]))
async def list_marriages_handler(m: types.Message):
    if m.chat.type == "private":
        return

    marriages = await db_query("SELECT user1_id, user2_id, date FROM marriages WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not marriages:
        return await m.answer("🌿 В этом чате пока нет зарегистрированных союзов.")

    txt = "💍 <b>Уютные любовные союзы чата:</b>\n\n"
    for idx, (u1, u2, mdate) in enumerate(marriages, 1):
        n1 = await get_display_name(m.chat.id, u1, f"ID:{u1}")
        n2 = await get_display_name(m.chat.id, u2, f"ID:{u2}")
        txt += f"{idx}. 💕 <b>{html.quote(n1)}</b> + <b>{html.quote(n2)}</b> <i>(с {mdate})</i>\n"

    await try_delete(m)
    await m.answer(txt)
    
