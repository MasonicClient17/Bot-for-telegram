import asyncio, json, logging, math, os, re, random, sqlite3, itertools
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types, html
from aiogram.enums import ParseMode
from aiogram.types import ChatPermissions, BufferedInputFile

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip("'\"")
STORAGE_CHAT_ID = int(os.getenv("STORAGE_CHAT_ID", 0) or 0)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_FILE = "bot_database.db"

CALL_EMOJIS = ["🌸", "☁️", "👁", "🐍", "🌫", "🥛", "🫗", "🍨", "🍧", "🌈", "🍇", "🫙"]

DEFAULT_CMD_LEVELS = {
    "кто я": 0, "профиль": 0, "кассеты": 0,
    "калл": 0, "call": 0, "созыв": 0,
    "устав": 0, "правила": 0,
    "список товаров": 0, "товары": 0, "магазин": 0, "купить": 0,
    "мои вещи": 0, "инвентарь": 0, "вещь": 0, "использовать": 0,
    "список браков": 0, "браки": 0,
    "клиновый сироп": 1, "напоить сиропом": 1, "дать воды": 1, "дать плод всей боли": 1, "+брак": 1, "-брак": 1,
    "актив": 2, "отругать": 2, "варн": 2, "-варн": 2, "снять варн": 2, "-варны": 2, "снять все варны": 2,
    "в банку": 3, "банка с джемом": 3, "вытащить из банки": 3,
    "+тессак": 3, "-тессак": 3, "тессак": 3,
    "+устав": 3, "+правила": 3, "+приветствие": 3, "-приветствие": 3,
    "повысить": 3, "понизить": 3,
    "роль": 4, "сменить": 4, "+вещь": 4
}

LEVEL_NAMES = {0: "Участник", 1: "Хелпер", 2: "Модератор", 3: "Администратор", 4: "Создатель"}

FORBIDDEN_PATTERNS = [
    r"правила.*", r"устав.*", r"актив.*", r"стата.*", r"варн.*", r"отругать.*",
    r"банка.*", r"сироп.*", r"воды.*", r"плод.*", r"ники.*", r"звания.*",
    r"команды.*", r"повысить.*", r"понизить.*", r"сменить.*", r"приветствие.*", r"профиль.*", r"кто я.*", r"тессак.*", r"кассеты.*"
]

def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
        c = conn.cursor()
        c.execute(sql, params)
        if commit: conn.commit()
        if fetchone: return c.fetchone()
        if fetchall: return c.fetchall()

def init_db():
    queries = [
        "CREATE TABLE IF NOT EXISTS users (chat_id INT, user_id INT, role_level INT DEFAULT 0, warns INT DEFAULT 0, msg_count INT DEFAULT 0, rp_name TEXT, day_count INT DEFAULT 0, week_count INT DEFAULT 0, last_msg_date TEXT, week_number TEXT, joined_at TEXT, tapes INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS custom_commands (chat_id INT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name));",
        "CREATE TABLE IF NOT EXISTS mod_roles (chat_id INT, user_id INT, role_level INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS role_names (chat_id INT PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ');",
        "CREATE TABLE IF NOT EXISTS cmd_levels (chat_id INT, cmd_name TEXT, min_lvl INT, PRIMARY KEY (chat_id, cmd_name));",
        "CREATE TABLE IF NOT EXISTS rules (chat_id INT, section INT, item INT, title TEXT, content TEXT, PRIMARY KEY (chat_id, section, item));",
        "CREATE TABLE IF NOT EXISTS chat_members (chat_id INT, user_id INT, first_name TEXT, username TEXT, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS welcome_messages (chat_id INT PRIMARY KEY, welcome_text TEXT);",
        "CREATE TABLE IF NOT EXISTS user_tags (chat_id INT, user_id INT, tag_name TEXT, PRIMARY KEY (chat_id, user_id));",
        "CREATE TABLE IF NOT EXISTS inventory (chat_id INT, user_id INT, item_name TEXT, count INT DEFAULT 1, PRIMARY KEY (chat_id, user_id, item_name));",
        "CREATE TABLE IF NOT EXISTS merchant_catalog (chat_id INT, item_name TEXT PRIMARY KEY, price INT, is_master_item INT DEFAULT 0);",
        "CREATE TABLE IF NOT EXISTS master_items (chat_id INT, item_name TEXT PRIMARY KEY, base_price INT);",
        "CREATE TABLE IF NOT EXISTS marriages (chat_id INT, user1_id INT, user2_id INT, date TEXT, PRIMARY KEY (chat_id, user1_id, user2_id));"
    ]
    for q in queries:
        db_query(q, commit=True)
    
    cols = [r[1] for r in db_query("PRAGMA table_info(users)", fetchall=True)]
    for col, col_type in [("day_count", "INT DEFAULT 0"), ("week_count", "INT DEFAULT 0"), ("last_msg_date", "TEXT"), ("week_number", "TEXT"), ("joined_at", "TEXT"), ("tapes", "INT DEFAULT 0")]:
        if col not in cols:
            db_query(f"ALTER TABLE users ADD COLUMN {col} {col_type};", commit=True)

    master_defaults = [("Освобождение от нормы", 1000), ("Бессрочное бракосочетание", 100)]
    for iname, iprice in master_defaults:
        db_query("INSERT OR IGNORE INTO master_items (chat_id, item_name, base_price) VALUES (0, ?, ?)", (iname, iprice), commit=True)

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
        "users": db_query("SELECT chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes FROM users", fetchall=True),
        "mod_roles": db_query("SELECT chat_id, user_id, role_level FROM mod_roles", fetchall=True),
        "cmd_levels": db_query("SELECT chat_id, cmd_name, min_lvl FROM cmd_levels", fetchall=True),
        "welcome": db_query("SELECT chat_id, welcome_text FROM welcome_messages", fetchall=True),
        "user_tags": db_query("SELECT chat_id, user_id, tag_name FROM user_tags", fetchall=True),
        "chat_members": db_query("SELECT chat_id, user_id, first_name, username FROM chat_members", fetchall=True),
        "inventory": db_query("SELECT chat_id, user_id, item_name, count FROM inventory", fetchall=True),
        "merchant_catalog": db_query("SELECT chat_id, item_name, price, is_master_item FROM merchant_catalog", fetchall=True),
        "master_items": db_query("SELECT chat_id, item_name, base_price FROM master_items", fetchall=True),
        "marriages": db_query("SELECT chat_id, user1_id, user2_id, date FROM marriages", fetchall=True)
    }
    file = BufferedInputFile(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'), filename="backup.json")
    try:
        msg = await bot.send_document(
            STORAGE_CHAT_ID,
            document=file,
            caption=f"📦 **Бэкап БД (Полный)** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
        for u in data.get("users", []):
            if len(u) == 4:
                db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name) VALUES (?,?,?,?)", tuple(u), commit=True)
            elif len(u) == 5:
                db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns) VALUES (?,?,?,?,?)", tuple(u), commit=True)
            elif len(u) == 11:
                db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(u[:11]), commit=True)
            elif len(u) >= 12:
                db_query("INSERT OR REPLACE INTO users (chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", tuple(u[:12]), commit=True)
        for cl in data.get("cmd_levels", []): db_query("INSERT OR REPLACE INTO cmd_levels VALUES (?,?,?)", tuple(cl), commit=True)
        for w in data.get("welcome", []): db_query("INSERT OR REPLACE INTO welcome_messages VALUES (?,?)", tuple(w), commit=True)
        for ut in data.get("user_tags", []): db_query("INSERT OR REPLACE INTO user_tags VALUES (?,?,?)", tuple(ut), commit=True)
        for cm in data.get("chat_members", []): db_query("INSERT OR REPLACE INTO chat_members VALUES (?,?,?,?)", tuple(cm), commit=True)
        for inv in data.get("inventory", []): db_query("INSERT OR REPLACE INTO inventory VALUES (?,?,?,?)", tuple(inv), commit=True)
        for mc in data.get("merchant_catalog", []): db_query("INSERT OR REPLACE INTO merchant_catalog VALUES (?,?,?,?)", tuple(mc), commit=True)
        for mi in data.get("master_items", []): db_query("INSERT OR REPLACE INTO master_items VALUES (?,?,?)", tuple(mi), commit=True)
        for mar in data.get("marriages", []): db_query("INSERT OR REPLACE INTO marriages VALUES (?,?,?,?)", tuple(mar), commit=True)
        logging.info("[RESTORE] Восстановлено успешно!")
    except Exception as e:
        logging.error(f"[RESTORE] Ошибка восстановления: {e}")

