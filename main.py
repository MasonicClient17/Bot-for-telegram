import asyncio, logging, math, os, re, random, psycopg2
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatPermissions, Message

logging.basicConfig(level=logging.INFO)
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Wacestall081215550570@db.vgdtikonjidhrdykchcy.supabase.co:5432/postgres")

def get_db(): return psycopg2.connect(DB_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (chat_id BIGINT, user_id BIGINT, username TEXT, first_name TEXT, message_count INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS warn_system (chat_id BIGINT, user_id BIGINT, warn_count INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS custom_commands (chat_id BIGINT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name));
                CREATE TABLE IF NOT EXISTS custom_nicknames (chat_id BIGINT, user_id BIGINT, nickname TEXT, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS mod_roles (chat_id BIGINT, user_id BIGINT, role_level INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS role_names (chat_id BIGINT PRIMARY KEY, r1 TEXT DEFAULT 'Хелпер', r2 TEXT DEFAULT 'Модер', r3 TEXT DEFAULT 'Админ');
                CREATE TABLE IF NOT EXISTS chat_rules (chat_id BIGINT PRIMARY KEY, rules_text TEXT);
            """)
            conn.commit()

init_db()

# Защищенные слова
FORBIDDEN_PATTERNS = [r"правила.*", r"устав.*", r"актив.*", r"стата.*", r"статистика.*", r"варн.*", r"отругать.*", r"банка.*", r"сироп.*", r"воды.*", r"ники.*", r"звания.*", r"команды.*", r"роль.*", r"повысить.*", r"понизить.*"]

async def get_user_lvl(m: Message, uid: int) -> int:
    if m.chat.type in ["private"]: return 0
    cm = await m.bot.get_chat_member(m.chat.id, uid)
    if cm.status == "creator": return 4
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT role_level FROM mod_roles WHERE chat_id=%s AND user_id=%s", (m.chat.id, uid))
            res = c.fetchone()
    db_lvl = res[0] if res else 0
    return db_lvl if cm.status == "administrator" else (db_lvl if db_lvl > 0 else 0)

def get_role_names(chat_id: int):
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT r1, r2, r3 FROM role_names WHERE chat_id=%s", (chat_id,))
            res = c.fetchone()
    return res if res else ("Хелпер", "Модер", "Админ")

def get_name(chat_id: int, user_id: int, default: str) -> str:
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT nickname FROM custom_nicknames WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            res = c.fetchone()
    return res[0] if res else default

def parse_time(t: str):
    m = re.match(r"^(\d+)\s*(мин|мин.|минут|минуты|ч|час|часа|часов|д|ден|день|дня|дней)?$", (t or "").lower().strip())
    if not m: return 60, "60 мин."
    n, u = int(m.group(1)), m.group(2)
    if u in ["ч", "час", "часа", "часов"]: return n * 60, f"{n} ч."
    if u in ["д", "ден", "день", "дня", "дней"]: return n * 1440, f"{n} дн."
    return n, f"{n} мин."

# Смена названий ролей (Только для Овнера/Создателя)
@dp.message(F.text.startswith("+роль"))
async def set_role_name(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 4: return await m.answer("⚠️ Менять названия ролей может только Создатель группы.")
    p = m.text.split(maxsplit=2)
    if len(p) < 3 or p[1] not in ["1", "2", "3"]: return await m.answer("Использование: `+роль [1/2/3] [Название]`", parse_mode="Markdown")
    lvl, name = int(p[1]), p[2].strip()
    r1, r2, r3 = get_role_names(m.chat.id)
    if lvl == 1: r1 = name
    elif lvl == 2: r2 = name
    elif lvl == 3: r3 = name
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO role_names VALUES (%s,%s,%s,%s) ON CONFLICT(chat_id) DO UPDATE SET r1=EXCLUDED.r1, r2=EXCLUDED.r2, r3=EXCLUDED.r3", (m.chat.id, r1, r2, r3))
            conn.commit()
    await m.answer(f"✅ Должность уровня {lvl} переименована в **{name}**!", parse_mode="Markdown")

# Повышение / Назначение модераторов
@dp.message(F.text.lower().startswith("повысить") | F.text.lower().startswith("+модер"))
async def promote_user(m: Message):
    my_lvl = await get_user_lvl(m, m.from_user.id)
    if my_lvl < 3: return await m.answer("⚠️ Повышать участников могут только Администраторы.")
    if not m.reply_to_message: return await m.answer("Ответьте на сообщение пользователя.")
    p = m.text.split()
    target_lvl = int(p[1]) if len(p) > 1 and p[1].isdigit() else 1
    if target_lvl >= my_lvl: return await m.answer(f"⚠️ Вы можете повышать только до уровня ниже вашего (максимум {my_lvl - 1}).")
    
    target = m.reply_to_message.from_user
    r1, r2, r3 = get_role_names(m.chat.id)
    role_title = {1: r1, 2: r2, 3: r3}.get(target_lvl, "Модератор")

    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO mod_roles VALUES (%s,%s,%s) ON CONFLICT(chat_id, user_id) DO UPDATE SET role_level=EXCLUDED.role_level", (m.chat.id, target.id, target_lvl))
            conn.commit()

    # Выдача прав админа в ТГ для уровня >= 2
    if target_lvl >= 2:
        try: await m.chat.promote_member(target.id, can_restrict_members=True, can_delete_messages=True, can_invite_users=True)
        except Exception as e: await m.answer(f"⚠️ Не удалось выдать права в Telegram: {e}")

    await m.answer(f"👑 Пользователь {target.first_name} назначен на должность **{role_title}** (Уровень {target_lvl})!", parse_mode="Markdown")

# Понижение / Снятие модераторов
@dp.message(F.text.lower().startswith("понизить") | F.text.lower().startswith("-модер"))
async def demote_user(m: Message):
    my_lvl = await get_user_lvl(m, m.from_user.id)
    if my_lvl < 3: return await m.answer("⚠️ Понижать могут только Администраторы.")
    if not m.reply_to_message: return await m.answer("Ответьте на сообщение пользователя.")
    
    target = m.reply_to_message.from_user
    target_lvl = await get_user_lvl(m, target.id)
    if target_lvl >= my_lvl: return await m.answer("⚠️ Вы не можете понизить участника с уровнем равным или выше вашего.")

    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM mod_roles WHERE chat_id=%s AND user_id=%s", (m.chat.id, target.id))
            conn.commit()
    try: await m.chat.promote_member(target.id, can_restrict_members=False, can_delete_messages=False, can_invite_users=False)
    except: pass
    await m.answer(f"🔻 {target.first_name} разжалован до обычного участника.")

# Устав Сада (Правила)
@dp.message(F.text.startswith("+устав") | F.text.startswith("+правила"))
async def set_rules(m: Message):
    if await get_user_lvl(m, m.from_user.id) < 3: return await m.answer("⚠️ Изменять устав сада могут только Админы.")
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+устав [текст правил]`", parse_mode="Markdown")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO chat_rules VALUES (%s,%s) ON CONFLICT(chat_id) DO UPDATE SET rules_text=EXCLUDED.rules_text", (m.chat.id, p[1]))
            conn.commit()
    await m.answer("📜 **Устав сада успешно обновлён!**", parse_mode="Markdown")

@dp.message(F.text.lower().in_(["устав сада", "устав", "правила", "правила сада"]))
async def get_rules(m: Message):
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT rules_text FROM chat_rules WHERE chat_id=%s", (m.chat.id,))
            res = c.fetchone()
    if not res or not res[0]: return await m.answer("📜 Устав сада еще не установлен. Используйте `+устав [текст]`.", parse_mode="Markdown")
    await m.answer(f"📜 **Устав сада:**\n\n{res[0]}", parse_mode="Markdown")

# Кастомные Ники
@dp.message(F.text.startswith("+ник"))
async def set_nick(m: Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+ник [ник]`", parse_mode="Markdown")
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    if m.reply_to_message and await get_user_lvl(m, m.from_user.id) < 1:
        return await m.answer("⚠️ Менять ники другим могут только модераторы.")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO custom_nicknames VALUES (%s,%s,%s) ON CONFLICT(chat_id, user_id) DO UPDATE SET nickname=EXCLUDED.nickname", (m.chat.id, target.id, p[1].strip()))
            conn.commit()
    await m.answer(f"🏷 РП-ник для {target.first_name}: **{p[1].strip()}**", parse_mode="Markdown")

@dp.message(F.text == "-ник")
async def rem_nick(m: Message):
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    if m.reply_to_message and await get_user_lvl(m, m.from_user.id) < 1:
        return await m.answer("⚠️ Сбрасывать ники другим могут только модераторы.")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM custom_nicknames WHERE chat_id=%s AND user_id=%s", (m.chat.id, target.id))
            del_cnt = c.rowcount
            conn.commit()
    await m.answer(f"🗑 РП-ник {target.first_name} сброшен." if del_cnt else "⚠️ РП-ник не найден.")

@dp.message(F.text.lower().startswith("ники") | F.text.lower().startswith("звания"))
async def list_nicks(m: Message):
    p = m.text.split()
    page = max(1, int(p[1]) if len(p) > 1 and p[1].isdigit() else 1)
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM custom_nicknames WHERE chat_id=%s", (m.chat.id,))
            total = c.fetchone()[0]
            if not total: return await m.answer("📝 Ни у кого нет кастомных ников.")
            pages = math.ceil(total / 10)
            c.execute("SELECT n.user_id, n.nickname, a.first_name FROM custom_nicknames n LEFT JOIN user_activity a ON n.chat_id=a.chat_id AND n.user_id=a.user_id WHERE n.chat_id=%s ORDER BY n.nickname LIMIT 10 OFFSET %s", (m.chat.id, (min(page, pages)-1)*10))
            rows = c.fetchall()
    msg = f"🏷 **Ники чата ({min(page, pages)}/{pages}):**\n\n" + "\n".join([f"{i}. **{nk}** *({orig or 'ID:'+str(uid)})*" for i, (uid, nk, orig) in enumerate(rows, (min(page, pages)-1)*10 + 1)])
    await m.answer(msg, parse_mode="Markdown")

# Управление РП-командами
@dp.message(F.text.startswith("+комманда") | F.text.startswith("+команда"))
async def add_cmd(m: Message):
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: `+команда [имя] [текст]`\nЗаглушки: `{Username}`, `{Reply}`, `{Reply_message}`, `{Random}`", parse_mode="Markdown")
    c_name = p[1].lower().strip()

    # Проверка на запрещённые/конфликтующие имена
    for pat in FORBIDDEN_PATTERNS:
        if re.fullmatch(pat, c_name):
            return await m.answer("⚠️ Нельзя создавать РП-команды, совпадающие или конфликтующие с системными командами (устав, правила, актив, варн и т.д.).")

    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT command_name FROM custom_commands WHERE chat_id=%s AND command_name=%s", (m.chat.id, c_name))
            if c.fetchone(): return await m.answer(f"⚠️ Команда `{c_name}` уже существует! Сначала удалите её через `-команда {c_name}`.")
            c.execute("INSERT INTO custom_commands VALUES (%s,%s,%s)", (m.chat.id, c_name, p[2]))
            conn.commit()
    await m.answer(f"✅ РП-команда `{c_name}` сохранена!", parse_mode="Markdown")

@dp.message(F.text.startswith("-комманда") | F.text.startswith("-команда"))
async def del_cmd(m: Message):
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `-команда [имя]`", parse_mode="Markdown")
    c_name = p[1].lower().strip()
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM custom_commands WHERE chat_id=%s AND command_name=%s", (m.chat.id, c_name))
            del_cnt = c.rowcount
            conn.commit()
    await m.answer(f"🗑 Команда `{c_name}` удалена!" if del_cnt else "⚠️ Команда не найдена.")

@dp.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_cmds(m: Message):
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT command_name FROM custom_commands WHERE chat_id=%s ORDER BY command_name", (m.chat.id,))
            cmds = c.fetchall()
    if not cmds: return await m.answer("📝 В чате нет кастомных РП-команд.")
    await m.answer("📜 **РП-команды:**\n\n" + "\n".join([f"• `{c[0]}`" for c in cmds]), parse_mode="Markdown")

# Обработка сообщений и модерации
@dp.message(F.text)
async def process_msg(m: Message):
    if m.chat.type in ["private"]: return
    t = m.text.lower().strip()
    
    # Фиксация активности
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO user_activity VALUES (%s,%s,%s,%s,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET message_count=user_activity.message_count+1, username=EXCLUDED.username, first_name=EXCLUDED.first_name", (m.chat.id, m.from_user.id, m.from_user.username, m.from_user.first_name))
            conn.commit()

    lvl = await get_user_lvl(m, m.from_user.id)

    # ХЕЛПЕР (Уровень 1+) — МУТ / РАЗМУТ
    if lvl >= 1:
        if (t.startswith("клиновый сироп") or t.startswith("напоить сиропом")) and m.reply_to_message:
            mins, disp = parse_time(t.replace("клиновый сироп","").replace("напоить сиропом","").strip())
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(minutes=mins))
                return await m.answer(f"🍁 {m.reply_to_message.from_user.first_name} молчит {disp}.")
            except Exception as e: return await m.answer(f"Ошибка: {e}")
        elif t == "дать воды" and m.reply_to_message:
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
                return await m.answer(f"💧 {m.reply_to_message.from_user.first_name} размучен!")
            except Exception as e: return await m.answer(f"Ошибка: {e}")

    # МОДЕР (Уровень 2+) — БАН / КИК / СТАТИСТИКА
    if lvl >= 2:
        if t in ["банка с джемом", "в банку"] and m.reply_to_message:
            try:
                await m.chat.ban(m.reply_to_message.from_user.id)
                return await m.answer(f"🫙 {m.reply_to_message.from_user.first_name} забанен!")
            except Exception as e: return await m.answer(f"Ошибка: {e}")
        elif t.startswith("вытащить из банки"):
            p = t.split()
            if len(p) > 3 and p[3].startswith("@"):
                with get_db() as conn:
                    with conn.cursor() as c:
                        c.execute("SELECT user_id FROM user_activity WHERE chat_id=%s AND LOWER(username)=%s", (m.chat.id, p[3].replace("@","")))
                        res = c.fetchone()
                if res:
                    try:
                        await m.chat.unban(res[0])
                        return await m.answer(f"🔓 {p[3]} разбанен!")
                    except Exception as e: return await m.answer(f"Ошибка: {e}")
        elif t in ["актив", "стата", "статистика"]:
            with get_db() as conn:
                with conn.cursor() as c:
                    c.execute("SELECT first_name, message_count FROM user_activity WHERE chat_id=%s ORDER BY message_count DESC LIMIT 20", (m.chat.id,))
                    top = c.fetchall()
            if not top: return await m.answer("Статистика пуста.")
            msg = "📊 **ТОП-20 участников:**\n\n" + "\n".join([f"{i}. {name} — {cnt} сообщ." for i, (name, cnt) in enumerate(top, 1)])
            return await m.answer(msg, parse_mode="Markdown")

    # АДМИН (Уровень 3+) — ВАРНЫ / ПЛОД БОЛИ
    if lvl >= 3:
        if t == "дать плод всей боли" and m.reply_to_message:
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(days=1))
                return await m.answer(f"🍎 {m.reply_to_message.from_user.first_name} в муте на 1 день.")
            except Exception as e: return await m.answer(f"Ошибка: {e}")
        elif t in ["варн", "отругать"] and m.reply_to_message:
            u = m.reply_to_message.from_user
            with get_db() as conn:
                with conn.cursor() as c:
                    c.execute("SELECT warn_count FROM warn_system WHERE chat_id=%s AND user_id=%s", (m.chat.id, u.id))
                    res = c.fetchone()
                    warns = (res[0] if res else 0) + 1
                    if warns >= 3:
                        c.execute("DELETE FROM warn_system WHERE chat_id=%s AND user_id=%s", (m.chat.id, u.id))
                        conn.commit()
                        try:
                            await m.chat.ban(u.id)
                            return await m.answer(f"🫙 {u.first_name} получил [3/3] варнов и забанен!")
                        except Exception as e: return await m.answer(f"Ошибка: {e}")
                    else:
                        c.execute("INSERT INTO warn_system VALUES (%s,%s,%s) ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count=EXCLUDED.warn_count", (m.chat.id, u.id, warns))
                        conn.commit()
                        return await m.answer(f"⚠️ {u.first_name} получил предупреждение! [{warns}/3]")

    # ВЫПОЛНЕНИЕ РП-КОМАНД (для всех)
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT response_text FROM custom_commands WHERE chat_id=%s AND command_name=%s", (m.chat.id, t))
            cmd = c.fetchone()
    if cmd:
        sender = get_name(m.chat.id, m.from_user.id, m.from_user.first_name if m.from_user else "Кто-то")
        reply_user, reply_txt = "кого-то", ""
        if m.reply_to_message:
            if m.reply_to_message.from_user:
                reply_user = get_name(m.chat.id, m.reply_to_message.from_user.id, m.reply_to_message.from_user.first_name)
            reply_txt = m.reply_to_message.text or m.reply_to_message.caption or ""

        # Подстановка {Random}
        rand_user = "Кто-то"
        with get_db() as conn:
            with conn.cursor() as c:
                c.execute("SELECT user_id, first_name FROM user_activity WHERE chat_id=%s", (m.chat.id,))
                users = c.fetchall()
                if users:
                    ru_id, ru_fn = random.choice(users)
                    rand_user = get_name(m.chat.id, ru_id, ru_fn)

        text = cmd[0].format(Username=sender, Reply=reply_user, Reply_message=reply_txt, Random=rand_user)
        await m.answer(text)

async def main():
    logging.info("Бот запущен с Supabase Postgres!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
