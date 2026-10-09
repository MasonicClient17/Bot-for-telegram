import math
import re
from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, resolve_target, get_display_name, get_user_stats, try_delete, schedule_sync

router = Router()

@router.message(F.text.lower().startswith(("кто я", "профиль")))
async def user_profile_handler(m: types.Message):
    if not await check_access(m, "кто я"): return
    
    tid, tname, _ = await resolve_target(m)
    if not tid:
        tid = m.from_user.id
        tname = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    
    safe_tname = html.quote(tname)
    day_cnt, week_cnt, joined_date, tapes, _ = await get_user_stats(m.chat.id, tid)
    same_count = (day_cnt == week_cnt)
    
    cm_data = await db_query("SELECT username FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True)
    un_prefix = f"(@{html.quote(cm_data[0])}) " if cm_data and cm_data[0] else ""
    full_user_str = f"{un_prefix}{safe_tname}"
    
    if week_cnt <= 10:
        msg = f"🌸 Похоже {full_user_str} немногословна~ всего <b>{week_cnt}</b> сообщений на этой неделе." + (f" А сегодня <b>{day_cnt}</b>." if not same_count else "")
    elif 11 <= week_cnt <= 30:
        msg = f"🌸 У этой мультяшки {full_user_str} всего <b>{week_cnt}</b> сообщений за неделю~." + (f" За сегодня <b>{day_cnt}</b>." if not same_count else "")
    elif 31 <= week_cnt <= 70:
        msg = f"🌸 Ох~ у этой мультяшки {full_user_str} <b>{week_cnt}</b> сообщений за эту неделю." + (f" А за сегодня <b>{day_cnt}</b>~" if not same_count else "")
    elif 71 <= week_cnt <= 100:
        msg = f"🌸 Ого, у этой мультяшки {full_user_str} <b>{week_cnt}</b> сообщений за эту неделю!~\n{safe_tname}, вы молодец!" + (f"\nА за сегодня <b>{day_cnt}</b> сообщений." if not same_count else "")
    else:
        msg = f"🌸 Вот это да~ <b>{week_cnt}</b> сообщений в неделю 👏🏻👏🏻\n{full_user_str}, вы молодец!✨" + (f"\nСегодня <b>{day_cnt}</b> сообщений." if not same_count else "")
            
    msg += f"\n\n📼 Баланс кассет: <b>{tapes}</b>📼\n✨ присоединилась к саду: <b>{html.quote(str(joined_date))}</b>"
    
    await try_delete(m)
    await m.answer(msg)

@router.message(F.text.lower().startswith(("стата", "статистика")))
async def tapes_stats_handler(m: types.Message):
    if not await check_access(m, "стата"): return
    args = re.sub(r"^(стата|статистика)", "", m.text.lower().strip()).strip()
    page = max(1, int(args) if args.isdigit() else 1)
    
    all_users = await db_query("SELECT u.user_id, u.tapes, cm.first_name FROM users u LEFT JOIN chat_members cm ON u.user_id=cm.user_id AND u.chat_id=cm.chat_id WHERE u.chat_id=?", (m.chat.id,), fetchall=True) or []
    tapes_list = sorted([(await get_display_name(m.chat.id, uid, fn or f"ID:{uid}"), tapes or 0) for uid, tapes, fn in all_users], key=lambda x: x[1], reverse=True)
    
    tot = len(tapes_list)
    pages = math.ceil(tot / 10) or 1
    if page > pages and tot > 0:
        return await m.answer(f"🫗 Страницы {page} не существует. Всего страниц: {pages}")
        
    start_idx = (page - 1) * 10
    page_data = tapes_list[start_idx:start_idx + 10]
    
    txt = f"📼 <b>Статистика кассет у участников [Стр. {page}/{pages}]:</b>\n\n"
    txt += "\n".join([f"{i}. {html.quote(name)} — {tapes} 📼" for i, (name, tapes) in enumerate(page_data, start_idx + 1)]) if page_data else "🫙 В чате пока нет записанных балансов."
        
    await try_delete(m)
    await m.answer(txt)

@router.message(F.text.lower().startswith("актив"))
async def msg_activity_handler(m: types.Message):
    if not await check_access(m, "актив"): return
    raw_text = m.text.lower().strip()
    is_daily = "день" in raw_text
    args = re.sub(r"^актив", "", raw_text).replace("день", "").strip()
    page = max(1, int(args) if args.isdigit() else 1)
    
    all_users = await db_query("SELECT u.user_id, cm.first_name FROM users u LEFT JOIN chat_members cm ON u.user_id=cm.user_id AND u.chat_id=cm.chat_id WHERE u.chat_id=?", (m.chat.id,), fetchall=True) or []
    user_stats_list = []
    for uid, fn in all_users:
        day_cnt, week_cnt, _, _, _ = await get_user_stats(m.chat.id, uid)
        cnt = day_cnt if is_daily else week_cnt
        if cnt > 0:
            user_stats_list.append((await get_display_name(m.chat.id, uid, fn or f"ID:{uid}"), cnt))
            
    user_stats_list.sort(key=lambda x: x[1], reverse=True)
    tot = len(user_stats_list)
    pages = math.ceil(tot / 10) or 1
    if page > pages and tot > 0:
        return await m.answer(f"🫗 Страницы {page} не существует. Всего: {pages}")
        
    start_idx = (page - 1) * 10
    page_data = user_stats_list[start_idx:start_idx + 10]
    
    title_mode = "дневной" if is_daily else "недельный"
    txt = f"📊 <b>Активность участников ({title_mode}) [Стр. {page}/{pages}]:</b>\n\n"
    txt += "\n".join([f"{i}. {html.quote(name)} — {cnt} сообщ." for i, (name, cnt) in enumerate(page_data, start_idx + 1)]) if page_data else "🫙 В этом периоде пока нет активности."
        
    await try_delete(m)
    await m.answer(txt)

@router.message(F.text.lower().startswith("кассеты"))
async def transfer_tapes_handler(m: types.Message):
    if not await check_access(m, "кассеты"): return
    match = re.match(r"^кассеты\s+(\d+)(.*)$", m.text.strip(), re.I)
    if not match: return await m.answer("🫗 Использование: <code>кассеты [число] [юзернейм/ответ]</code>")
    
    amount = int(match.group(1))
    if amount <= 0: return await m.answer("🫗 Число кассет должно быть больше 0!")

    tid, tname, _ = await resolve_target(m)
    if not tid: return await m.answer("🫗 Укажите пользователя или ответьте на его сообщение!")
    if tid == m.from_user.id: return await m.answer("🫗 Нельзя передавать кассеты самому себе!")

    sender_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    if (sender_tapes_res[0] if sender_tapes_res else 0) < amount:
        return await m.answer("📼 Недостаточно кассет!")

    sender_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    receiver_name = await get_display_name(m.chat.id, tid, tname)

    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (amount, m.chat.id, m.from_user.id), commit=True)
    await db_query("INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=COALESCE(tapes,0)+excluded.tapes", (m.chat.id, tid, amount), commit=True)

    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 <b>{html.quote(sender_name)}</b> отправил(а) {amount}📼 <b>{html.quote(receiver_name)}</b>")
  