@dp.message(F.text.in_(["/safe", "/save"]))
async def manual_safe_handler(m: types.Message):
    if m.chat.id != STORAGE_CHAT_ID:
        return
    await backup_to_telegram()
    await m.answer("📦 **Вся информация бота успешно сохранена!**", parse_mode="Markdown")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

async def try_delete(m: types.Message):
    try:
        await m.delete()
    except Exception:
        pass

async def delete_after_delay(msg: types.Message, delay: int = 60):
    await asyncio.sleep(delay)
    await try_delete(msg)

async def get_user_lvl(cid: int, uid: int) -> int:
    if uid == 7350331661:
        return 4
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

def get_user_tag(cid: int, uid: int) -> str:
    res = db_query("SELECT tag_name FROM user_tags WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    return res[0] if res and res[0] else ""

def get_display_name(cid: int, uid: int, default_tg_name: str) -> str:
    rp_nick = db_query("SELECT rp_name FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    if rp_nick and rp_nick[0]:
        return rp_nick[0]
    
    rp_tag = get_user_tag(cid, uid)
    if rp_tag:
        return rp_tag
        
    return default_tg_name

def parse_mod_args(text: str, target_str: str, prefixes: list):
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
    return mins, (f"\n📝 **Причина:** {reason}" if reason else "")

async def resolve_target(m: types.Message):
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        fname = get_display_name(m.chat.id, u.id, u.first_name)
        return u.id, fname, None

    text = m.text or m.caption or ""
    if m.entities:
        for entity in m.entities:
            if entity.type == "text_mention" and entity.user:
                u = entity.user
                fname = get_display_name(m.chat.id, u.id, u.first_name)
                target_str = text[entity.offset:entity.offset + entity.length]
                return u.id, fname, target_str
            elif entity.type == "mention":
                raw_mention = text[entity.offset:entity.offset + entity.length]
                un = raw_mention.lstrip("@").lower().strip()
                res = db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
                if res:
                    fname = get_display_name(m.chat.id, res[0], res[1])
                    return res[0], fname, raw_mention
                return None, raw_mention, raw_mention

    for w in text.split():
        if w.startswith("@"):
            un = w.lstrip("@").lower().strip()
            res = db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, un), fetchone=True)
            if res:
                fname = get_display_name(m.chat.id, res[0], res[1])
                return res[0], fname, w
            return None, w, w

    return None, None, None

