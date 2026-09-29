import asyncio, json, logging, math, os, re, random, sqlite3, itertools
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.types import ChatPermissions, BufferedInputFile

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip("'\"")
STORAGE_CHAT_ID = int(os.getenv("STORAGE_CHAT_ID", 0) or 0)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_FILE = "bot_database.db"

# Набор эмодзи для маскировки ссылок в команде созыва
CALL_EMOJIS = ["🌸", "☁️", "👁", "🐍", "🌫", "🥛", "🫗", "🍨", "🍧", "🌈", "🍇", "🫙"]

# Дефолтные уровни доступа к командам
DEFAULT_CMD_LEVELS = {
    "калл": 0, "call": 0, "созыв": 0,
    "устав": 0, "правила": 0,
    "клиновый сироп": 1, "напоить сиропом": 1, "дать воды": 1, "дать плод всей боли": 1,
    "актив": 2, "стата": 2, "статистика": 2, "отругать": 2, "варн": 2,
    "в банку": 3, "банка с джемом": 3, "вытащить из банки": 3,
    "+устав": 3, "+правила": 3, "+приветствие": 3, "-приветствие": 3,
    "повысить": 3, "понизить": 3,
    "роль": 4, "сменить": 4
}

LEVEL_NAMES = {0: "Участник", 1: "Хелпер", 2: "Модератор", 3: "Администратор", 4: "Создатель"}

FORBIDDEN_PATTERNS = [
    r"правила.*", r"устав.*", r"актив.*", r"стата.*", r"варн.*", r"отругать.*",
    r"банка.*", r"сироп.*", r"воды.*", r"плод.*", r"ники.*", r"звания.*",
    r"команды.*", r"повысить.*", r"понизить.*", r"сменить.*", r"приветствие.*"
]

def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(sql, params)
        if commit: conn.commit()
        if fetchone: return c.fetchone()
        if fetchall: return c.fetchall()

def init_db():
    queries = [
        "CREATE TABLE IF NOT EXISTS users (chat_id INT, user_id INT, role_level INT DEFAULT 0, warns INT DEFAULT 0, msg_count INT DEFAULT 0, rp_name TEXT, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS custom_commands (chat_id INT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name));",
        "CREATE TABLE IF NOT EXISTS mod_roles (chat_id INT, user_id INT, role_level INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS role_names (chat_id INT PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ');",
        "CREATE TABLE IF NOT EXISTS cmd_levels (chat_id INT, cmd_name TEXT, min_lvl INT, PRIMARY KEY (chat_id, cmd_name));",
        "CREATE TABLE IF NOT EXISTS rules (chat_id INT, section INT, item INT, title TEXT, content TEXT, PRIMARY KEY (chat_id, section, item));",
        "CREATE TABLE IF NOT EXISTS chat_members (chat_id INT, user_id INT, first_name TEXT, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS welcome_messages (chat_id INT PRIMARY KEY, welcome_text TEXT);"
    ]
    for q in queries:
        db_query(q, commit=True)

init_db()

# ==================== СИНХРОНИЗАЦИЯ И БЭКАПЫ ====================

def schedule_sync():
    asyncio.create_task(backup_to_telegram())

