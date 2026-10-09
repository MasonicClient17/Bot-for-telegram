import asyncio
import logging
import random
import re
from datetime import datetime
from aiogram import types, html
from aiogram.types import ChatPermissions
from config import bot, CREATOR_ID, DEFAULT_CMD_LEVELS
from database import db_query, backup_to_telegram

def schedule_sync():
    """Запускает фоновую задачу отправки бэкапа в Telegram."""
    asyncio.create_task(backup_to_telegram())

async def try_delete(m: types.Message):
    """Безопасное удаление сообщения."""
    try:
        await m.delete()
    except Exception:
        pass

async def delete_after_delay(msg: types.Message, delay: int = 60):
    """Удаление сообщения через задержку."""
    await asyncio.sleep(delay)
    await try_delete(msg)

async def get_user_lvl(cid: int, uid: int) -> int:
    """Получение уровня доступа пользователя."""
    if uid == CREATOR_ID:
        return 4
    try:
        member = await bot.get_chat_member(cid, uid)
        if member.status == "creator":
            return 4
    except Exception:
        pass
    res = await db_query("SELECT role_level FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    return res[0] if res and res[0] is not None else 0

async def get_req_lvl(cid: int, cmd: str) -> int:
    """Получение требуемого уровня доступа для команды."""
    c = cmd.strip().lower()
    res = await db_query("SELECT min_lvl FROM cmd_levels WHERE chat_id=? AND cmd_name=?", (cid, c), fetchone=True)
    return res[0] if res and res[0] is not None else DEFAULT_CMD_LEVELS.get(c, 0)

async def check_access(m: types.Message, cmd: str) -> bool:
    """Проверка прав пользователя на выполнение команды."""
    req = await get_req_lvl(m.chat.id, cmd)
    u_lvl = await get_user_lvl(m.chat.id, m.from_user.id)
    if u_lvl < req:
        await m.answer(f"🌫 Ваше влияние недостаточно велико! Требуется: {req}.")
        return False
    return True

async def get_user_tag(cid: int, uid: int) -> str:
    """Получение тэга пользователя."""
    res = await db_query("SELECT tag_name FROM user_tags WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    return res[0] if res and res[0] else ""

async def get_display_name(cid: int, uid: int, default_tg_name: str) -> str:
    """Формирование отображаемого имени с учётом РП-ника и тэга."""
    rp_nick = await db_query("SELECT rp_name FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    if rp_nick and rp_nick[0]:
        return rp_nick[0]
    
    rp_tag = await get_user_tag(cid, uid)
    if rp_tag:
        return rp_tag
        
    return default_tg_name

def parse_mod_args(text: str, target_str: str, prefixes: list):
    """Парсинг аргументов модерации (время и причина)."""
    cleaned = text
    for p in prefixes:
        if cleaned.lower().startswith(p):
            cleaned = cleaned[len(p):].strip()
            break
    if target_str and (target_str.startswith("@") or target_str.isdigit()):
        cleaned = re.sub(re.escape(target_str), "", cleaned, flags=re.I).strip()
    
    mins, words = 60, cleaned.split()
    if words:
        m = re.match(r"^(\d+)\s*(мин|мин.|минут|минуты|ч|час|часа|часов|д|ден|день|дня|дней)?$", words[0].lower())
        if m:
            n, u = int(m.group(1)), m.group(2) or "мин"
            mins = n * 60 if u.startswith("ч") else (n * 1440 if u.startswith("д") else n)
            words = words[1:]
    reason = " ".join(words).strip()
    return mins, (f"\n📝 <b>Причина:</b> {html.quote(reason)}" if reason else "")

async def resolve_target(m: types.Message):
    """Определение цели команды (по ответу, меншену или юзернейму)."""
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        fname = await get_display_name(m.chat.id, u.id, u.first_name)
        return u.id, fname, None

    text = m.text or m.caption or ""
    if m.entities:
        for entity in m.entities:
            if entity.type == "text_mention" and entity.user:
                u = entity.user
                fname = await get_display_name(m.chat.id, u.id, u.first_name)
                target_str = text[entity.offset:entity.offset + entity.length]
                return u.id, fname, target_str
            elif entity.type == "mention":
                raw_mention = text[entity.offset:entity.offset + entity.length]
                un = raw_mention.lstrip("@").lower().strip()
                res = await db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
                if res:
                    fname = await get_display_name(m.chat.id, res[0], res[1])
                    return res[0], fname, raw_mention
                return None, raw_mention, raw_mention

    for w in text.split():
        if w.startswith("@"):
            un = w.lstrip("@").lower().strip()
            res = await db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
            if res:
                fname = await get_display_name(m.chat.id, res[0], res[1])
                return res[0], fname, w
            return None, w, w

    return None, None, None

async def get_user_stats(cid: int, uid: int):
    """Получение статистики сообщений и баланса."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    week_str = f"{iso_year}-{iso_week}"
    
    data = await db_query("SELECT day_count, week_count, last_msg_date, week_number, joined_at, tapes, msg_count FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    if not data:
        return 0, 0, today_str, 0, 0
    
    day_c, week_c, last_date, last_week, joined, tapes, tot_c = data
    real_day = day_c if last_date == today_str else 0
    real_week = week_c if last_week == week_str else 0
    real_joined = joined or today_str
    
    return real_day, real_week, real_joined, (tapes or 0), (tot_c or 0)

async def track_user_and_daily(m: types.Message):
    """Учёт активности пользователя и выдача ежедневного бонуса."""
    cid, uid = m.chat.id, m.from_user.id
    fname, username = m.from_user.first_name, m.from_user.username
    if not uid or uid == bot.id:
        return
    un = username.lower() if username else ""
    await db_query("INSERT INTO chat_members VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username", (cid, uid, fname, un), commit=True)
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    week_str = f"{iso_year}-{iso_week}"
    
    user_data = await db_query("SELECT msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    
    is_new_day = False
    if not user_data:
        await db_query("INSERT INTO users (chat_id, user_id, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes) VALUES (?,?,1,1,1,?,?,?,0)", (cid, uid, today_str, week_str, today_str), commit=True)
        is_new_day = True
    else:
        tot_cnt, day_c, week_c, last_date, last_week, joined, tapes = user_data
        if last_date != today_str:
            is_new_day = True
        
        new_tot = (tot_cnt or 0) + 1
        new_day_c = 1 if last_date != today_str else (day_c or 0) + 1
        new_week_c = 1 if last_week != week_str else (week_c or 0) + 1
        new_joined = joined or today_str
        
        await db_query("""
            UPDATE users SET 
                msg_count=?, 
                day_count=?, 
                week_count=?, 
                last_msg_date=?, 
                week_number=?, 
                joined_at=?
            WHERE chat_id=? AND user_id=?
        """, (new_tot, new_day_c, new_week_c, today_str, week_str, new_joined, cid, uid), commit=True)

    if is_new_day:
        daily_reward = random.randint(30, 50)
        await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + ? WHERE chat_id=? AND user_id=?", (daily_reward, cid, uid), commit=True)
        uname = await get_display_name(cid, uid, fname)
        daily_msg = await m.answer(f"📼 <b>{html.quote(uname)}</b>, держи ежедневную копеечку: <b>+{daily_reward}</b> кассет!")
        asyncio.create_task(delete_after_delay(daily_msg, 60))
  