def get_user_stats(cid: int, uid: int):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    week_str = f"{iso_year}-{iso_week}"
    
    data = db_query("SELECT day_count, week_count, last_msg_date, week_number, joined_at, tapes, msg_count FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    if not data:
        return 0, 0, today_str, 0, 0
    
    day_c, week_c, last_date, last_week, joined, tapes, tot_c = data
    real_day = day_c if last_date == today_str else 0
    real_week = week_c if last_week == week_str else 0
    real_joined = joined or today_str
    
    return real_day, real_week, real_joined, (tapes or 0), (tot_c or 0)

async def track_user_and_daily(m: types.Message):
    cid, uid = m.chat.id, m.from_user.id
    fname, username = m.from_user.first_name, m.from_user.username
    if not uid or uid == bot.id:
        return
    un = username.lower() if username else ""
    db_query("INSERT INTO chat_members VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username", (cid, uid, fname, un), commit=True)
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    week_str = f"{iso_year}-{iso_week}"
    
    user_data = db_query("SELECT msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
    
    is_new_day = False
    if not user_data:
        db_query("INSERT INTO users (chat_id, user_id, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes) VALUES (?,?,1,1,1,?,?,?,0)", (cid, uid, today_str, week_str, today_str), commit=True)
        is_new_day = True
    else:
        tot_cnt, day_c, week_c, last_date, last_week, joined, tapes = user_data
        if last_date != today_str:
            is_new_day = True
        
        new_tot = (tot_cnt or 0) + 1
        new_day_c = 1 if last_date != today_str else (day_c or 0) + 1
        new_week_c = 1 if last_week != week_str else (week_c or 0) + 1
        new_joined = joined or today_str
        
        db_query("""
            UPDATE users SET 
                msg_count=?, 
                day_count=?, 
                week_count=?, 
                last_msg_date=?, 
                week_number=?, 
                joined_at=?
            WHERE chat_id=? AND user_id=?
        """, (new_tot, new_day_c, new_week_c, today_str, week_str, new_joined, cid, uid), commit=True)

    # ВЫДАЧА ЕЖЕДНЕВНЫХ КАССЕТ (30-50 кассет)
    if is_new_day:
        daily_reward = random.randint(30, 50)
        db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + ? WHERE chat_id=? AND user_id=?", (daily_reward, cid, uid), commit=True)
        uname = get_display_name(cid, uid, fname)
        daily_msg = await m.answer(f"📼 **{uname}**, держи ежедневную копеечку: **+{daily_reward}** кассет!", parse_mode="Markdown")
        asyncio.create_task(delete_after_delay(daily_msg, 60))

# ==================== ПРИВЕТСТВИЕ ====================

@dp.message(F.new_chat_members)
async def welcome_new_members(m: types.Message):
    res = db_query("SELECT welcome_text FROM welcome_messages WHERE chat_id=?", (m.chat.id,), fetchone=True)
    for user in m.new_chat_members:
        if user.is_bot: continue
        un = user.username.lower() if user.username else ""
        db_query("INSERT INTO chat_members VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username", (m.chat.id, user.id, user.first_name, un), commit=True)
        if not res or not res[0]: continue
        uname = get_display_name(m.chat.id, user.id, user.first_name)
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

# ==================== ПРОФИЛЬ И ВАЛЮТА ====================

@dp.message(F.text.lower().startswith(("кто я", "профиль")))
async def user_profile_handler(m: types.Message):
    if not await check_access(m, "кто я"): 
        return
    
    tid, tname, _ = await resolve_target(m)
    if not tid:
        tid = m.from_user.id
        tname = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    
    safe_tname = html.quote(tname)
    day_cnt, week_cnt, joined_date, tapes, _ = get_user_stats(m.chat.id, tid)
    same_count = (day_cnt == week_cnt)
    
    cm_data = db_query("SELECT username FROM chat_members WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True)
    if cm_data and cm_data[0]:
        un_prefix = f"(@{html.quote(cm_data[0])}) "
    else:
        un_prefix = ""
        
    full_user_str = f"{un_prefix}{safe_tname}"
    
    if week_cnt <= 10:
        msg = f"🌸 Похоже {full_user_str} немногословна~ всего <b>{week_cnt}</b> сообщений на этой неделе."
        if not same_count:
            msg += f" А сегодня <b>{day_cnt}</b>."
    elif 11 <= week_cnt <= 30:
        msg = f"🌸 У этой мультяшки {full_user_str} всего <b>{week_cnt}</b> сообщений за неделю~."
        if not same_count:
            msg += f" За сегодня <b>{day_cnt}</b>."
    elif 31 <= week_cnt <= 70:
        msg = f"🌸 Ох~ у этой мультяшки {full_user_str} <b>{week_cnt}</b> сообщений за эту неделю."
        if not same_count:
            msg += f" А за сегодня <b>{day_cnt}</b>~"
    elif 71 <= week_cnt <= 100:
        msg = f"🌸 Ого, у этой мультяшки {full_user_str} <b>{week_cnt}</b> сообщений за эту неделю!~\n{safe_tname}, вы молодец!"
        if not same_count:
            msg += f"\nА за сегодня <b>{day_cnt}</b> сообщений."
    else:
        msg = f"🌸 Вот это да~ <b>{week_cnt}</b> сообщений в неделю 👏🏻👏🏻\n{full_user_str}, вы молодец!✨"
        if not same_count:
            msg += f"\nСегодня <b>{day_cnt}</b> сообщений."
            
    msg += f"\n\n📼 Баланс кассет: <b>{tapes}</b>📼"
    msg += f"\n✨ присоединилась к саду: <b>{html.quote(str(joined_date))}</b>"
    
    await try_delete(m)
    await m.answer(msg, parse_mode="HTML")

# --- СТАТИСТИКА КАССЕТ С ПОСТРАНИЧНЫМ ВЫВОДОМ ---
@dp.message(F.text.lower().startswith(("стата", "статистика")))
async def tapes_stats_handler(m: types.Message):
    if not await check_access(m, "стата"): return
    
    raw_text = m.text.lower().strip()
    args = re.sub(r"^(стата|статистика)", "", raw_text).strip()
    page = max(1, int(args) if args.isdigit() else 1)
    
    all_users = db_query("SELECT u.user_id, u.tapes, cm.first_name FROM users u LEFT JOIN chat_members cm ON u.user_id=cm.user_id AND u.chat_id=cm.chat_id WHERE u.chat_id=?", (m.chat.id,), fetchall=True) or []
    
    tapes_list = []
    for uid, tapes, fn in all_users:
        disp_name = get_display_name(m.chat.id, uid, fn or f"ID:{uid}")
        tapes_list.append((disp_name, tapes or 0))
            
    tapes_list.sort(key=lambda x: x[1], reverse=True)
    
    tot = len(tapes_list)
    pages = math.ceil(tot / 10) or 1
    if page > pages and tot > 0:
        return await m.answer(f"🫗 Страницы {page} не существует. Всего страниц: {pages}")
        
    start_idx = (page - 1) * 10
    page_data = tapes_list[start_idx:start_idx + 10]
    
    txt = f"📼 **Статистика кассет у участников [Стр. {page}/{pages}]:**\n\n"
    if not page_data:
        txt += "🫙 В чате пока нет записанных балансов."
    else:
        txt += "\n".join([f"{i}. {name} — {tapes} 📼" for i, (name, tapes) in enumerate(page_data, start_idx + 1)])
        
    await try_delete(m)
    await m.answer(txt, parse_mode="Markdown")

# --- АКТИВНОСТЬ (СООБЩЕНИЯ) ---
@dp.message(F.text.lower().startswith("актив"))
async def msg_activity_handler(m: types.Message):
    if not await check_access(m, "актив"): return
    
    raw_text = m.text.lower().strip()
    is_daily = "день" in raw_text
    args = re.sub(r"^актив", "", raw_text).strip()
    args = re.sub(r"\bдень\b", "", args).strip()
    page = max(1, int(args) if args.isdigit() else 1)
    
    all_users = db_query("SELECT u.user_id, cm.first_name FROM users u LEFT JOIN chat_members cm ON u.user_id=cm.user_id AND u.chat_id=cm.chat_id WHERE u.chat_id=?", (m.chat.id,), fetchall=True) or []
    
    user_stats_list = []
    for uid, fn in all_users:
        day_cnt, week_cnt, _, _, _ = get_user_stats(m.chat.id, uid)
        cnt = day_cnt if is_daily else week_cnt
        if cnt > 0:
            disp_name = get_display_name(m.chat.id, uid, fn or f"ID:{uid}")
            user_stats_list.append((disp_name, cnt))
            
    user_stats_list.sort(key=lambda x: x[1], reverse=True)
    tot = len(user_stats_list)
    pages = math.ceil(tot / 10) or 1
    if page > pages and tot > 0:
        return await m.answer(f"🫗 Страницы {page} не существует. Всего: {pages}")
        
    start_idx = (page - 1) * 10
    page_data = user_stats_list[start_idx:start_idx + 10]
    
    title_mode = "дневной" if is_daily else "недельный"
    txt = f"📊 **Активность участников ({title_mode}) [Стр. {page}/{pages}]:**\n\n"
    if not page_data:
        txt += "🫙 В этом периоде пока нет активности."
    else:
        txt += "\n".join([f"{i}. {name} — {cnt} сообщ." for i, (name, cnt) in enumerate(page_data, start_idx + 1)])
        
    await try_delete(m)
    await m.answer(txt, parse_mode="Markdown")

# --- ПЕРЕДАЧА КАССЕТ ---
@dp.message(F.text.lower().startswith("кассеты"))
async def transfer_tapes_handler(m: types.Message):
    if not await check_access(m, "кассеты"): return
    text = m.text.strip()
    match = re.match(r"^кассеты\s+(\d+)(.*)$", text, re.I)
    if not match:
        return await m.answer("🫗 Использование: `кассеты [число] [юзернейм/ответ]`", parse_mode="Markdown")
    
    amount = int(match.group(1))
    if amount <= 0:
        return await m.answer("🫗 Число кассет должно быть больше 0!")

    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🫗 Укажите пользователя или ответьте на его сообщение!")

    if tid == m.from_user.id:
        return await m.answer("🫗 Нельзя передавать кассеты самому себе!")

    sender_id = m.from_user.id
    sender_tapes = (db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, sender_id), fetchone=True) or [0])[0] or 0

    if sender_tapes < amount:
        return await m.answer("📼Недостаточно кассет!")

    sender_name = get_display_name(m.chat.id, sender_id, m.from_user.first_name)
    receiver_name = get_display_name(m.chat.id, tid, tname)

    db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (amount, m.chat.id, sender_id), commit=True)
    db_query("INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=COALESCE(tapes,0)+excluded.tapes", (m.chat.id, tid, amount), commit=True)

    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 {sender_name} отправил(а) {amount}📼 {receiver_name}")

