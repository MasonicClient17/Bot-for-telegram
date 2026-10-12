from datetime import datetime
import random
from aiogram import Router, F, types
from database import db_query
from utils import (
    is_authorized_chat,
    get_text,
    try_delete
)

router = Router()

FORTUNES = [
    "Сегодня квантовая запутанность на вашей стороне.",
    "Кассета с редкой записью Баха уже ждет вас в архиве.",
    "Ваш код скомпилируется с первого раза. Наверное.",
    "Необычный всплеск репутации в ближайшие часы.",
    "Время переключить частоту и настроиться на созидание."
]

@router.message(F.text)
async def economy_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip().lower()
    
    if text not in ("печенька", "cookie", "+печенька"):
        return

    await try_delete(m)

    user_id = m.from_user.id
    chat_id = m.chat.id
    today_str = datetime.now().strftime("%Y-%m-%d")

    cookie_row = await db_query(
        "SELECT last_date FROM daily_cookies WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
        fetchone=True
    )

    if cookie_row and cookie_row[0] == today_str:
        cooldown_text = await get_text(chat_id, "cookie_cooldown")
        await m.answer(cooldown_text)
        return

    tapes_reward = 1
    fortune_text = random.choice(FORTUNES)

    await db_query(
        "INSERT OR REPLACE INTO daily_cookies (chat_id, user_id, last_date) VALUES (?,?,?)",
        (chat_id, user_id, today_str),
        commit=True
    )

    await db_query(
        "UPDATE users SET tapes = tapes + ? WHERE chat_id=? AND user_id=?",
        (tapes_reward, chat_id, user_id),
        commit=True
    )

    success_text = await get_text(
        chat_id,
        "cookie_get",
        text=fortune_text,
        tapes=tapes_reward
    )
    await m.answer(success_text)
    
