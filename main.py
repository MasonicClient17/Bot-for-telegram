import asyncio, logging, math, os, re, psycopg2
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatPermissions, Message

logging.basicConfig(level=logging.INFO)
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Wacestall081215550570@db.vgdtikonjidhrdykchcy.supabase.co:5432/postgres")

def get_db():
    return psycopg2.connect(DB_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (chat_id BIGINT, user_id BIGINT, username TEXT, first_name TEXT, message_count INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS warn_system (chat_id BIGINT, user_id BIGINT, warn_count INT DEFAULT 0, PRIMARY KEY (chat_id, user_id));
                CREATE TABLE IF NOT EXISTS custom_commands (chat_id BIGINT, command_name TEXT, response_text TEXT, PRIMARY KEY (chat_id, command_name));
                CREATE TABLE IF NOT EXISTS custom_nicknames (chat_id BIGINT, user_id BIGINT, nickname TEXT, PRIMARY KEY (chat_id, user_id));
            """)
            conn.commit()

init_db()

async def is_admin(m: Message) -> bool:
    if m.chat.type in ["private"]: return False
    return (await m.bot.get_chat_member(m.chat.id, m.from_user.id)).status in ["administrator", "creator"]

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

@dp.message(F.text.startswith("+ник"))
async def set_nick(m: Message):
    if m.chat.type in ["private"]: return
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `+ник [ник]`", parse_mode="Markdown")
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    if m.reply_to_message and not await is_admin(m):
        return await m.answer("⚠️ Менять ники другим могут только админы.")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO custom_nicknames VALUES (%s,%s,%s) ON CONFLICT(chat_id, user_id) DO UPDATE SET nickname=EXCLUDED.nickname", (m.chat.id, target.id, p[1].strip()))
            conn.commit()
    await m.answer(f"🏷 РП-ник для {target.first_name}: **{p[1].strip()}**", parse_mode="Markdown")

@dp.message(F.text == "-ник")
async def rem_nick(m: Message):
    if m.chat.type in ["private"]: return
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    if m.reply_to_message and not await is_admin(m):
        return await m.answer("⚠️ Сбрасывать ники другим могут только админы.")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM custom_nicknames WHERE chat_id=%s AND user_id=%s", (m.chat.id, target.id))
            del_cnt = c.rowcount
            conn.commit()
    await m.answer(f"🗑 РП-ник {target.first_name} сброшен." if del_cnt else f"⚠️ У {target.first_name} не было РП-ника.")

@dp.message(F.text.lower().startswith("ники") | F.text.lower().startswith("звания"))
async def list_nicks(m: Message):
    if m.chat.type in ["private"]: return
    p = m.text.split()
    page = int(p[1]) if len(p) > 1 and p[1].isdigit() else 1
    page = max(1, page)
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM custom_nicknames WHERE chat_id=%s", (m.chat.id,))
            total = c.fetchone()[0]
            if not total: return await m.answer("📝 Ни у кого нет кастомных ников.")
            pages = math.ceil(total / 10)
            page = min(page, pages)
            c.execute("SELECT n.user_id, n.nickname, a.first_name FROM custom_nicknames n LEFT JOIN user_activity a ON n.chat_id=a.chat_id AND n.user_id=a.user_id WHERE n.chat_id=%s ORDER BY n.nickname LIMIT 10 OFFSET %s", (m.chat.id, (page-1)*10))
            rows = c.fetchall()
    msg = f"🏷 **Ники чата ({page}/{pages}):**\n\n" + "\n".join([f"{i}. **{nk}** *({orig or 'ID:'+str(uid)})*" for i, (uid, nk, orig) in enumerate(rows, (page-1)*10 + 1)])
    await m.answer(msg + "\n\n💡 `ники [стр]` для навигации.", parse_mode="Markdown")

@dp.message(F.text.startswith("+комманда") | F.text.startswith("+команда"))
async def add_cmd(m: Message):
    if m.chat.type in ["private"]: return await m.answer("⚠️ Только для групп.")
    p = m.text.split(maxsplit=2)
    if len(p) < 3: return await m.answer("Использование: `+команда [имя] [текст]`\nЗаглушки: `{Username}`, `{Reply}`, `{Reply_message}`", parse_mode="Markdown")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO custom_commands VALUES (%s,%s,%s) ON CONFLICT(chat_id, command_name) DO UPDATE SET response_text=EXCLUDED.response_text", (m.chat.id, p[1].lower(), p[2]))
            conn.commit()
    await m.answer(f"✅ Команда `{p[1].lower()}` сохранена!", parse_mode="Markdown")

@dp.message(F.text.startswith("-комманда") | F.text.startswith("-команда"))
async def del_cmd(m: Message):
    if m.chat.type in ["private"]: return
    p = m.text.split(maxsplit=1)
    if len(p) < 2: return await m.answer("Использование: `-команда [имя]`", parse_mode="Markdown")
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM custom_commands WHERE chat_id=%s AND command_name=%s", (m.chat.id, p[1].lower().strip()))
            del_cnt = c.rowcount
            conn.commit()
    await m.answer(f"🗑 Команда `{p[1].lower().strip()}` удалена!" if del_cnt else "⚠️ Команда не найдена.")

@dp.message(F.text.lower().in_(["список команд", "команды", "рп команды"]))
async def list_cmds(m: Message):
    if m.chat.type in ["private"]: return
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT command_name FROM custom_commands WHERE chat_id=%s ORDER BY command_name", (m.chat.id,))
            cmds = c.fetchall()
    if not cmds: return await m.answer("📝 В чате нет кастомных команд.")
    await m.answer("📜 **РП-команды:**\n\n" + "\n".join([f"• `{c[0]}`" for c in cmds]), parse_mode="Markdown")

@dp.message(F.text)
async def process_msg(m: Message):
    if m.chat.type in ["private"]: return
    t = m.text.lower().strip()
    if t.startswith(("+ник", "-ник", "+команда", "+комманда", "-команда", "-комманда")) or t in ["список команд", "команды", "рп команды", "ники", "звания"] or t.startswith(("ники ", "звания ")): return

    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO user_activity VALUES (%s,%s,%s,%s,1) ON CONFLICT(chat_id, user_id) DO UPDATE SET message_count=user_activity.message_count+1, username=EXCLUDED.username, first_name=EXCLUDED.first_name", (m.chat.id, m.from_user.id, m.from_user.username, m.from_user.first_name))
            conn.commit()

    if await is_admin(m):
        if t in ["банка с джемом", "в банку"] and m.reply_to_message:
            try:
                await m.chat.ban(m.reply_to_message.from_user.id)
                await m.answer(f"🫙 {m.reply_to_message.from_user.first_name} забанен!")
            except Exception as e: await m.answer(f"Ошибка: {e}")
            return
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
                        await m.answer(f"🔓 {p[3]} разбанен!")
                    except Exception as e: await m.answer(f"Ошибка: {e}")
            return
        elif t == "дать плод всей боли" and m.reply_to_message:
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(days=1))
                await m.answer(f"🍎 {m.reply_to_message.from_user.first_name} в муте на 1 день.")
            except Exception as e: await m.answer(f"Ошибка: {e}")
            return
        elif (t.startswith("клиновый сироп") or t.startswith("напоить сиропом")) and m.reply_to_message:
            mins, disp = parse_time(t.replace("клиновый сироп","").replace("напоить сиропом","").strip())
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(minutes=mins))
                await m.answer(f"🍁 {m.reply_to_message.from_user.first_name} молчит {disp}.")
            except Exception as e: await m.answer(f"Ошибка: {e}")
            return
        elif t == "дать воды" and m.reply_to_message:
            try:
                await m.chat.restrict(m.reply_to_message.from_user.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
                await m.answer(f"💧 {m.reply_to_message.from_user.first_name} размучен!")
            except Exception as e: await m.answer(f"Ошибка: {e}")
            return
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
                            await m.answer(f"🫙 {u.first_name} получил [3/3] варнов и забанен!")
                        except Exception as e: await m.answer(f"Ошибка: {e}")
                    else:
                        c.execute("INSERT INTO warn_system VALUES (%s,%s,%s) ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count=EXCLUDED.warn_count", (m.chat.id, u.id, warns))
                        conn.commit()
                        await m.answer(f"⚠️ {u.first_name} получил предупреждение! [{warns}/3]")
            return
        elif t in ["актив", "стата", "статистика"]:
            with get_db() as conn:
                with conn.cursor() as c:
                    c.execute("SELECT first_name, message_count FROM user_activity WHERE chat_id=%s ORDER BY message_count DESC LIMIT 20", (m.chat.id,))
                    top = c.fetchall()
            if not top: return await m.answer("Статистика пуста.")
            msg = "📊 **ТОП-20 участников:**\n\n" + "\n".join([f"{i}. {name} — {cnt} сообщ." for i, (name, cnt) in enumerate(top, 1)])
            return await m.answer(msg, parse_mode="Markdown")

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
        await m.answer(cmd[0].format(Username=sender, Reply=reply_user, Reply_message=reply_txt))

async def main():
    logging.info("Бот запущен с Supabase Postgres!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