# --- АДМИН-КОМАНДЫ ТЕССАК ---
@dp.message(F.text.lower().startswith(("+тессак", "-тессак", "тессак")))
async def admin_tapes_handler(m: types.Message):
    if not await check_access(m, "+тессак"): return
    text = m.text.strip()

    if text.lower().startswith("+тессак"):
        mode = "add"
        rest = text[7:].strip()
    elif text.lower().startswith("-тессак"):
        mode = "sub"
        rest = text[7:].strip()
    else:
        mode = "set"
        rest = text[6:].strip()

    match = re.match(r"^(\d+)(.*)$", rest)
    if not match:
        return await m.answer("🫗 Формат: `тессак [число] [пользователь]`", parse_mode="Markdown")

    amount = int(match.group(1))
    tid, tname, _ = await resolve_target(m)

    sender_name = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)

    if not tid or tid == m.from_user.id:
        target_id = m.from_user.id
        is_self = True
        target_name = sender_name
    else:
        target_id = tid
        is_self = False
        target_name = get_display_name(m.chat.id, target_id, tname)

    current_tapes = (db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, target_id), fetchone=True) or [0])[0] or 0

    if mode == "add":
        new_val = current_tapes + amount
    elif mode == "sub":
        new_val = max(0, current_tapes - amount)
    else:
        new_val = amount

    db_query(
        "INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=excluded.tapes", 
        (m.chat.id, target_id, new_val), 
        commit=True
    )
    schedule_sync(); await try_delete(m)

    if is_self:
        await m.answer(f"🌸 {sender_name} материализовал(а) {new_val}📼 из ниоткуда")
    else:
        await m.answer(f"🌸 {sender_name} материализовал(а) {new_val}📼 из ниоткуда и отдал(а) их {target_name}.")

