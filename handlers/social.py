from datetime import datetime
from aiogram import Router, F, types
from database import db_query
from utils import (
    is_authorized_chat,
    get_text,
    get_cmd_name,
    resolve_target,
    try_delete
)

router = Router()

# Временный словарь для хранения предложений брака: {(chat_id, target_id): initiator_id}
PENDING_MARRIAGES = {}

@router.message(F.text)
async def social_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip()
    args = text.split()
    if not args:
        return

    cmd_candidate = args[0].lower()

    c_marry = await get_cmd_name(m.chat.id, "marry")
    c_divorce = await get_cmd_name(m.chat.id, "divorce")

    if cmd_candidate not in (c_marry.lower(), c_divorce.lower()):
        return

    await try_delete(m)

    # Обработка развода (-брак)
    if cmd_candidate == c_divorce.lower():
        marriage = await db_query(
            "SELECT user1_id, user2_id FROM marriages WHERE chat_id=? AND (user1_id=? OR user2_id=?)",
            (m.chat.id, m.from_user.id, m.from_user.id),
            fetchone=True
        )
        if not marriage:
            await m.answer("🌫️ Вы не состоите в браке.")
            return

        u1, u2 = marriage
        partner_id = u2 if u1 == m.from_user.id else u1

        await db_query(
            "DELETE FROM marriages WHERE chat_id=? AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))",
            (m.chat.id, u1, u2, u2, u1),
            commit=True
        )

        m1 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
        m2 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, partner_id), fetchone=True)
        name1 = m1[0] if m1 else "Участник"
        name2 = m2[0] if m2 else "Участник"

        divorce_text = await get_text(m.chat.id, "divorce_success", user=name1, target=name2)
        await m.answer(divorce_text)
        return

    # Обработка принятия предложения брака (+брак в ответ или при наличии приглашения)
    if (m.chat.id, m.from_user.id) in PENDING_MARRIAGES:
        initiator_id = PENDING_MARRIAGES.pop((m.chat.id, m.from_user.id))
        
        m_check = await db_query(
            "SELECT 1 FROM marriages WHERE chat_id=? AND (user1_id=? OR user2_id=? OR user1_id=? OR user2_id=?)",
            (m.chat.id, initiator_id, initiator_id, m.from_user.id, m.from_user.id),
            fetchone=True
        )
        if m_check:
            await m.answer("🌫️ Один из участников уже состоит в браке.")
            return

        today_str = datetime.now().strftime("%d.%m.%Y")
        await db_query(
            "INSERT INTO marriages (chat_id, user1_id, user2_id, date) VALUES (?,?,?,?)",
            (m.chat.id, initiator_id, m.from_user.id, today_str),
            commit=True
        )

        m1 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, initiator_id), fetchone=True)
        m2 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
        name1 = m1[0] if m1 else "Участник"
        name2 = m2[0] if m2 else "Участник"

        success_text = await get_text(m.chat.id, "marry_success", user=name1, target=name2)
        await m.answer(success_text)
        return

    # Отправка нового предложения брака
    target_id = await resolve_target(m)
    if not target_id:
        await m.answer("🌫️ Укажите участника для заключения брака (через @ или ответом на сообщение).")
        return

    if target_id == m.from_user.id:
        await m.answer("🌫️ Нельзя заключить брак с самим собой.")
        return

    m_check = await db_query(
        "SELECT 1 FROM marriages WHERE chat_id=? AND (user1_id=? OR user2_id=? OR user1_id=? OR user2_id=?)",
        (m.chat.id, m.from_user.id, m.from_user.id, target_id, target_id),
        fetchone=True
    )
    if m_check:
        await m.answer("🌫️ Вы или выбранный участник уже состоите в браке.")
        return

    PENDING_MARRIAGES[(m.chat.id, target_id)] = m.from_user.id

    m1 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    m2 = await db_query("SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True)
    name1 = m1[0] if m1 else "Участник"
    name2 = m2[0] if m2 else "Участник"

    req_text = await get_text(m.chat.id, "marry_req", user=name1, target=name2)
    await m.answer(req_text)
    
