import asyncio, logging, os, re, random, json, aiosqlite
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command
from aiogram.types import ChatPermissions, FSInputFile

load_dotenv()
BOT_TOKEN, STORAGE_GROUP_ID = os.getenv("BOT_TOKEN", "").strip("'\""), os.getenv("STORAGE_GROUP_ID", "").strip("'\"")
bot, dp, DB_PATH = Bot(token=BOT_TOKEN), Dispatcher(), "bot_database.db"

CALL_EMOJIS = ["🌸", "☁️", "👁", "🐍", "🌫", "🥛", "🫗", "🍨", "🍧", "🌈", "🍇", "🫙"]
DEFAULT_CMD_LEVELS = {"клиновый сироп": 1, "напоить сиропом": 1, "дать плод всей боли": 1, "дать воды": 1, "калл": 1, "call": 1, "созыв": 1, "варн": 2, "отругать": 2, "актив": 2, "стата": 2, "статистика": 2, "банка с джемом": 3, "в банку": 3, "вытащить из банки": 3, "повысить": 3, "+модер": 3, "понизить": 3, "-модер": 3, "+устав": 3, "устав+": 3}
SYSTEM_RESERVED_WORDS = list(DEFAULT_CMD_LEVELS.keys()) + ["устав", "правила", "устав сада", "правила сада", "ники", "звания", "+ник", "-ник", "+команда", "-команда", "список команд", "команды", "рп команды", "+роль", "сменить"]

async def try_delete(m: types.Message):
    try: await m.delete()
    except: pass

class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        if isinstance(event, types.Message) and event.from_user and not event.from_user.is_bot and event.chat.type in ["group", "supergroup"]:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO users (chat_id, user_id, username, first_name, msg_count) VALUES (?,?,?,?,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET msg_count=msg_count+1, username=excluded.username, first_name=excluded.first_name", (event.chat.id, event.from_user.id, event.from_user.username, event.from_user.first_name))
                await db.commit()
        return await handler(event, data)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for q in [
            "CREATE TABLE IF NOT EXISTS users (chat_id INT, user_id INT, username TEXT, first_name TEXT, role_level INT DEFAULT 0, warns INT DEFAULT 0, msg_count INT DEFAULT 0, rp_name TEXT, PRIMARY KEY (chat_id, user_id))",
            "CREATE TABLE IF NOT EXISTS roles_custom (chat_id INT, level INT, title TEXT, PRIMARY KEY (chat_id, level))",
            "CREATE TABLE IF NOT EXISTS rules_chapters (chat_id INT, chapter_num INT, title TEXT, PRIMARY KEY (chat_id, chapter_num))",
            "CREATE TABLE IF NOT EXISTS rules_items (chat_id INT, chapter_num INT, rule_num INT, text TEXT, PRIMARY KEY (chat_id, chapter_num, rule_num))",
            "CREATE TABLE IF NOT EXISTS custom_commands (chat_id INT, cmd_name TEXT, cmd_text TEXT, PRIMARY KEY (chat_id, cmd_name))",
            "CREATE TABLE IF NOT EXISTS cmd_levels (chat_id INT, cmd_name TEXT, required_level INT, PRIMARY KEY (chat_id, cmd_name))"
        ]: await db.execute(q)
        await db.commit()

async def get_user_role(cid: int, uid: int) -> int:
    try:
        if (await bot.get_chat_member(cid, uid)).status == ChatMemberStatus.CREATOR: return 4
    except: pass
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role_level FROM users WHERE chat_id=? AND user_id=?", (cid, uid)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def get_req_lvl(cid: int, cmd: str) -> int:
    cmd = cmd.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT required_level FROM cmd_levels WHERE chat_id=? AND cmd_name=?", (cid, cmd)) as cur:
            row = await cur.fetchone()
            return row[0] if row else DEFAULT_CMD_LEVELS.get(cmd, 0)

async def get_disp_name(cid: int, user: types.User) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rp_name FROM users WHERE chat_id=? AND user_id=?", (cid, user.id)) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else user.full_name

def parse_dur(t: str) -> timedelta:
    m = re.search(r"(\d+)\s*(мин|ч|час|дня|день|дней|д)", (t or "").lower())
    if not m: return timedelta(minutes=60)
    v, u = int(m.group(1)), m.group(2)
    return timedelta(minutes=v) if "мин" in u else (timedelta(hours=v) if "ч" in u else timedelta(days=v))

async def resolve_target(m: types.Message) -> Optional[types.User]:
    if m.reply_to_message and m.reply_to_message.from_user: return m.reply_to_message.from_user
    txt = m.text or m.caption or ""
    for e in (m.entities or []):
        if e.type == "text_mention" and e.user: return e.user
        elif e.type == "mention":
            un = txt[e.offset:e.offset+e.length].lstrip("@").lower()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un)) as cur:
                    r = await cur.fetchone()
                    if r:
                        try: return (await bot.get_chat_member(m.chat.id, r[0])).user
                        except: pass
    return None