# ==================== МАГАЗИН И ПРЕДМЕТЫ DANDY ====================

@dp.message(F.text.startswith("+вещи"))
async def give_item_admin(m: types.Message):
    if not await check_access(m, "+вещь"):
        return

    text = m.text[6:].strip()
    tid, tname, tstr = await resolve_target(m)

    if not tid:
        return await m.answer("🫗 Укажите пользователя (ответом или через @/ID)!", parse_mode="Markdown")

    clean_item = text
    if tstr and (tstr.startswith("@") or tstr.isdigit()):
        clean_item = re.sub(re.escape(tstr), "", clean_item, flags=re.I).strip()

    count = 1
    words = clean_item.split()
    if words and words[-1].isdigit():
        count = int(words[-1])
        item_name = " ".join(words[:-1]).strip()
    else:
        item_name = clean_item.strip()

    if not item_name:
        return await m.answer("🫗 Укажите название вещи! Пример: `+вещи [название] [кол-во] [юзер]`", parse_mode="Markdown")

    db_query(
        "INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+excluded.count",
        (m.chat.id, tid, item_name, count),
        commit=True
    )

    admin_name = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    target_name = get_display_name(m.chat.id, tid, tname)

    schedule_sync()
    await try_delete(m)
    await m.answer(f"🌸 **{admin_name}** выгрузил(а) из инвентаря **{item_name}** ({count} шт.) и передал(а) **{target_name}**.")

