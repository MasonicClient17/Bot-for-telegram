import re
from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, try_delete, schedule_sync

router = Router()

@router.message(F.text.startswith(("+устав", "+правила")))
async def edit_rules_handler(m: types.Message):
    if not await check_access(m, "+устав"): return
    cnt = re.sub(r"^(\+устав|\+правила)", "", m.text, flags=re.I).strip()
    m_app = re.match(r"^(\d+)\+\s+(.+?)\s+(.+)$", cnt, re.S)
    if m_app:
        sec, title, text = int(m_app.group(1)), m_app.group(2).strip(), m_app.group(3).strip()
        max_item_res = await db_query("SELECT MAX(item) FROM rules WHERE chat_id=? AND section=?", (m.chat.id, sec), fetchone=True)
        nxt = ((max_item_res[0] if max_item_res else 0) or 0) + 1
        await db_query("INSERT INTO rules VALUES (?,?,?,?,?)", (m.chat.id, sec, nxt, title, text), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Добавлен пункт {sec}.{nxt} [{html.quote(title)}] в конец раздела {sec}!")
    m_itm = re.match(r"^(\d+)\.(\d+)\s+(.+?)\s+(.+)$", cnt, re.S)
    if m_itm:
        sec, itm, title, text = int(m_itm.group(1)), int(m_itm.group(2)), m_itm.group(3).strip(), m_itm.group(4).strip()
        await db_query("INSERT INTO rules VALUES (?,?,?,?,?) ON CONFLICT(chat_id, section, item) DO UPDATE SET title=excluded.title, content=excluded.content", (m.chat.id, sec, itm, title, text), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Пункт {sec}.{itm} [{html.quote(title)}] успешно сохранен!")
    m_sec = re.match(r"^(\d+)\s+(.+)$", cnt)
    if m_sec:
        sec, title = int(m_sec.group(1)), m_sec.group(2).strip()
        await db_query("INSERT INTO rules VALUES (?,?,0,?,'') ON CONFLICT(chat_id, section, item) DO UPDATE SET title=excluded.title", (m.chat.id, sec, title), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Раздел {sec} [{html.quote(title)}] создан!")
    await m.answer("🫗 Неверный формат!")

@router.message(F.text.lower().startswith(("устав", "правила")))
async def view_rules_handler(m: types.Message):
    if not await check_access(m, "устав"): return
    arg = re.sub(r"^(устав|правила)", "", m.text, flags=re.I).strip()
    m_itm = re.match(r"^(\d+)\.(\d+)$", arg)
    if m_itm:
        sec, itm = int(m_itm.group(1)), int(m_itm.group(2))
        res = await db_query("SELECT title, content FROM rules WHERE chat_id=? AND section=? AND item=?", (m.chat.id, sec, itm), fetchone=True)
        return await m.answer(f"📜 <b>Правило {sec}.{itm}: {html.quote(res[0])}</b>\n\n{html.quote(res[1])}" if res else f"🫙 Правило {sec}.{itm} не найдено!")
    if arg.isdigit():
        items = await db_query("SELECT item, title, content FROM rules WHERE chat_id=? AND section=? ORDER BY item ASC", (m.chat.id, int(arg)), fetchall=True)
        if not items: return await m.answer(f"👁 Раздел {arg} не найден!")
        stitle = items[0][1] if items[0][0] == 0 else f"Раздел {arg}"
        txt = f"📜 <b>Раздел {arg}. {html.quote(stitle)}</b>\n\n" + "\n\n".join([f"<b>{arg}.{i} {html.quote(t)}</b>\n{html.quote(c)}" for i, t, c in items if i != 0])
        return await m.answer(txt)
    all_rules = await db_query("SELECT section, item, title, content FROM rules WHERE chat_id=? ORDER BY section ASC, item ASC", (m.chat.id,), fetchall=True)
    if not all_rules: return await m.answer("👁 Устав ещё пуст!")
    txt, cur_sec = "📜 <b>Устав / Правила чата:</b>\n\n", None
    for sec, itm, title, content in all_rules:
        if sec != cur_sec:
            cur_sec = sec
            txt += f"\n🔻 <b>Раздел {sec}. {html.quote(title)}</b>\n" if itm == 0 else f"\n🔻 <b>Раздел {sec}</b>\n"
        if itm != 0: txt += f"▪️ <b>{sec}.{itm} {html.quote(title)}</b>: {html.quote(content)}\n"
    await m.answer(txt)
  