async def backup_to_telegram():
    if not STORAGE_CHAT_ID:
        return logging.warning("[STORAGE] STORAGE_CHAT_ID не задан!")
    data = {
        "rules": db_query("SELECT chat_id, section, item, title, content FROM rules", fetchall=True),
        "custom_commands": db_query("SELECT chat_id, command_name, response_text FROM custom_commands", fetchall=True),
        "users": db_query("SELECT chat_id, user_id, role_level, rp_name FROM users", fetchall=True),
        "mod_roles": db_query("SELECT chat_id, user_id, role_level FROM mod_roles", fetchall=True),
        "cmd_levels": db_query("SELECT chat_id, cmd_name, min_lvl FROM cmd_levels", fetchall=True),
        "welcome": db_query("SELECT chat_id, welcome_text FROM welcome_messages", fetchall=True)
    }
    file = BufferedInputFile(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'), filename="backup.json")
    try:
        msg = await bot.send_document(
            STORAGE_CHAT_ID,
            document=file,
            caption=f"📦 **Бэкап БД** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await bot.pin_chat_message(STORAGE_CHAT_ID, msg.message_id, disable_notification=True)
        except Exception as e:
            logging.warning(f"[STORAGE] Не удалось закрепить: {e}")
        logging.info("[STORAGE] Бэкап отправлен!")
    except Exception as e:
        logging.error(f"[STORAGE] Ошибка бэкапа: {e}")

async def restore_from_telegram():
    if not STORAGE_CHAT_ID:
        return logging.warning("[RESTORE] STORAGE_CHAT_ID не указан.")
    try:
        chat = await bot.get_chat(STORAGE_CHAT_ID)
        if not chat.pinned_message or not chat.pinned_message.document or chat.pinned_message.document.file_name != "backup.json":
            return
        finfo = await bot.get_file(chat.pinned_message.document.file_id)
        data = json.loads((await bot.download_file(finfo.file_path)).read().decode('utf-8'))
        for r in data.get("rules", []): db_query("INSERT OR REPLACE INTO rules VALUES (?,?,?,?,?)", tuple(r), commit=True)
        for c in data.get("custom_commands", []): db_query("INSERT OR REPLACE INTO custom_commands VALUES (?,?,?)", tuple(c), commit=True)
        for u in data.get("users", []): db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name) VALUES (?,?,?,?)", tuple(u), commit=True)
        for cl in data.get("cmd_levels", []): db_query("INSERT OR REPLACE INTO cmd_levels VALUES (?,?,?)", tuple(cl), commit=True)
        for w in data.get("welcome", []): db_query("INSERT OR REPLACE INTO welcome_messages VALUES (?,?)", tuple(w), commit=True)
        logging.info("[RESTORE] Восстановлено успешно!")
    except Exception as e:
        logging.error(f"[RESTORE] Ошибка восстановления: {e}")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

async def try_delete(m: types.Message):
    try:
        await m.delete()
    except Exception:
        pass

async def get_user_lvl(cid: int, uid: int) -> int:
    try:
        if (await bot.get_chat_member(cid, uid)).status == "creator":
            return 4
    except Exception:
        pass
    res = db_query("SELECT role_level FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    return res[0] if res and res[0] is not None else 0

def get_req_lvl(cid: int, cmd: str) -> int:
    c = cmd.strip().lower()
    res = db_query("SELECT min_lvl FROM cmd_levels WHERE chat_id=? AND cmd_name=?", (cid, c), fetchone=True)
    return res[0] if res and res[0] is not None else DEFAULT_CMD_LEVELS.get(c, 0)

async def check_access(m: types.Message, cmd: str) -> bool:
    req = get_req_lvl(m.chat.id, cmd)
    u_lvl = await get_user_lvl(m.chat.id, m.from_user.id)
    if u_lvl < req:
        await m.answer(f"🌫 Ваше влияние недостаточно велико! Требуется: {req} ({LEVEL_NAMES.get(req, '')}).")
        return False
    return True

def get_name(cid: int, uid: int, default: str) -> str:
    res = db_query("SELECT rp_name FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    return res[0] if res and res[0] else default

def parse_mod_args(text: str, target_str: str, prefixes: list):
    cleaned = text
    for p in prefixes:
        if cleaned.lower().startswith(p):
            cleaned = cleaned[len(p):].strip()
            break
    if target_str and target_str.startswith("@"):
        cleaned = re.sub(re.escape(target_str), "", cleaned, flags=re.I).strip()
    
    mins, words = 60, cleaned.split()
    if words:
        m = re.match(r"^(\d+)\s*(мин|мин.|минут|минуты|ч|час|часа|часов|д|ден|день|дня|дней)?$", words[0].lower())
        if m:
            n, u = int(m.group(1)), m.group(2) or "мин"
            mins = n * 60 if u.startswith("ч") else (n * 1440 if u.startswith("д") else n)
            words = words[1:]
    reason = ".".join(words).strip()
    return mins, (f"\n📝 **Причина:** {reason}" if reason else "")

async def resolve_target(m: types.Message):
    if m.reply_to_message:
        return m.reply_to_message.from_user.id, m.reply_to_message.from_user.first_name, None
    for w in m.text.split():
        if w.startswith("@"):
            un = w.replace("@", "").lower().strip()
            res = db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=? AND LOWER(first_name)=?", (m.chat.id, un), fetchone=True)
            return (res[0], res[1], w) if res else (None, w, w)
    return None, None, None

def track_user(cid: int, uid: int, fname: str):
    if uid and uid != bot.id:
        db_query("INSERT INTO chat_members VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name=excluded.first_name", (cid, uid, fname), commit=True)
        db_query("INSERT INTO users (chat_id, user_id, msg_count) VALUES (?,?,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET msg_count=msg_count+1", (cid, uid), commit=True)

# ==================== ПРИВЕТСТВИЕ ====================

@dp.message(F.new_chat_members)
async def welcome_new_members(m: types.Message):
    res = db_query("SELECT welcome_text FROM welcome_messages WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not res or not res[0]:
        return
    for user in m.new_chat_members:
        if user.is_bot: continue
        track_user(m.chat.id, user.id, user.first_name)
        uname = get_name(m.chat.id, user.id, user.first_name)
        txt = res[0]
        for pat, val in {r"\{user\}": uname, r"\{chat\}": m.chat.title or "Сад"}.items():
            txt = re.sub(pat, val, txt, flags=re.I)
        await m.answer(f"🌸 {txt}")

@dp.message(F.text.startswith("+приветствие"))
async def set_welcome(m: types.Message):
    if not await check_access(m, "+приветствие"): return
    text = m.text[13:].strip()
    if not text:
        return await m.answer("🫗 Укажите текст приветствия!\nПример: `+приветствие Добро пожаловать в {chat}, {user}!`\n\nПеременные: `{user}`, `{chat}`", parse_mode="Markdown")
    db_query("INSERT INTO welcome_messages VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET welcome_text=excluded.welcome_text", (m.chat.id, text), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("🌸 Приветствие для новых участников успешно установлено!")

@dp.message(F.text.startswith("-приветствие"))
async def remove_welcome(m: types.Message):
    if not await check_access(m, "-приветствие"): return
    db_query("DELETE FROM welcome_messages WHERE chat_id=?", (m.chat.id,), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("🗑 Приветствие отключено.")

@dp.message(F.text.lower() == "приветствие")
async def show_welcome(m: types.Message):
    res = db_query("SELECT welcome_text FROM welcome_messages WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not res or not res[0]:
        return await m.answer("🫙 Приветствие в этом чате не установлено.")
    await m.answer(f"🌸 **Текущее приветствие:**\n\n{res[0]}", parse_mode="Markdown")

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@dp.message(F.text.lower().startswith("сменить"))
async def change_cmd_level_handler(m: types.Message):
    if not await check_access(m, "сменить"): return
    mat = re.search(r"^сменить\s*\((.+?)\)\s*(\d+)$", m.text.strip(), re.I)
    if not mat:
        return await m.answer("🫗 Формат: `сменить (команда) уровень`", parse_mode="Markdown")
    cmd, lvl = mat.group(1).strip().lower(), int(mat.group(2))
    if not (0 <= lvl <= 4):
        return await m.answer("🫗 Уровень должен быть от 0 до 4!")
    db_query("INSERT INTO cmd_levels VALUES (?,?,?) ON CONFLICT(chat_id, cmd_name) DO UPDATE SET min_lvl=excluded.min_lvl", (m.chat.id, cmd, lvl), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Уровень допуска для ({cmd}) изменён на {lvl} ({LEVEL_NAMES[lvl]}).")

@dp.message(F.text.lower().startswith(("калл", "call", "созыв")))
async def call_all_handler(m: types.Message):
    if not await check_access(m, "калл"): return
    members = db_query("SELECT user_id FROM chat_members WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not members:
        return await m.answer("🫙 В базе пока нет записанных участников!")
    reason = re.sub(r"^(калл|call|созыв)", "", m.text, flags=re.I).strip()
    hdr = f"🌈 Общий сбор!\nПричина: {reason}\n\n" if reason else "🌈 Общий сбор!\n\n"
    mentions, emo_cycle = [], itertools.cycle(CALL_EMOJIS)
    for (uid,) in members:
        mentions.append(f'<a href="tg://user?id={uid}">{next(emo_cycle)}</a>')
    await try_delete(m)
    for i in range(0, len(mentions), 50):
        chunk = mentions[i:i+50]
        await m.answer((hdr if i == 0 else "") + " ".join(chunk), parse_mode="HTML")

@dp.message(F.text.lower().startswith(("актив", "стата", "статистика")))
async def stats_handler(m: types.Message):
    if not await check_access(m, "стата"): return
    args = re.sub(r"^(актив|стата|статистика)", "", m.text, flags=re.I).strip()
    page = max(1, int(args) if args.isdigit() else 1)
    tot = (db_query("SELECT COUNT(*) FROM users WHERE chat_id=?", (m.chat.id,), fetchone=True) or [0])[0]
    pages = math.ceil(tot / 10) or 1
    if page > pages:
        return await m.answer(f"🫗 Страницы {page} не существует. Всего: {pages}")
    rows = db_query("SELECT u.user_id, u.msg_count, cm.first_name FROM users u LEFT JOIN chat_members cm ON u.user_id=cm.user_id AND u.chat_id=cm.chat_id WHERE u.chat_id=? ORDER BY u.msg_count DESC LIMIT 10 OFFSET ?", (m.chat.id, (page-1)*10), fetchall=True)
    txt = f"📊 **Активность участников (Стр. {page}/{pages}):**\n\n" + "\n".join([f"{i}. {fn or 'ID:'+str(u)} — {cnt} сообщ." for i, (u, cnt, fn) in enumerate(rows, (page-1)*10+1)])
    await try_delete(m); await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text.lower().startswith(("напоить сиропом", "клиновый сироп", "дать воды")))
async def mute_handler(m: types.Message):
    if not await check_access(m, "напоить сиропом"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")
    await try_delete(m)
    if m.text.lower().startswith("дать воды"):
        try:
            await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
            return await m.answer(f"🥛 {tname} получил(а) воды!")
        except Exception as e: return await m.answer(f"👁 Ошибка: {e}")
    mins, r_str = parse_mod_args(m.text, tstr, ["напоить сиропом", "клиновый сироп"])
    try:
        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=int(datetime.now().timestamp()) + mins*60)
        await m.answer(f"🫗 **{tname}** отправлен молчать на {mins} мин.{r_str}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@dp.message(F.text.lower().startswith("дать плод всей боли"))
async def mute_24h_handler(m: types.Message):
    if not await check_access(m, "дать плод всей боли"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")
    reason = m.text[19:].strip() or "Не указана"
    try:
        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=int(datetime.now().timestamp()) + 86400)
        await try_delete(m); await m.answer(f"🍇 {tname} вкусил(а) плод всей боли...\nПричина: {reason}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@dp.message(F.text.lower().startswith(("в банку", "банка с джемом")))
async def ban_handler(m: types.Message):
    if not await check_access(m, "в банку"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🫗 Ответьте на сообщение пользователя!")
    reason = re.sub(r"^(в банку|банка с джемом)", "", m.text, flags=re.I).strip() or "Не указана"
    try:
        await m.chat.ban(tid); await try_delete(m)
        await m.answer(f"🫙 {tname} запечатан(а) в банку с джемом.\nПричина: {reason}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@dp.message(F.text.lower().startswith("вытащить из банки"))
async def unban_handler(m: types.Message):
    if not await check_access(m, "в банку"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")
    try:
        await m.chat.unban(tid, only_if_banned=True); await try_delete(m)
        await m.answer(f"🌸 {tname} достали из банки!")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@dp.message(F.text.startswith(("+устав", "+правила")))
async def edit_rules_handler(m: types.Message):
    if not await check_access(m, "+устав"): return
    cnt = re.sub(r"^(\+устав|\+правила)", "", m.text, flags=re.I).strip()
    m_app = re.match(r"^(\d+)\+\s+(.+?)\s+(.+)$", cnt, re.S)
    if m_app:
        sec, title, text = int(m_app.group(1)), m_app.group(2).strip(), m_app.group(3).strip()
        max_item = (db_query("SELECT MAX(item) FROM rules WHERE chat_id=? AND section=?", (m.chat.id, sec), fetchone=True) or [0])[0]
        nxt = (max_item or 0) + 1
        db_query("INSERT INTO rules VALUES (?,?,?,?,?)", (m.chat.id, sec, nxt, title, text), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Добавлен пункт {sec}.{nxt} [{title}] в конец раздела {sec}!")
    m_itm = re.match(r"^(\d+)\.(\d+)\s+(.+?)\s+(.+)$", cnt, re.S)
    if m_itm:
        sec, itm, title, text = int(m_itm.group(1)), int(m_itm.group(2)), m_itm.group(3).strip(), m_itm.group(4).strip()
        db_query("INSERT INTO rules VALUES (?,?,?,?,?) ON CONFLICT(chat_id, section, item) DO UPDATE SET title=excluded.title, content=excluded.content", (m.chat.id, sec, itm, title, text), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Пункт {sec}.{itm} [{title}] успешно сохранен!")
    m_sec = re.match(r"^(\d+)\s+(.+)$", cnt)
    if m_sec:
        sec, title = int(m_sec.group(1)), m_sec.group(2).strip()
        db_query("INSERT INTO rules VALUES (?,?,0,?,'') ON CONFLICT(chat_id, section, item) DO UPDATE SET title=excluded.title", (m.chat.id, sec, title), commit=True)
        schedule_sync(); await try_delete(m)
        return await m.answer(f"🌸 Раздел {sec} [{title}] создан!")
    await m.answer("🫗 Неверный формат!")

@dp.message(F.text.lower().startswith(("устав", "правила")))
async def view_rules_handler(m: types.Message):
    if not await check_access(m, "устав"): return
    arg = re.sub(r"^(устав|правила)", "", m.text, flags=re.I).strip()
    m_itm = re.match(r"^(\d+)\.(\d+)$", arg)
    if m_itm:
        sec, itm = int(m_itm.group(1)), int(m_itm.group(2))
        res = db_query("SELECT title, content FROM rules WHERE chat_id=? AND section=? AND item=?", (m.chat.id, sec, itm), fetchone=True)
        return await m.answer(f"📜 **Правило {sec}.{itm}: {res[0]}**\n\n{res[1]}" if res else f"🫙 Правило {sec}.{itm} не найдено!", parse_mode="Markdown")
    if arg.isdigit():
        items = db_query("SELECT item, title, content FROM rules WHERE chat_id=? AND section=? ORDER BY item ASC", (m.chat.id, int(arg)), fetchall=True)
        if not items: return await m.answer(f"👁️ Раздел {arg} не найден!")
        stitle = items[0][1] if items[0][0] == 0 else f"Раздел {arg}"
        txt = f"📜 **Раздел {arg}. {stitle}**\n\n" + "\n\n".join([f"**{arg}.{i} {t}**\n{c}" for i, t, c in items if i != 0])
        return await m.answer(txt, parse_mode="Markdown")
    all_rules = db_query("SELECT section, item, title, content FROM rules WHERE chat_id=? ORDER BY section ASC, item ASC", (m.chat.id,), fetchall=True)
    if not all_rules: return await m.answer("👁️ Устав ещё пуст!")
    txt, cur_sec = "📜 **Устав / Правила чата:**\n\n", None
    for sec, itm, title, content in all_rules:
        if sec != cur_sec:
            cur_sec = sec
            txt += f"\n🔻 **Раздел {sec}. {title}**\n" if itm == 0 else f"\n🔻 **Раздел {sec}**\n"
        if itm != 0: txt += f"▪️ **{sec}.{itm} {title}**: {content}\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text.startswith("+ник"))
async def set_nick(m: types.Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+ник [ник]`", parse_mode="Markdown")
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m.chat.id, m.from_user.id) < 1:
        return await m.answer("🌫 Менять ники другим могут только модераторы.")
    db_query("INSERT INTO users (chat_id, user_id, rp_name) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET rp_name=excluded.rp_name", (m.chat.id, tid, p[1].strip()), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🏷 РП-ник для **{tname}**: **{p[1].strip()}**", parse_mode="Markdown")

@dp.message(F.text == "-ник")
async def rem_nick(m: types.Message):
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m.chat.id, m.from_user.id) < 1:
        return await m.answer("🌫 Сбрасывать ники другим могут только модераторы.")
    db_query("UPDATE users SET rp_name=NULL WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🏷 ник {tname} сброшен.")

@dp.message(F.text.startswith(("+команда", "+комманда")))
async def add_cmd(m: types.Message):
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: `+команда [имя] [текст]`", parse_mode="Markdown")
    cn = p[1].lower().strip()
    if any(re.fullmatch(pat, cn) for pat in FORBIDDEN_PATTERNS):
        return await m.answer("👁️ Совпадает с системной командой.")
    if db_query("SELECT command_name FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, cn), fetchone=True):
        return await m.answer(f"👁️ Команда `{cn}` уже существует!")
    db_query("INSERT INTO custom_commands VALUES (?,?,?)", (m.chat.id, cn, p[2]), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 `{cn}` сохранена!", parse_mode="Markdown")

@dp.message(F.text.startswith(("-команда", "-комманда")))
async def del_cmd(m: types.Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `-команда [имя]`", parse_mode="Markdown")
    cn = p[1].lower().strip()
    db_query("DELETE FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, cn), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 `{cn}` удалена!")

@dp.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_cmds(m: types.Message):
    cmds = db_query("SELECT command_name FROM custom_commands WHERE chat_id=? ORDER BY command_name", (m.chat.id,), fetchall=True)
    if not cmds: return await m.answer("📝 В чате нет РП-команд.")
    await try_delete(m)
    await m.answer("🌈 **РП-команды:**\n\n" + "\n".join([f"• `{c[0]}`" for c in cmds]), parse_mode="Markdown")

@dp.message(F.text)
async def process_msg(m: types.Message):
    if m.chat.type == "private" or not m.from_user: return
    track_user(m.chat.id, m.from_user.id, m.from_user.first_name)
    t = m.text.lower().strip()

    cmd = db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, t), fetchone=True)
    if cmd:
        await try_delete(m)
        sender = get_name(m.chat.id, m.from_user.id, m.from_user.first_name)
        tid, tname, _ = await resolve_target(m)
        reply_user = get_name(m.chat.id, tid, tname) if tid else "кого-то"
        reply_txt = (m.reply_to_message.text or m.reply_to_message.caption or "") if m.reply_to_message else ""
        users = db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=?", (m.chat.id,), fetchall=True)
        rand_user = get_name(m.chat.id, *random.choice(users)) if users else "Кто-то"

        res = cmd[0]
        for pat, val in {r"\{user\}": sender, r"\{username\}": sender, r"\{reply\}": reply_user, r"\{reply_message\}": reply_txt, r"\{random\}": rand_user}.items():
            res = re.sub(pat, val, res, flags=re.I)
        await m.answer(res)

async def main():
    logging.info("🚀 Восстановление из Telegram...")
    await restore_from_telegram()
    logging.info("🧪 Отправка автобэкапа...")
    await backup_to_telegram()
    logging.info("🌸 Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