@dp.message(F.text.lower().startswith(("+вещь", "создать предмет")))
async def master_add_item_handler(m: types.Message):
    if not await check_access(m, "+вещь"): return
    match = re.match(r"^\+вещь\s+(.+?)\s+(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer("🫗 Формат: `+вещь [название] [цена]`", parse_mode="Markdown")
    
    item_name, price = match.group(1).strip(), int(match.group(2))
    db_query("INSERT OR REPLACE INTO master_items (chat_id, item_name, base_price) VALUES (?,?,?)", (m.chat.id, item_name, price), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Создана вещь 4 уровня: **{item_name}** (Базовая цена: {price} 📼)")

@dp.message(F.text.lower().startswith("создать вещь"))
async def merchant_create_item_handler(m: types.Message):
    user_tag = get_user_tag(m.chat.id, m.from_user.id)
    if user_tag.lower() != "dandy":
        return await m.answer("🌫️ Создавать товары для магазина может только Торговец (Dandy)!")

    match = re.match(r"^создать вещь\s+(.+?)\s+(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer("🫗 Формат: `создать вещь [название] [цена]`", parse_mode="Markdown")

    item_name, price = match.group(1).strip(), int(match.group(2))
    
    master_item = db_query("SELECT base_price FROM master_items WHERE (chat_id=? OR chat_id=0) AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), fetchone=True)
    is_master = 0
    if master_item:
        is_master = 1
        base_price = master_item[0]
        min_p = int(base_price * 0.8)
        max_p = int(base_price * 1.2)
        if not (min_p <= price <= max_p):
            return await m.answer(f"🌫️ Торговец может продавать вещь 4 уровня '{item_name}' только в пределах ±20% от базовой цены ({base_price} 📼)!\nДопустимая цена: от {min_p} до {max_p} 📼.")

    db_query("INSERT OR REPLACE INTO merchant_catalog (chat_id, item_name, price, is_master_item) VALUES (?,?,?,?)", (m.chat.id, item_name, price, is_master), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🛍 Торговец Dandy выставил на продажу: **{item_name}** за **{price}** 📼")

@dp.message(F.text.lower().startswith("удалить вещь"))
async def merchant_delete_item_handler(m: types.Message):
    user_tag = get_user_tag(m.chat.id, m.from_user.id)
    if user_tag.lower() != "dandy":
        return await m.answer("🌫️ Удалять товары может только Торговец (Dandy)!")
    
    item_name = m.text[12:].strip()
    db_query("DELETE FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🛍 Товар **{item_name}** убран из магазина.")

@dp.message(F.text.lower().in_(["список товаров", "товары", "магазин"]))
async def show_merchant_shop_handler(m: types.Message):
    if not await check_access(m, "список товаров"): return
    items = db_query("SELECT item_name, price FROM merchant_catalog WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not items:
        return await m.answer("🫙 У Торговца Dandy пока нет товаров на продажу.")
    
    txt = "🛍 **Лавка торговца Dandy:**\n\n"
    for name, price in items:
        txt += f"• **{name}** — {price} 📼\n"
    txt += "\nДля покупки используйте команду: `купить [название]`"
    await try_delete(m)
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text.lower().startswith("купить"))
async def buy_item_handler(m: types.Message):
    if not await check_access(m, "купить"): return
    item_name = m.text[6:].strip()
    if not item_name:
        return await m.answer("🫗 Использование: `купить [название вещи]`", parse_mode="Markdown")

    item = db_query("SELECT item_name, price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), fetchone=True)
    if not item:
        return await m.answer("🫙 Такого товара нет у торговца!")

    real_item_name, price = item
    user_tapes = (db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True) or [0])[0] or 0

    if user_tapes < price:
        return await m.answer(f"📼 Недостаточно кассет! Требуется: **{price}** 📼, у вас: **{user_tapes}** 📼.")

    dandy_res = db_query("SELECT user_id FROM user_tags WHERE chat_id=? AND LOWER(tag_name)='dandy'", (m.chat.id,), fetchone=True)
    
    db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (price, m.chat.id, m.from_user.id), commit=True)
    if dandy_res:
        db_query("INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=COALESCE(tapes,0)+excluded.tapes", (m.chat.id, dandy_res[0], price), commit=True)

    db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+1", (m.chat.id, m.from_user.id, real_item_name), commit=True)
    
    buyer_nick = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    schedule_sync(); await try_delete(m)
    await m.answer(f"✨ **{buyer_nick}** приобретает **{real_item_name}** у Dandy за **{price}** 📼!")

@dp.message(F.text.lower().in_(["мои вещи", "инвентарь"]))
async def show_inventory_handler(m: types.Message):
    if not await check_access(m, "мои вещи"): return
    items = db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND count > 0", (m.chat.id, m.from_user.id), fetchall=True)
    uname = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    if not items:
        return await m.answer(f"🫙 В карманах у **{uname}** пока пусто.")
    
    txt = f"🎒 **Инвентарь {uname}:**\n\n"
    for iname, icnt in items:
        txt += f"• **{iname}** — {icnt} шт.\n"
    await try_delete(m)
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text.lower().startswith("вещь"))
async def transfer_item_handler(m: types.Message):
    if not await check_access(m, "вещь"): return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("🌸 Ответьте на сообщение пользователя, которому хотите передать вещь!")

    item_name = m.text[4:].strip()
    if not item_name:
        return await m.answer("🫗 Укажите название вещи! Пример: `вещь [название]`", parse_mode="Markdown")

    inv_item = db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?) AND count > 0", (m.chat.id, m.from_user.id, item_name), fetchone=True)
    if not inv_item:
        return await m.answer("🫙 У вас нет этой вещи!")

    real_iname = inv_item[0]
    tid = m.reply_to_message.from_user.id
    if tid == m.from_user.id:
        return await m.answer("🫗 Нельзя передавать вещи самому себе!")

    db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND item_name=?", (m.chat.id, m.from_user.id, real_iname), commit=True)
    db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+1", (m.chat.id, tid, real_iname), commit=True)

    sender_name = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    receiver_name = get_display_name(m.chat.id, tid, m.reply_to_message.from_user.first_name)

    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 **{sender_name}** передал(а) вещь **{real_iname}** пользователю **{receiver_name}**.")

@dp.message(F.text.lower().startswith("использовать"))
async def use_item_handler(m: types.Message):
    if not await check_access(m, "использовать"): return
    item_name = m.text[12:].strip()
    inv_item = db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?) AND count > 0", (m.chat.id, m.from_user.id, item_name), fetchone=True)
    if not inv_item:
        return await m.answer("🫙 У вас нет такой вещи в инвентаре!")

    real_iname = inv_item[0]
    uname = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)

    if real_iname.lower() == "освобождение от нормы":
        db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND item_name=?", (m.chat.id, m.from_user.id, real_iname), commit=True)
        creator_id = 7350331661
        try:
            await bot.send_message(creator_id, f"📜 **Уведомление об Освобождении от нормы:**\nПользователь **{uname}** (ID: {m.from_user.id}) применил вещь 'Освобождение от нормы' в чате {m.chat.title or m.chat.id}!")
            await m.answer(f"✨ **{uname}** использовал(а) **Освобождение от нормы**! Создатель группы получил уведомление в ЛС.")
        except Exception as e:
            await m.answer(f"✨ **{uname}** использовал(а) **Освобождение от нормы**! (Не удалось отправить ЛС Создателю: {e})")
        schedule_sync(); await try_delete(m)
        return

    await m.answer(f"🫗 Предмет **{real_iname}** пока не имеет встроенной активации.")

# ==================== БРАКИ ====================

@dp.message(F.text.startswith("+брак"))
async def create_marriage_handler(m: types.Message):
    u_lvl = await get_user_lvl(m.chat.id, m.from_user.id)
    inv_item = db_query("SELECT count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)='бессрочное бракосочетание' AND count > 0", (m.chat.id, m.from_user.id), fetchone=True)
    
    if u_lvl < 1 and not inv_item:
        return await m.answer("🌫 У вас нет прав для создания браков или предмета 'Бессрочное бракосочетание'!")

    u1_id, u2_id = None, None

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
                    raw_mention = m.text[entity.offset:entity.offset + entity.length].lstrip("@").lower().strip()
                    res = db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, raw_mention), fetchone=True)
                    if res: mentions.append(res[0])
        if len(mentions) >= 2:
            u1_id, u2_id = mentions[0], mentions[1]

    if not u1_id or not u2_id:
        return await m.answer("🫗 Использование: `+брак @user1 @user2` или `+брак` ответом на сообщение!", parse_mode="Markdown")

    if u1_id == u2_id:
        return await m.answer("🫗 Нельзя заключить брак с самим собой!")

    existing = db_query("SELECT * FROM marriages WHERE chat_id=? AND ((user1_id=? OR user2_id=?) OR (user1_id=? OR user2_id=?))", (m.chat.id, u1_id, u1_id, u2_id, u2_id), fetchone=True)
    if existing:
        return await m.answer("🌸 Один из участников уже состоит в браке!")

    if u_lvl < 1 and inv_item:
        db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND LOWER(item_name)='бессрочное бракосочетание'", (m.chat.id, m.from_user.id), commit=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    db_query("INSERT INTO marriages VALUES (?,?,?,?)", (m.chat.id, u1_id, u2_id, today_str), commit=True)
    
    n1 = get_display_name(m.chat.id, u1_id, f"ID:{u1_id}")
    n2 = get_display_name(m.chat.id, u2_id, f"ID:{u2_id}")

    schedule_sync(); await try_delete(m)
    await m.answer(f"💍 **Совет да любовь!** Объявлен новый союз между **{n1}** и **{n2}**! 💕")