@dp.message(F.text.regexp(r"(?i)^сменить\s+(?:\((.*?)\)|(\S+))\s+(\d+)$"))
async def change_cmd_level(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < 4: return await m.answer("🌫 Только Создатель группы (4 уровень)!")
    mat = re.match(r"^сменить\s+(?:\((.*?)\)|(\S+))\s+(\d+)$", m.text, re.I)
    cmd, lvl = (mat.group(1) or mat.group(2)).lower().strip(), int(mat.group(3))
    if cmd not in DEFAULT_CMD_LEVELS: return await m.answer("🌫 Эту команду нельзя перенастроить!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO cmd_levels VALUES (?,?,?) ON CONFLICT(chat_id, cmd_name) DO UPDATE SET required_level=?", (m.chat.id, cmd, lvl, lvl))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 Уровень доступа для «<b>{cmd}</b>» изменен на <b>{lvl}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\+роль\s+([1-3])\s+(.+)$"))
async def set_role_title(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < 4: return await m.answer("🌫 Только Создатель!")
    mat = re.match(r"^\+роль\s+([1-3])\s+(.+)$", m.text, re.I)
    lvl, title = int(mat.group(1)), mat.group(2).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO roles_custom VALUES (?,?,?) ON CONFLICT(chat_id, level) DO UPDATE SET title=?", (m.chat.id, lvl, title, title))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 Должность уровня {lvl} переименована в «<b>{title}</b>».", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(повысить|\+модер)(\s+[1-2])?$"))
async def promote_user(m: types.Message):
    u_role = await get_user_role(m.chat.id, m.from_user.id)
    if u_role < await get_req_lvl(m.chat.id, "повысить"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Укажите пользователя!")
    mat = re.match(r"^(повысить|\+модер)(\s+[1-2])?$", m.text, re.I)
    t_lvl = int(mat.group(2).strip()) if mat.group(2) else 1
    if t_lvl >= u_role: return await m.answer("🌫 Нельзя повысить до своего уровня или выше!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (chat_id, user_id, role_level) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET role_level=?", (m.chat.id, target.id, t_lvl, t_lvl))
        await db.commit()
    if t_lvl >= 2:
        try: await bot.promote_chat_member(m.chat.id, target.id, can_manage_chat=True, can_delete_messages=True, can_restrict_members=True)
        except: pass
    await try_delete(m)
    await m.answer(f"🌸 Пользователь {target.mention_html()} назначен на уровень <b>{t_lvl}</b>!", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(понизить|-модер)$"))
async def demote_user(m: types.Message):
    u_role = await get_user_role(m.chat.id, m.from_user.id)
    if u_role < await get_req_lvl(m.chat.id, "понизить"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Укажите пользователя!")
    if await get_user_role(m.chat.id, target.id) >= u_role: return await m.answer("🌫 Вы не можете понизить этого пользователя!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET role_level=0 WHERE chat_id=? AND user_id=?", (m.chat.id, target.id))
        await db.commit()
    try: await bot.promote_chat_member(m.chat.id, target.id, can_manage_chat=False, can_delete_messages=False, can_restrict_members=False)
    except: pass
    await try_delete(m)
    await m.answer(f"🌸 Пользователь {target.mention_html()} разжалован.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(клиновый сироп|напоить сиропом)"))
async def mute_syrup(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "клиновый сироп"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте нарушителю!")
    dur = parse_dur(m.text)
    try:
        await bot.restrict_chat_member(m.chat.id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+dur)
        await try_delete(m)
        await m.answer(f"🫗 {target.mention_html()} напоен сиропом на <b>{dur}</b>.", parse_mode=ParseMode.HTML)
    except Exception as e: await m.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.regexp(r"(?i)^дать плод всей боли"))
async def mute_fruit_pain(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "дать плод всей боли"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте нарушителю!")
    try:
        await bot.restrict_chat_member(m.chat.id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(days=1))
        await try_delete(m)
        await m.answer(f"🍇 Пользователь {target.mention_html()} получил плод всей боли (24 часа).", parse_mode=ParseMode.HTML)
    except Exception as e: await m.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.regexp(r"(?i)^дать воды$"))
async def unmute_water(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "дать воды"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте пользователю!")
    try:
        await bot.restrict_chat_member(m.chat.id, target.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
        await try_delete(m)
        await m.answer(f"🥛 {target.mention_html()} получил воды. Мут снят.", parse_mode=ParseMode.HTML)
    except Exception as e: await m.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.regexp(r"(?i)^(варн|отругать)"))
async def issue_warn(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "варн"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте нарушителю!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (chat_id, user_id, warns) VALUES (?,?,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warns=warns+1", (m.chat.id, target.id))
        await db.commit()
        async with db.execute("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target.id)) as cur: warns = (await cur.fetchone())[0]
    await try_delete(m)
    if warns >= 3:
        try:
            await bot.ban_chat_member(m.chat.id, target.id)
            await m.answer(f"🐍 {target.mention_html()} получил 3/3 варнов и забанен!", parse_mode=ParseMode.HTML)
        except Exception as e: await m.answer(f"⚠️ Ошибка бана: {e}")
    else: await m.answer(f"👁 {target.mention_html()} получил предупреждение [{warns}/3].", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(банка с джемом|в банку)"))
async def ban_user(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "в банку"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте нарушителю!")
    try:
        await bot.ban_chat_member(m.chat.id, target.id)
        await try_delete(m)
        await m.answer(f"🫙 {target.mention_html()} запечатан в банку с джемом.", parse_mode=ParseMode.HTML)
    except Exception as e: await m.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.regexp(r"(?i)^вытащить из банки$"))
async def unban_user(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "вытащить из банки"): return await m.answer("🌫 Недостаточно прав!")
    target = await resolve_target(m)
    if not target: return await m.answer("🌫 Ответьте пользователю!")
    try:
        await bot.unban_chat_member(m.chat.id, target.id, only_if_banned=True)
        await try_delete(m)
        await m.answer(f"🌸 {target.mention_html()} вытащен из банки.", parse_mode=ParseMode.HTML)
    except Exception as e: await m.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.regexp(r"(?i)^(актив|стата|статистика)$"))
async def show_activity(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "актив"): return await m.answer("🌫 Недостаточно прав!")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, first_name, msg_count FROM users WHERE chat_id=? ORDER BY msg_count DESC LIMIT 20", (m.chat.id,)) as cur: rows = await cur.fetchall()
    if not rows: return await m.answer("🍧 Статистика пуста.")
    await try_delete(m)
    txt = "🍧 <b>ТОП-20 активных участников:</b>\n\n" + "\n".join([f"{i}. {fn or f'ID:{u}'} — <b>{c}</b> сообщ." for i, (u, fn, c) in enumerate(rows, 1)])
    await m.answer(txt, parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(калл|call|созыв)(?:\s+(.+))?$"))
async def call_all_users(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "калл"): return await m.answer("🌫 Недостаточно прав!")
    mat = re.match(r"^(калл|call|созыв)(?:\s+(.+))?$", m.text, re.I)
    call_txt = mat.group(2) or "Общий созыв участников Сада!"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE chat_id=?", (m.chat.id,)) as cur: rows = await cur.fetchall()
    if not rows: return await m.answer("🌫 База участников пуста!")
    await try_delete(m)
    mentions = " ".join([f'<a href="tg://user?id={u}">{random.choice(CALL_EMOJIS)}</a>' for u, in rows])
    await m.answer(f"🌸 <b>{call_txt}</b>\n\n{mentions}", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\+устав\s+(\d+)\s+(.+)$"))
async def add_rules_chapter(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "+устав"): return await m.answer("🌫 Недостаточно прав!")
    mat = re.match(r"^\+устав\s+(\d+)\s+(.+)$", m.text, re.I)
    cn, title = int(mat.group(1)), mat.group(2).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO rules_chapters VALUES (?,?,?) ON CONFLICT(chat_id, chapter_num) DO UPDATE SET title=?", (m.chat.id, cn, title, title))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 Раздел <b>{cn}. {title}</b> создан!", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\+устав\s+(\d+)\.(\d+)\s+(.+)$"))
async def add_rule_item(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "+устав"): return await m.answer("🌫 Недостаточно прав!")
    mat = re.match(r"^\+устав\s+(\d+)\.(\d+)\s+(.+)$", m.text, re.I)
    cn, rn, rtxt = int(mat.group(1)), int(mat.group(2)), mat.group(3).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM rules_chapters WHERE chat_id=? AND chapter_num=?", (m.chat.id, cn)) as cur:
            if not await cur.fetchone(): return await m.answer(f"🌫 Сначала создайте раздел {cn}!")
        if rn > 1:
            async with db.execute("SELECT 1 FROM rules_items WHERE chat_id=? AND chapter_num=? AND rule_num=?", (m.chat.id, cn, rn-1)) as cur:
                if not await cur.fetchone(): return await m.answer(f"🌫 Нет правила {cn}.{rn-1}!")
        await db.execute("INSERT INTO rules_items VALUES (?,?,?,?) ON CONFLICT(chat_id, chapter_num, rule_num) DO UPDATE SET text=?", (m.chat.id, cn, rn, rtxt, rtxt))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 Добавлено правило <b>{cn}.{rn}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^устав\s+(\d+)\+\s+(.+)$"))
async def append_rule_item(m: types.Message):
    if await get_user_role(m.chat.id, m.from_user.id) < await get_req_lvl(m.chat.id, "устав+"): return await m.answer("🌫 Недостаточно прав!")
    mat = re.match(r"^устав\s+(\d+)\+\s+(.+)$", m.text, re.I)
    cn, rtxt = int(mat.group(1)), mat.group(2).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(rule_num) FROM rules_items WHERE chat_id=? AND chapter_num=?", (m.chat.id, cn)) as cur:
            next_r = ((await cur.fetchone())[0] or 0) + 1
        await db.execute("INSERT INTO rules_items VALUES (?,?,?,?)", (m.chat.id, cn, next_r, rtxt))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 Правило добавлено под номером <b>{cn}.{next_r}</b>.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(устав сада|устав|правила|правила сада)(?:\s+(\d+)(?:\.(\d+))?)?$"))
async def show_rules(m: types.Message):
    mat = re.match(r"^(устав сада|устав|правила|правила сада)(?:\s+(\d+)(?:\.(\d+))?)?$", m.text, re.I)
    cf, rf = mat.group(2), mat.group(3)
    async with aiosqlite.connect(DB_PATH) as db:
        if cf and rf:
            async with db.execute("SELECT text FROM rules_items WHERE chat_id=? AND chapter_num=? AND rule_num=?", (m.chat.id, int(cf), int(rf))) as cur:
                r = await cur.fetchone()
                return await m.answer(f"🌸 <b>Правило {cf}.{rf}:</b> {r[0]}" if r else "🌫 Не найдено.")
        elif cf:
            async with db.execute("SELECT title FROM rules_chapters WHERE chat_id=? AND chapter_num=?", (m.chat.id, int(cf))) as cur:
                cr = await cur.fetchone()
                if not cr: return await m.answer("🌫 Раздел не найден.")
                txt = f"<b>{cf}. {cr[0]}</b>\n"
                async with db.execute("SELECT rule_num, text FROM rules_items WHERE chat_id=? AND chapter_num=? ORDER BY rule_num", (m.chat.id, int(cf))) as rcur:
                    async for rn, rt in rcur: txt += f"{cf}.{rn}. {rt}\n"
                return await m.answer(txt, parse_mode=ParseMode.HTML)
        else:
            txt = "🌸 <b>Устав Сада:</b>\n\n"
            async with db.execute("SELECT chapter_num, title FROM rules_chapters WHERE chat_id=? ORDER BY chapter_num", (m.chat.id,)) as ccur:
                chaps = await ccur.fetchall()
                if not chaps: return await m.answer("🌸 Устав пуст.")
                for cn, ct in chaps:
                    txt += f"<b>{cn}. {ct}</b>\n"
                    async with db.execute("SELECT rule_num, text FROM rules_items WHERE chat_id=? AND chapter_num=? ORDER BY rule_num", (m.chat.id, cn)) as rcur:
                        async for rn, rt in rcur: txt += f"{cn}.{rn}. {rt}\n"
                    txt += "\n"
            return await m.answer(txt, parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\+ник\s+(.+)$"))
async def set_nickname(m: types.Message):
    nn = re.match(r"^\+ник\s+(.+)$", m.text, re.I).group(1).strip()
    target, u_role = await resolve_target(m), await get_user_role(m.chat.id, m.from_user.id)
    tu = target if (target and target.id != m.from_user.id and u_role >= 1) else (message.from_user if not target or target.id == m.from_user.id else None)
    if not tu: return await m.answer("🌫 Меняют ники другим только модераторы!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (chat_id, user_id, rp_name) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name=?", (m.chat.id, tu.id, nn, nn))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 РП-ник для {tu.mention_html()}: <b>{nn}</b>", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\-ник$"))
async def reset_nickname(m: types.Message):
    target, u_role = await resolve_target(m), await get_user_role(m.chat.id, m.from_user.id)
    tu = target if (target and target.id != m.from_user.id and u_role >= 1) else (message.from_user if not target or target.id == m.from_user.id else None)
    if not tu: return await m.answer("🌫 Сбрасывают ники другим только модераторы!")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rp_name=NULL WHERE chat_id=? AND user_id=?", (m.chat.id, tu.id))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 РП-ник для {tu.mention_html()} сброшен.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\+команда\s+(\S+)\s+(.+)$"))
async def add_custom_cmd(m: types.Message):
    mat = re.match(r"^\+команда\s+(\S+)\s+(.+)$", m.text, re.I)
    cn, ct = mat.group(1).lower().strip(), mat.group(2).strip()
    if cn in SYSTEM_RESERVED_WORDS: return await m.answer("🌫 Запрещено перекрывать служебные команды!")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM custom_commands WHERE chat_id=? AND cmd_name=?", (m.chat.id, cn)) as cur:
            if await cur.fetchone(): return await m.answer("🌫 Команда существует!")
        await db.execute("INSERT INTO custom_commands VALUES (?,?,?)", (m.chat.id, cn, ct))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 РП-команда «<b>{cn}</b>» создана!", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^\-команда\s+(\S+)$"))
async def del_custom_cmd(m: types.Message):
    cn = re.match(r"^\-команда\s+(\S+)$", m.text, re.I).group(1).lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM custom_commands WHERE chat_id=? AND cmd_name=?", (m.chat.id, cn))
        await db.commit()
    await try_delete(m)
    await m.answer(f"🌸 РП-команда «<b>{cn}</b>» удалена.", parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(список команд|команды|рп команды)$"))
async def list_custom_cmds(m: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT cmd_name FROM custom_commands WHERE chat_id=?", (m.chat.id,)) as cur: rows = await cur.fetchall()
    if not rows: return await m.answer("🌈 Нет кастомных РП-команд.")
    await try_delete(m)
    await m.answer(f"🌈 <b>Кастомные РП-команды:</b>\n" + ", ".join([f"<code>{r[0]}</code>" for r in rows]), parse_mode=ParseMode.HTML)

@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def process_custom_rp(m: types.Message):
    if not m.from_user or m.from_user.is_bot or not (m.text or m.caption): return
    fw = (m.text or m.caption).strip().split()[0].lower()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT cmd_text FROM custom_commands WHERE chat_id=? AND cmd_name=?", (m.chat.id, fw)) as cur:
            row = await cur.fetchone()
            if row:
                c_name = await get_disp_name(m.chat.id, m.from_user)
                r_name = await get_disp_name(m.chat.id, m.reply_to_message.from_user) if (m.reply_to_message and m.reply_to_message.from_user) else "Никто"
                r_msg = (m.reply_to_message.text or m.reply_to_message.caption or "") if m.reply_to_message else ""
                rnd_name = "Случайный Гость"
                async with db.execute("SELECT user_id FROM users WHERE chat_id=? ORDER BY RANDOM() LIMIT 1", (m.chat.id,)) as rcur:
                    rrow = await rcur.fetchone()
                    if rrow:
                        try: rnd_name = await get_disp_name(m.chat.id, (await bot.get_chat_member(m.chat.id, rrow[0])).user)
                        except: pass
                res = row[0]
                for p, v in {r"\{user\}": c_name, r"\{username\}": c_name, r"\{reply\}": r_name, r"\{reply_message\}": r_msg, r"\{random\}": rnd_name}.items(): res = re.sub(p, v, res, flags=re.I)
                await try_delete(m)
                await m.answer(f"🌈 {res}", parse_mode=ParseMode.HTML)

@dp.message(Command("backup"))
async def cmd_backup(m: types.Message):
    if not STORAGE_GROUP_ID or str(m.chat.id) != str(STORAGE_GROUP_ID).strip(): return
    try:
        if (await bot.get_chat_member(m.chat.id, m.from_user.id)).status != ChatMemberStatus.CREATOR: return await m.answer("🌫 Только Создатель!")
    except: return
    msg = await m.answer("🔄 Выгружаю бэкап...")
    fn = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        data = {}
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for t in ["users", "roles_custom", "rules_chapters", "rules_items", "custom_commands", "cmd_levels"]:
                async with db.execute(f"SELECT * FROM {t}") as cur: data[t] = [dict(r) for r in await cur.fetchall()]
        with open(fn, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        await m.answer_document(FSInputFile(fn), caption=f"📦 <b>Бэкап сформирован!</b>\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", parse_mode=ParseMode.HTML)
        await msg.delete()
    except Exception as e: await m.answer(f"⚠️ Ошибка: <code>{e}</code>", parse_mode=ParseMode.HTML)
    finally:
        if os.path.exists(fn): os.remove(fn)

async def main():
    await init_db()
    dp.message.outer_middleware(ActivityMiddleware())
    logging.basicConfig(level=logging.INFO)
    print("🌸 Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())ц
