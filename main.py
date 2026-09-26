import asyncio, json, logging, math, os, re, random, sqlite3
from datetime import datetime, timedelta
from io import BytesIO
from collections import defaultdict
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatPermissions, Message, BufferedInputFile

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ⚠️ Укажи ID своей служебной группы (обязательно добавь туда бота админом)
STORAGE_CHAT_ID = -1001234567890  
DB_FILE = "bot_database.db"

# Переменная для контроля отложенного сохранения (Debounce)
sync_task = None

# Память для защиты от спама: {chat_id: {user_id: [msg_id1, msg_id2, ...], 'times': [time1, time2, ...]}}
spam_tracker = defaultdict(lambda: defaultdict(lambda: {"ids": [], "times": []}))

def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(sql, params)
        if commit: conn.commit()
        if fetchone: return c.fetchone()
        if fetchall: return c.fetchall()

def init_db():
    db_query("CREATE TABLE IF NOT EXISTS user_activity (chat_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT, message_count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id));", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS warn_system (chat_id INTEGER, user_id INTEGER, warn_count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id));", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS custom_commands (chat_id INTEGER, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name));", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS custom_nicknames (chat_id INTEGER, user_id INTEGER, nickname TEXT, PRIMARY KEY (chat_id, user_id));", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS mod_roles (chat_id INTEGER, user_id INTEGER, role_level INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id));", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS role_names (chat_id INTEGER PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ');", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS chat_rules (chat_id INTEGER PRIMARY KEY, rules_text TEXT);", commit=True)
    db_query("CREATE TABLE IF NOT EXISTS antispam_settings (chat_id INTEGER PRIMARY KEY, max_rate INTEGER DEFAULT 5);", commit=True)

init_db()

# ==================== СИНХРОНИЗАЦИЯ С TELEGRAM ====================

def schedule_sync():
    """Мгновенный вызов бэкапа с выводом лога для проверки."""
    logging.info("[DEBUG] Вызвана функция schedule_sync()!")
    asyncio.create_task(backup_to_telegram())

async def backup_to_telegram():
    """Сохраняет всю локальную БД в JSON-файл и отправляет в тех-чат."""
    logging.info(f"[DEBUG] Попытка бэкапа... STORAGE_CHAT_ID = {STORAGE_CHAT_ID}")
    if not STORAGE_CHAT_ID:
        logging.warning("[STORAGE] STORAGE_CHAT_ID не задан или равен 0!")
        return

    data = {
        "rules": db_query("SELECT chat_id, rules_text FROM chat_rules", fetchall=True),
        "custom_commands": db_query("SELECT chat_id, command_name, response_text FROM custom_commands", fetchall=True),
        "nicknames": db_query("SELECT chat_id, user_id, nickname FROM custom_nicknames", fetchall=True),
        "mod_roles": db_query("SELECT chat_id, user_id, role_level FROM mod_roles", fetchall=True),
        "role_names": db_query("SELECT chat_id, r1, r2, r3 FROM role_names", fetchall=True),
        "antispam": db_query("SELECT chat_id, max_rate FROM antispam_settings", fetchall=True)
    }

    json_data = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    file = BufferedInputFile(json_data, filename="backup.json")

    try:
        msg = await bot.send_document(
            chat_id=STORAGE_CHAT_ID,
            document=file,
            caption=f"📦 **Авто-бэкап базы данных**\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="Markdown"
        )
        try:
            await bot.pin_chat_message(STORAGE_CHAT_ID, msg.message_id, disable_notification=True)
        except Exception as e:
            logging.warning(f"[STORAGE] Не удалось закрепить сообщение: {e}")
            
        logging.info("[STORAGE] Бэкап успешно загружен в Telegram!")
    except Exception as e:
        logging.error(f"[STORAGE] Ошибка отправки бэкапа: {e}")

async def restore_from_telegram():
    """Выкачивает закрепленный backup.json из тех-чата и забивает локальный SQLite."""
    if not STORAGE_CHAT_ID:
        logging.warning("[RESTORE] STORAGE_CHAT_ID не указан. Пропуск восстановления.")
        return

    try:
        chat = await bot.get_chat(STORAGE_CHAT_ID)
        if not chat.pinned_message or not chat.pinned_message.document:
            logging.info("[RESTORE] В тех-чате нет закрепленного файла бэкапа.")
            return

        doc = chat.pinned_message.document
        if doc.file_name != "backup.json":
            logging.info("[RESTORE] Закрепленный документ — не backup.json.")
            return

        file_info = await bot.get_file(doc.file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        data = json.loads(file_bytes.read().decode('utf-8'))

        # Восстановление
        for r in data.get("rules", []):
            db_query("INSERT OR REPLACE INTO chat_rules VALUES (?,?)", tuple(r), commit=True)
        for c in data.get("custom_commands", []):
            db_query("INSERT OR REPLACE INTO custom_commands VALUES (?,?,?)", tuple(c), commit=True)
        for n in data.get("nicknames", []):
            db_query("INSERT OR REPLACE INTO custom_nicknames VALUES (?,?,?)", tuple(n), commit=True)
        for m in data.get("mod_roles", []):
            db_query("INSERT OR REPLACE INTO mod_roles VALUES (?,?,?)", tuple(m), commit=True)
        for rn in data.get("role_names", []):
            db_query("INSERT OR REPLACE INTO role_names VALUES (?,?,?,?)", tuple(rn), commit=True)
        for a in data.get("antispam", []):
            db_query("INSERT OR REPLACE INTO antispam_settings VALUES (?,?)", tuple(a), commit=True)

        logging.info(f"[RESTORE] БД успешно восстановлена из Telegram! Команд: {len(data.get('custom_commands', []))}")
    except Exception as e:
        logging.error(f"[RESTORE] Ошибка при восстановлении из Telegram: {e}")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

FORBIDDEN_PATTERNS = [r"правила.*", r"устав.*", r"актив.*", r"стата.*", r"статистика.*", r"варн.*", r"отругать.*", r"банка.*", r"сироп.*", r"воды.*", r"плод.*", r"ники.*", r"звания.*", r"команды.*", r"роль.*", r"повысить.*", r"понизить.*", r"антиспам.*"]

async def get_user_lvl(m: Message, uid: int) -> int:
    if m.chat.type == "private": return 0
    cm = await m.bot.get_chat_member(m.chat.id, uid)
    if cm.status == "creator": return 4
    res = db_query("SELECT role_level FROM mod_roles WHERE chat_id=? AND user_id=?", (m.chat.id, uid), fetchone=True)
    db_lvl = res[0] if res else 0
    return db_lvl if cm.status == "administrator" else (db_lvl if db_lvl > 0 else 0)

def get_name(chat_id: int, user_id: int, default: str) -> str:
    res = db_query("SELECT nickname FROM custom_nicknames WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    return res[0] if res else default

def parse_mod_args(text: str, target_str: str, prefixes: list):
    cleaned = text
    for p in prefixes:
        if cleaned.lower().startswith(p):
            cleaned = cleaned[len(p):].strip()
            break
    if target_str and target_str.startswith("@"):
        cleaned = re.sub(re.escape(target_str), "", cleaned, flags=re.IGNORECASE).strip()

    mins, time_disp, words = 60, "60 мин.", cleaned.split()
    if words:
        m = re.match(r"^(\d+)\s*(мин|мин.|минут|минуты|ч|час|часа|часов|д|ден|день|дня|дней)?$", words[0].lower())
        if m:
            n, u = int(m.group(1)), m.group(2) or "мин"
            if u.startswith("ч"): mins, time_disp = n * 60, f"{n} ч."
            elif u.startswith("д"): mins, time_disp = n * 1440, f"{n} дн."
            else: mins, time_disp = n, f"{n} мин."
            words = words[1:]

    reason = " ".join(words).strip()
    return mins, time_disp, (f"\n📝 **Причина:** {reason}" if reason else "")

async def resolve_target(m: Message):
    if m.reply_to_message:
        u = m.reply_to_message.from_user
        return u.id, u.first_name, None
    words = m.text.split()
    for w in words:
        if w.startswith("@"):
            uname = w.replace("@", "").lower().strip()
            res = db_query("SELECT user_id, first_name FROM user_activity WHERE chat_id=? AND LOWER(username)=?", (m.chat.id, uname), fetchone=True)
            if res: return res[0], res[1], w
            return None, w, w
    return None, None, None

# ==================== ХЭНДЛЕРЫ И КОМАНДЫ ====================

@dp.message(F.text.lower().startswith("+антиспам"))
async def set_antispam(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 4: 
        return await m.answer("⚠️ Настраивать анти-спам может только Создатель группы.")
    
    p = m.text.split()
    if len(p) < 2:
        return await m.answer("Использование: `+антиспам [число_сообщений_в_сек]`\nНапример: `+антиспам 5` (или `0` для выключения)", parse_mode="Markdown")
    
    val = p[1].lower().strip()
    if val in ["0", "выкл", "off", "откл"]:
        rate = 0
        msg_text = "🛡 **Анти-спам отключен.**"
    elif val.isdigit() and int(val) > 0:
        rate = int(val)
        msg_text = f"🛡 **Анти-спам обновлен!** Лимит: **{rate}** сообщ/сек."
    else:
        return await m.answer("⚠️ Укажите корректное число сообщений в секунду.")
    
    db_query("INSERT INTO antispam_settings VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET max_rate=excluded.max_rate", (m.chat.id, rate), commit=True)
    schedule_sync()
    await m.answer(msg_text, parse_mode="Markdown")

@dp.message(F.text.lower() == "антиспам")
async def get_antispam(m: Message):
    res = db_query("SELECT max_rate FROM antispam_settings WHERE chat_id=?", (m.chat.id,), fetchone=True)
    rate = res[0] if res else 5
    if rate == 0:
        await m.answer("🛡 Анти-спам в этой группе **отключен**.")
    else:
        await m.answer(f"🛡 Текущий лимит анти-спама: **{rate}** сообщ/сек.")

@dp.message(F.text.startswith("+роль"))
async def set_role_name(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 4: return await m.answer("⚠️ Менять названия ролей может только Создатель группы.")
    p = m.text.split(maxsplit=2)
    if len(p) < 3 or p[1] not in ["1", "2", "3"]: return await m.answer("Использование: `+роль [1/2/3] [Название]`", parse_mode="Markdown")
    r = list(db_query("SELECT r1, r2, r3 FROM role_names WHERE chat_id=?", (m.chat.id,), fetchone=True) or ("Хелпер", "Модер", "Админ"))
    r[int(p[1]) - 1] = p[2].strip()
    db_query("INSERT INTO role_names VALUES (?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET r1=excluded.r1, r2=excluded.r2, r3=excluded.r3", (m.chat.id, *r), commit=True)
    schedule_sync()
    await m.answer(f"✅ Должность уровня {p[1]} переименована в **{p[2].strip()}**!", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("повысить") | F.text.lower().startswith("+модер"))
async def promote(m: Message):
    my_lvl = await get_user_lvl(m, m.from_user.id)
    if my_lvl < 3: return await m.answer("⚠️ Повышать могут только Администраторы.")
    tid, tname, _ = await resolve_target(m)
    if not tid: return await m.answer("⚠️ Выберите пользователя ответом или укажите `@username`.")
    p = m.text.split()
    target_lvl = int(p[1]) if len(p) > 1 and p[1].isdigit() else 1
    if target_lvl >= my_lvl: return await m.answer(f"⚠️ Вы можете повышать только до уровня ниже вашего (максимум {my_lvl - 1}).")
    
    r = db_query("SELECT r1, r2, r3 FROM role_names WHERE chat_id=?", (m.chat.id,), fetchone=True) or ("Хелпер", "Модер", "Админ")
    db_query("INSERT INTO mod_roles VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET role_level=excluded.role_level", (m.chat.id, tid, target_lvl), commit=True)
    schedule_sync()
    if target_lvl >= 2:
        try: await m.chat.promote_member(tid, can_restrict_members=True, can_delete_messages=True, can_invite_users=True)
        except Exception as e: await m.answer(f"⚠️ Права в ТГ не выданы: {e}")
    await m.answer(f"👑 Пользователь **{tname}** назначен на должность **{r[target_lvl-1]}** (Уровень {target_lvl})!", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("понизить") | F.text.lower().startswith("-модер"))
async def demote(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 3: return await m.answer("⚠️ Понижать могут только Администраторы.")
    tid, tname, _ = await resolve_target(m)
    if not tid: return await m.answer("⚠️ Выберите пользователя ответом или укажите `@username`.")
    if await get_user_lvl(m, tid) >= await get_user_lvl(m, m.from_user.id): return await m.answer("⚠️ Вы не можете понизить этого участника.")
    db_query("DELETE FROM mod_roles WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync()
    try: await m.chat.promote_member(tid, can_restrict_members=False, can_delete_messages=False, can_invite_users=False)
    except: pass
    await m.answer(f"🔻 **{tname}** разжалован до обычного участника.")

@dp.message(F.text.startswith("+устав") | F.text.startswith("+правила"))
async def set_rules(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 3: return await m.answer("⚠️ Изменять устав сада могут только Админы.")
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+устав [текст правил]`", parse_mode="Markdown")
    db_query("INSERT INTO chat_rules VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET rules_text=excluded.rules_text", (m.chat.id, p[1]), commit=True)
    schedule_sync()
    await m.answer("📜 **Устав сада успешно обновлён!**", parse_mode="Markdown")

@dp.message(F.text.lower().in_(["устав сада", "устав", "правила", "правила сада"]))
async def get_rules(m: Message):
    res = db_query("SELECT rules_text FROM chat_rules WHERE chat_id=?", (m.chat.id,), fetchone=True)
    await m.answer(f"📜 **Устав сада:**\n\n{res[0]}" if res and res[0] else "📜 Устав сада еще не установлен.")

@dp.message(F.text.startswith("+ник"))
async def set_nick(m: Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+ник [ник]`", parse_mode="Markdown")
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m, m.from_user.id) < 1: return await m.answer("⚠️ Менять ники другим могут только модераторы.")
    db_query("INSERT INTO custom_nicknames VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET nickname=excluded.nickname", (m.chat.id, tid, p[1].strip()), commit=True)
    schedule_sync()
    await m.answer(f"🏷 РП-ник для **{tname}**: **{p[1].strip()}**", parse_mode="Markdown")

@dp.message(F.text == "-ник")
async def rem_nick(m: Message):
    tid, tname, _ = await resolve_target(m)
    if not tid: tid, tname = m.from_user.id, m.from_user.first_name
    if tid != m.from_user.id and await get_user_lvl(m, m.from_user.id) < 1: return await m.answer("⚠️ Сбрасывать ники другим могут только модераторы.")
    db_query("DELETE FROM custom_nicknames WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
    schedule_sync()
    await m.answer(f"🗑 РП-ник **{tname}** сброшен.")

@dp.message(F.text.lower().startswith("ники") | F.text.lower().startswith("звания"))
async def list_nicks(m: Message):
    p = m.text.split()
    page = max(1, int(p[1]) if len(p) > 1 and p[1].isdigit() else 1)
    total = (db_query("SELECT COUNT(*) FROM custom_nicknames WHERE chat_id=?", (m.chat.id,), fetchone=True) or [0])[0]
    if not total: return await m.answer("📝 Ни у кого нет кастомных ников.")
    pages = math.ceil(total / 10)
    page = min(page, pages)
    rows = db_query("SELECT n.user_id, n.nickname, a.first_name FROM custom_nicknames n LEFT JOIN user_activity a ON n.chat_id=a.chat_id AND n.user_id=a.user_id WHERE n.chat_id=? ORDER BY n.nickname LIMIT 10 OFFSET ?", (m.chat.id, (page-1)*10), fetchall=True)
    msg = f"🏷 **Ники чата ({page}/{pages}):**\n\n" + "\n".join([f"{i}. **{nk}** *({orig or 'ID:'+str(uid)})*" for i, (uid, nk, orig) in enumerate(rows, (page-1)*10 + 1)])
    await m.answer(msg, parse_mode="Markdown")

@dp.message(F.text.startswith("+комманда") | F.text.startswith("+команда"))
async def add_cmd(m: Message):
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: `+команда [имя] [текст]`", parse_mode="Markdown")
    c_name = p[1].lower().strip()
    if any(re.fullmatch(pat, c_name) for pat in FORBIDDEN_PATTERNS):
        return await m.answer("⚠️ Нельзя создавать РП-команды, совпадающие с системными.")
    if db_query("SELECT command_name FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, c_name), fetchone=True):
        return await m.answer(f"⚠️ Команда `{c_name}` уже существует! Сначала удалите её через `-команда {c_name}`.")
    db_query("INSERT INTO custom_commands VALUES (?,?,?)", (m.chat.id, c_name, p[2]), commit=True)
    schedule_sync()
    await m.answer(f"✅ РП-команда `{c_name}` сохранена!", parse_mode="Markdown")

@dp.message(F.text.startswith("-комманда") | F.text.startswith("-команда"))
async def del_cmd(m: Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `-команда [имя]`", parse_mode="Markdown")
    c_name = p[1].lower().strip()
    db_query("DELETE FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, c_name), commit=True)
    schedule_sync()
    await m.answer(f"🗑 Команда `{c_name}` удалена!")

@dp.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_cmds(m: Message):
    cmds = db_query("SELECT command_name FROM custom_commands WHERE chat_id=? ORDER BY command_name", (m.chat.id,), fetchall=True)
    if not cmds: return await m.answer("📝 В чате нет кастомных РП-команд.")
    await m.answer("📜 **РП-команды:**\n\n" + "\n".join([f"• `{c[0]}`" for c in cmds]), parse_mode="Markdown")

@dp.message(F.text)
async def process_msg(m: Message):
    if m.chat.type == "private": return
    
    # ------------------- ПРОВЕРКА АНТИ-СПАМА -------------------
    lvl = await get_user_lvl(m, m.from_user.id)
    # Игнорируем администраторов/модераторов (уровень >= 1)
    if lvl == 0:
        res = db_query("SELECT max_rate FROM antispam_settings WHERE chat_id=?", (m.chat.id,), fetchone=True)
        max_rate = res[0] if res else 5
        
        if max_rate > 0:
            now = datetime.now().timestamp()
            user_data = spam_tracker[m.chat.id][m.from_user.id]
            
            # Очищаем метки времени старше 1 секунды
            valid_pairs = [(t, mid) for t, mid in zip(user_data["times"], user_data["ids"]) if now - t <= 1.0]
            user_data["times"] = [t for t, _ in valid_pairs]
            user_data["ids"] = [mid for _, mid in valid_pairs]
            
            # Добавляем текущее сообщение
            user_data["times"].append(now)
            user_data["ids"].append(m.message_id)
            
            # Проверяем превышение лимита
            if len(user_data["times"]) > max_rate:
                # Наказание: мут на 1 минуту
                try:
                    await m.chat.restrict(
                        m.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=datetime.now() + timedelta(minutes=1)
                    )
                except Exception as e:
                    logging.error(f"[ANTISPAM] Ошибка мута: {e}")
                
                # Удаляем последние 5 сообщений (или сколько успел отправить)
                to_delete = user_data["ids"][-5:]
                for mid in to_delete:
                    try:
                        await bot.delete_message(m.chat.id, mid)
                    except Exception:
                        pass
                
                # Сбрасываем трекер для этого юзера
                spam_tracker[m.chat.id][m.from_user.id] = {"ids": [], "times": []}
                
                name = get_name(m.chat.id, m.from_user.id, m.from_user.first_name)
                return await m.answer(f"🚫 **{name}** отправил(а) слишком много сообщений, получил(а) мут на 1 мин и сообщения удалены!", parse_mode="Markdown")

    t = m.text.lower().strip()
    db_query("""
        INSERT INTO user_activity VALUES (?,?,?,?,1) 
        ON CONFLICT(chat_id, user_id) DO UPDATE SET 
        message_count=user_activity.message_count+1, username=excluded.username, first_name=excluded.first_name
    """, (m.chat.id, m.from_user.id, m.from_user.username, m.from_user.first_name), commit=True)

    # 1. ХЕЛПЕР
    if lvl >= 1:
        prefixes = ["клиновый сироп", "напоить сиропом", "дать плод всей боли", "дать воды"]
        if any(t.startswith(p) for p in prefixes):
            tid, tname, tstr = await resolve_target(m)
            if tid:
                if t.startswith("дать воды"):
                    try:
                        await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
                        return await m.answer(f"💧 **{tname}** размучен!")
                    except Exception as e: return await m.answer(f"Ошибка: {e}")
                
                if t.startswith("дать плод всей боли"):
                    mins, disp, r_str = 1440, "1 дн.", parse_mod_args(m.text, tstr, ["дать плод всей боли"])[2]
                else:
                    mins, disp, r_str = parse_mod_args(m.text, tstr, ["клиновый сироп", "напоить сиропом"])
                try:
                    await m.chat.restrict(tid, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(minutes=mins))
                    return await m.answer(f"🍁 **{tname}** в муте на {disp}.{r_str}", parse_mode="Markdown")
                except Exception as e: return await m.answer(f"Ошибка: {e}")

    # 2. МОДЕР
    if lvl >= 2:
        if t.startswith("варн") or t.startswith("отругать"):
            tid, tname, tstr = await resolve_target(m)
            if tid:
                _, _, r_str = parse_mod_args(m.text, tstr, ["варн", "отругать"])
                res = db_query("SELECT warn_count FROM warn_system WHERE chat_id=? AND user_id=?", (m.chat.id, tid), fetchone=True)
                warns = (res[0] if res else 0) + 1
                if warns >= 3:
                    db_query("DELETE FROM warn_system WHERE chat_id=? AND user_id=?", (m.chat.id, tid), commit=True)
                    try:
                        await m.chat.ban(tid)
                        return await m.answer(f"🫙 **{tname}** получил [3/3] варнов и забанен!{r_str}", parse_mode="Markdown")
                    except Exception as e: return await m.answer(f"Ошибка: {e}")
                else:
                    db_query("INSERT INTO warn_system VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count=excluded.warn_count", (m.chat.id, tid, warns), commit=True)
                    return await m.answer(f"⚠️ **{tname}** получил предупреждение! [{warns}/3]{r_str}", parse_mode="Markdown")
        elif t in ["актив", "стата", "статистика"]:
            top = db_query("SELECT first_name, message_count FROM user_activity WHERE chat_id=? ORDER BY message_count DESC LIMIT 20", (m.chat.id,), fetchall=True)
            if not top: return await m.answer("Статистика пуста.")
            return await m.answer("📊 **ТОП-20 участников:**\n\n" + "\n".join([f"{i}. {name} — {cnt} сообщ." for i, (name, cnt) in enumerate(top, 1)]), parse_mode="Markdown")

    # 3. АДМИН
    if lvl >= 3:
        if t.startswith("банка с джемом") or t.startswith("в банку"):
            tid, tname, tstr = await resolve_target(m)
            if tid:
                _, _, r_str = parse_mod_args(m.text, tstr, ["банка с джемом", "в банку"])
                try:
                    await m.chat.ban(tid)
                    return await m.answer(f"🫙 **{tname}** забанен (в банке с джемом)!{r_str}", parse_mode="Markdown")
                except Exception as e: return await m.answer(f"Ошибка: {e}")
        elif t.startswith("вытащить из банки"):
            tid, tname, _ = await resolve_target(m)
            if tid:
                try:
                    await m.chat.unban(tid)
                    return await m.answer(f"🔓 **{tname}** разбанен (вытащен из банки)!")
                except Exception as e: return await m.answer(f"Ошибка: {e}")

    # РП-КОМАНДЫ
    cmd = db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?", (m.chat.id, t), fetchone=True)
    if cmd:
        sender = get_name(m.chat.id, m.from_user.id, m.from_user.first_name if m.from_user else "Кто-то")
        tid, tname, _ = await resolve_target(m)
        reply_user = get_name(m.chat.id, tid, tname) if tid else "кого-то"
        reply_txt = (m.reply_to_message.text or m.reply_to_message.caption or "") if m.reply_to_message else ""
        
        users = db_query("SELECT user_id, first_name FROM user_activity WHERE chat_id=?", (m.chat.id,), fetchall=True)
        rand_user = get_name(m.chat.id, *random.choice(users)) if users else "Кто-то"

        text = cmd[0]
        replacements = {
            r"\{user\}": sender, r"\{username\}": sender,
            r"\{reply\}": reply_user, r"\{reply_message\}": reply_txt,
            r"\{random\}": rand_user
        }
        for pat, val in replacements.items():
            text = re.sub(pat, val, text, flags=re.IGNORECASE)

        await m.answer(text)

# ==================== ЗАПУСК ====================

async def main():
    logging.info("🚀 Восстановление данных из Telegram...")
    await restore_from_telegram()
    
    logging.info("🧪 Тестовая отправка бэкапа...")
    await backup_to_telegram()
    
    logging.info("✅ Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