@dp.message(F.text.startswith("-брак"))
async def remove_marriage_handler(m: types.Message):
    if not await check_access(m, "+брак"): return
    u1_id, u2_id = None, None

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
                    raw_mention = m.text[entity.offset:entity.offset + entity.length].lstrip("@").lower().strip()
                    res = db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, raw_mention), fetchone=True)
                    if res: mentions.append(res[0])
        if len(mentions) >= 2:
            u1_id, u2_id = mentions[0], mentions[1]

    if not u1_id or not u2_id:
        return await m.answer("🫗 Использование: `-брак @user1 @user2` или `-брак` ответом!", parse_mode="Markdown")

    db_query("DELETE FROM marriages WHERE chat_id=? AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))", (m.chat.id, u1_id, u2_id, u2_id, u1_id), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer("💔 Брак был успешно расторгнут.")

@dp.message(F.text.lower().in_(["список браков", "браки"]))
async def list_marriages_handler(m: types.Message):
    if not await check_access(m, "список браков"): return
    marriages = db_query("SELECT user1_id, user2_id, date FROM marriages WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not marriages:
        return await m.answer("🫙 В этом чате пока нет зарегистрированных браков.")

    txt = "💍 **Список любовных союзов чата:**\n\n"
    for idx, (u1, u2, mdate) in enumerate(marriages, 1):
        n1 = get_display_name(m.chat.id, u1, f"ID:{u1}")
        n2 = get_display_name(m.chat.id, u2, f"ID:{u2}")
        txt += f"{idx}. 💕 **{n1}** + **{n2}** *(с {mdate})*\n"

    await try_delete(m)
    await m.answer(txt, parse_mode="Markdown")

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
    hdr = f"🌈 Общий сбор!\n{reason}\n\n" if reason else "🌈 Общий сбор!\n\n"
    mentions, emo_cycle = [], itertools.cycle(CALL_EMOJIS)
    for (uid,) in members:
        mentions.append(f'<a href="tg://user?id={uid}">{next(emo_cycle)}</a>')
    await try_delete(m)
    for i in range(0, len(mentions), 50):
        chunk = mentions[i:i+50]
        await m.answer((hdr if i == 0 else "") + " ".join(chunk), parse_mode="HTML")

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
        await m.answer(f"🫗 {tname} отправлен молчать на {mins} мин.{r_str}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

@dp.message(F.text.lower().startswith("дать плод всей боли"))
async def mute_24h_handler(m: types.Message):
    if not await check_access(m, "дать плод всей боли"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")
    reason = parse_mod_args(m.text, tstr, ["дать плод всей боли"])[1]
    try:
        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=int(datetime.now().timestamp()) + 86400)
        await try_delete(m); await m.answer(f"🍇 {tname} вкусил(а) плод всей боли...{reason}")
    except Exception as e: await m.answer(f"👁 Ошибка: {e}")

# --- ВАРНЫ ---

@dp.message(F.text.lower().startswith(("варн", "отругать")))
async def give_warn_handler(m: types.Message):
    if not await check_access(m, "варн"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")

    reason = parse_mod_args(m.text, tstr, ["варн", "отругать"])[1]

    db_query("INSERT INTO users (chat_id, user_id, warns) VALUES (?,?,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warns=warns+1", (m.chat.id, tid), commit=True)
    warns = (db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True) or [0])[0]
    
    schedule_sync(); await try_delete(m)

    if warns >= 3:
        db_query("UPDATE users SET warns=0 WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
        try:
            await m.chat.ban(tid)
            await m.answer(f"🫙 {tname} получил(а) 3/3 предупреждений и запечатан(а) в банку с джемом!{reason}")
        except Exception as e:
            await m.answer(f"👁 Пользователь набрал 3/3 варнов, но не удалось забанить: {e}")
    else:
        await m.answer(f"🌫 {tname} получил(а) предупреждение [{warns}/3].{reason}")

@dp.message(F.text.lower().startswith(("-варн", "снять варн")))
async def remove_warn_handler(m: types.Message):
    if not await check_access(m, "-варн"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")

    warns = (db_query("SELECT warns FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True) or [0])[0]
    if warns <= 0:
        return await m.answer(f"🌸 У {tname} нет предупреждений.")

    new_warns = warns - 1
    db_query("UPDATE users SET warns=? WHERE chat_id=? AND user_id=?", (new_warns, m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 У {tname} снято предупреждение. Теперь: [{new_warns}/3].")

@dp.message(F.text.lower().startswith(("-варны", "снять все варны")))
async def clear_warns_handler(m: types.Message):
    if not await check_access(m, "-варны"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        return await m.answer("🌸 Ответьте на сообщение пользователя!")

    db_query("UPDATE users SET warns=0 WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Все предупреждения с {tname} сняты! [0/3].")

# --- БАН / РАЗБАН ---

@dp.message(F.text.lower().startswith(("в банку", "банка с джемом")))
async def ban_handler(m: types.Message):
    if not await check_access(m, "в банку"): return
    tid, tname, tstr = await resolve_target(m)
    if not tid:
        return await m.answer("🫗 Ответьте на сообщение пользователя!")
    reason = parse_mod_args(m.text, tstr, ["в банку", "банка с джемом"])[1]
    try:
        await m.chat.ban(tid); await try_delete(m)
        await m.answer(f"🫙 {tname} запечатан(а) в банку с джемом.{reason}")
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

# --- УСТАВ ---
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
        if not items: return await m.answer(f"👁 Раздел {arg} не найден!")
        stitle = items[0][1] if items[0][0] == 0 else f"Раздел {arg}"
        txt = f"📜 **Раздел {arg}. {stitle}**\n\n" + "\n\n".join([f"**{arg}.{i} {t}**\n{c}" for i, t, c in items if i != 0])
        return await m.answer(txt, parse_mode="Markdown")
    all_rules = db_query("SELECT section, item, title, content FROM rules WHERE chat_id=? ORDER BY section ASC, item ASC", (m.chat.id,), fetchall=True)
    if not all_rules: return await m.answer("👁 Устав ещё пуст!")
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
    await m.answer(f"🏷 РП-ник для {tname}: **{p[1].strip()}**", parse_mode="Markdown")

@dp.message(F.text == "-ник")
async def rem_nick(m: types.Message):
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m.chat.id, m.from_user.id) < 1:
        return await m.answer("🌫 Сбрасывать ники другим могут только модераторы.")
    db_query("UPDATE users SET rp_name=NULL WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🏷 ник {tname} сброшен.")

# --- ТЭГИ ---

@dp.message(F.text.startswith("+тэг"))
async def set_tag_handler(m: types.Message):
    if not await check_access(m, "+ник"): return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2: 
        return await m.answer("Использование: `+тэг [название]` (ответом или с упоминанием)", parse_mode="Markdown")
    
    tid, tname, tstr = await resolve_target(m)
    if not tid:
        tid = m.from_user.id
        tname = m.from_user.first_name
        
    tag_val = parts[1].strip()
    if tstr and (tstr.startswith("@") or tstr.isdigit()):
        tag_val = re.sub(re.escape(tstr), "", tag_val, flags=re.I).strip()
        
    if not tag_val:
        return await m.answer("🫗 Укажите название тэга!")

    db_query("INSERT INTO user_tags (chat_id, user_id, tag_name) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tag_name=excluded.tag_name", (m.chat.id, tid, tag_val), commit=True)
    schedule_sync(); await try_delete(m)
    disp_name = get_display_name(m.chat.id, tid, tname)
    await m.answer(f"🏷 Пользователю {disp_name} присвоен тэг: **{tag_val}**", parse_mode="Markdown")

@dp.message(F.text.startswith("-тэг"))
async def rem_tag_handler(m: types.Message):
    if not await check_access(m, "+ник"): return
    tid, tname, _ = await resolve_target(m)
    if not tid:
        tid = m.from_user.id
        tname = m.from_user.first_name
        
    db_query("DELETE FROM user_tags WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync(); await try_delete(m)
    disp_name = get_display_name(m.chat.id, tid, tname)
    await m.answer(f"🏷 Тэг у {disp_name} был удалён.")

# --- РП КОМАНДЫ ---

@dp.message(F.text.startswith(("+команда", "+комманда")))
async def add_cmd(m: types.Message):
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: `+команда [имя] [текст]`", parse_mode="Markdown")
    cn = p[1].lower().strip()
    if any(re.fullmatch(pat, cn) for pat in FORBIDDEN_PATTERNS):
        return await m.answer("👁️ Совпадает с системной командой.")
    if db_query("SELECT command_name FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, cn), fetchone=True):
        return await m.answer(f"👁 Команда `{cn}` уже существует!")
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
    try:
        await track_user_and_daily(m)
    except Exception as e:
        logging.error(f"[TRACK_ERROR] {e}")

    t = m.text.lower().strip()

    cmd = db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, t), fetchone=True)
    if cmd:
        await try_delete(m)
        sender = get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
        tid, tname, _ = await resolve_target(m)
        reply_user = get_display_name(m.chat.id, tid, tname) if tid else "кого-то"
        reply_txt = (m.reply_to_message.text or m.reply_to_message.caption or "") if m.reply_to_message else ""
        users = db_query("SELECT user_id, first_name FROM chat_members WHERE chat_id=?", (m.chat.id,), fetchall=True)
        rand_user = get_display_name(m.chat.id, *random.choice(users)) if users else "Кто-то"

        s_day, s_week, _, _, _ = get_user_stats(m.chat.id, m.from_user.id)
        r_day, r_week, _, _, _ = get_user_stats(m.chat.id, tid) if tid else (0, 0, "", 0, 0)

        res = cmd[0]
        replacements = {
            r"\{user\}": sender, 
            r"\{u\}": sender,
            r"\{username\}": sender, 
            r"\{reply\}": reply_user, 
            r"\{r\}": reply_user,
            r"\{reply_message\}": reply_txt, 
            r"\{reply_text\}": reply_txt,
            r"\{rt\}": reply_txt,
            r"\{random\}": rand_user,
            r"\{rn\}": rand_user,
            r"\{day\}": str(s_day),
            r"\{week\}": str(s_week),
            r"\{reply_day\}": str(r_day),
            r"\{reply_week\}": str(r_week)
        }
        for pat, val in replacements.items():
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
