import random
from datetime import datetime
from aiogram import Router, F, types, html
from database import db_query, get_text
from utils import get_display_name, schedule_sync

router = Router()

COOKIES_TEXTS = [
    "Сегодня тебя ждёт неожиданная чашка вкусного чая и приятный сюрприз.",
    "Твоя улыбка сегодня способна согреть даже самый хмурый чат.",
    "Отличный день, чтобы сделать то, что давно откладывал!",
    "Звёзды говорят, что сегодня удача полностью на твоей стороне.",
    "Помни: отдыхать тоже важно, не забывай баловать себя.",
    "Рядом с тобой всегда есть те, кому ты дорог."
]

@router.message(F.text.lower().in_(["печенька", "гадание", "предсказание"]))
async def cookie_handler(m: types.Message):
    if m.chat.type == "private":
        return
    today = datetime.now().strftime('%Y-%m-%d')
    res = await db_query("SELECT last_date FROM daily_cookies WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    
    if res and res[0] == today:
        text = await get_text(m.chat.id, "cookie_cooldown")
        return await m.answer(text)

    tapes_bonus = random.randint(5, 25)
    cookie_text = random.choice(COOKIES_TEXTS)

    await db_query("INSERT OR REPLACE INTO daily_cookies VALUES (?, ?, ?)", (m.chat.id, m.from_user.id, today), commit=True)
    await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + ? WHERE chat_id=? AND user_id=?", (tapes_bonus, m.chat.id, m.from_user.id), commit=True)
    schedule_sync()

    formatted = await get_text(m.chat.id, "cookie_get", tapes=tapes_bonus, text=cookie_text)
    await m.answer(formatted)

@router.message(F.text.lower().in_(["кто тут", "актив", "онлайн"]))
async def who_is_here(m: types.Message):
    if m.chat.type == "private":
        return
    active = await db_query("SELECT user_id, rp_name FROM users WHERE chat_id=? ORDER BY msg_count DESC LIMIT 10", (m.chat.id,), fetchall=True)
    if not active:
        return await m.answer("🌿 Пока тут тихо.")
    
    lines = []
    for uid, rp in active:
        member = await m.chat.get_member(uid)
        name = rp or member.user.first_name
        lines.append(f"• <b>{html.quote(name)}</b>")
    
    await m.answer("🌿 <b>Самые активные мультяшки чата:</b>\n\n" + "\n".join(lines))

# Система репутации (спасибо, красавчик, молодец)
@router.message(F.text.lower().in_(["спасибо", "спасибки", "красавчик", "красавица", "молодец", "+"]))
async def rep_handler(m: types.Message):
    if m.chat.type == "private" or not m.reply_to_message:
        return
    target = m.reply_to_message.from_user
    if target.id == m.from_user.id:
        return

    await db_query("UPDATE users SET rep = COALESCE(rep, 0) + 1 WHERE chat_id=? AND user_id=?", (m.chat.id, target.id), commit=True)
    await m.react(reaction=[types.ReactionTypeEmoji(emoji="❤️")])
  
