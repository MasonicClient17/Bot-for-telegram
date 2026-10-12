import re
import random
import itertools
from aiogram import Router, F, types, html
from config import FORBIDDEN_PATTERNS, CALL_EMOJIS, STORAGE_CHAT_ID
from database import db_query
from utils import check_access, resolve_target, get_display_name, get_user_stats, track_user_and_daily, try_delete, schedule_sync, backup_to_telegram

router = Router()

@router.message(F.text.in_(["/safe", "/save"]))
async def manual_safe_handler(m: types.Message):
    if m.chat.id != STORAGE_CHAT_ID: return
    await backup_to_telegram()
    await m.answer("📦 <b>Вся информация бота успешно сохранена!</b>")

@router.message(F.text.lower().startswith(("калл", "call", "созыв")))
async def call_all_handler(m: types.Message):
    if not await check_access(m, "калл"): return
    members = await db_query("SELECT user_id FROM chat_members WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not members: return await m.answer("🫙 В базе пока нет записанных участников!")
    reason = re.sub(r"^(калл|call|созыв)", "", m.text, flags=re.I).strip()
    hdr = f"🌈 Общий сбор!\n{html.quote(reason)}\n\n" if reason else "🌈 Общий сбор!\n\n"
    mentions, emo_cycle = [], itertools.cycle(CALL_EMOJIS)
    for (uid,) in members:
        mentions.append(f'<a href="tg://user?id={uid}">{next(emo_cycle)}</a>')
    await try_delete(m)
    for i in range(0, len(mentions), 50):
        await m.answer((hdr if i == 0 else "") + " ".join(mentions[i:i+50]))

@router.message(F.text.startswith(("+команда", "+комманда")))
async def add_cmd(m: types.Message):
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: <code>+команда [имя] [текст]</code>")
    cn = p[1].lower().strip()
    if any(re.fullmatch(pat, cn) for pat in FORBIDDEN_PATTERNS):
        return await m.answer("👁️ Совпадает с системной командой.")
    if await db_query("SELECT command_name FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, cn), fetchone=True):
        return await m.answer(f"👁 Команда <code>{html.quote(cn)}</code> уже существует!")
    await db_query("INSERT INTO custom_commands VALUES (?,?,?)", (m.chat.id, cn, p[2]), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 <code>{html.quote(cn)}</code> сохранена!")

@router.message(F.text.startswith(("-команда", "-комманда")))
async def del_cmd(m: types.Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: <code>-команда [имя]</code>")
    cn = p[1].lower().strip()
    await db_query("DELETE FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, cn), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 <code>{html.quote(cn)}</code> удалена!")

@router.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_cmds(m: types.Message):
    cmds = await db_query("SELECT command_name FROM custom_commands WHERE chat_id=? ORDER BY command_name", (m.chat.id,), fetchall=True)
    if not cmds: return await m.answer("📝 В чате нет РП-команд.")
    await try_delete(m)
    await m.answer("🌈 <b>РП-команды:</b>\n\n" + "\n".join([f"• <code>{html.quote(c[0])}</code>" for c in cmds]))

@router.message(F.text)
async def process_msg(m: types.Message):
    if m.chat.type == "private" or not m.from_user: return
    try: await track_user_and_daily(m)
    except Exception as e: logging.error(f"[TRACK_ERROR] {e}")

    t = m.text.lower().strip()
    cmd = await db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, t), fetchone=True)
    if cmd:
        await try_delete(m)
        sender = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
        tid, tname, _ = await resolve_target(m)
        reply_user = await get_display_name(m.chat.id, tid, tname) if tid else "кого-то"
        reply_txt = (m.reply_to_message.text or m.reply_to_message.caption or "") if m.reply_to_message else ""
        users = await db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=?", (m.chat.id,), fetchall=True)
        rand_user = await get_display_name(m.chat.id, random.choice(users)[0], random.choice(users)[1]) if users else "Кто-то"

        s_day, s_week, _, _, _ = await get_user_stats(m.chat.id, m.from_user.id)
        r_day, r_week, _, _, _ = await get_user_stats(m.chat.id, tid) if tid else (0, 0, "", 0, 0)

        res = cmd[0]
        replacements = {
            r"\{user\}": html.quote(sender), r"\{u\}": html.quote(sender), r"\{username\}": html.quote(sender),
            r"\{reply\}": html.quote(reply_user), r"\{r\}": html.quote(reply_user),
            r"\{reply_message\}": html.quote(reply_txt), r"\{reply_text\}": html.quote(reply_txt), r"\{rt\}": html.quote(reply_txt),
            r"\{random\}": html.quote(rand_user), r"\{rn\}": html.quote(rand_user),
            r"\{day\}": str(s_day), r"\{week\}": str(s_week), r"\{reply_day\}": str(r_day), r"\{reply_week\}": str(r_week)
        }
        for pat, val in replacements.items():
            res = re.sub(pat, val, res, flags=re.I)
        await m.answer(res)
      
