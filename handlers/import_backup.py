import json
from aiogram import Router, F, types
from config import SUPERUSER_ID
from database import db_query

router = Router()

@router.message(F.document, F.chat.type == "private")
async def import_json_backup(m: types.Message):
    if m.from_user.id != SUPERUSER_ID:
        return
    
    document = m.document
    if not document.file_name.endswith(".json"):
        await m.answer("🌫️ Пожалуйста, отправьте JSON-файл бэкапа.")
        return

    file_info = await m.bot.get_file(document.file_id)
    file_bytes = await m.bot.download_file(file_info.file_path)
    
    try:
        data = json.loads(file_bytes.decode("utf-8"))
    except Exception as e:
        await m.answer(f"🌫️ Ошибка чтения JSON: {e}")
        return

    for row in data.get("users", []):
        chat_id, user_id, role_level, rp_name, warns, msg_count, day_count, week_count, last_msg_date, week_number, joined_at, tapes = row
        await db_query(
            """INSERT OR REPLACE INTO users 
            (chat_id, user_id, role_level, warns, msg_count, rp_name, day_count, week_count, last_msg_date, week_number, joined_at, tapes, status, rep)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, user_id, role_level, warns, msg_count, rp_name, day_count, week_count, last_msg_date, week_number, joined_at, tapes, "Участник", 0),
            commit=True
        )

    for row in data.get("chat_members", []):
        await db_query(
            "INSERT OR REPLACE INTO chat_members (chat_id, user_id, first_name, username) VALUES (?, ?, ?, ?)",
            row,
            commit=True
        )

    for row in data.get("custom_commands", []):
        await db_query(
            "INSERT OR REPLACE INTO custom_commands (chat_id, command_name, response_text) VALUES (?, ?, ?)",
            row,
            commit=True
        )

    for row in data.get("mod_roles", []):
        await db_query("INSERT OR REPLACE INTO mod_roles (chat_id, user_id, role_level) VALUES (?, ?, ?)", row, commit=True)
    for row in data.get("cmd_levels", []):
        await db_query("INSERT OR REPLACE INTO cmd_levels (chat_id, cmd_name, min_lvl) VALUES (?, ?, ?)", row, commit=True)

    await m.answer("✨ <b>Старый бэкап успешно импортирован!</b> Все данные, участники и кастомные команды перенесены в новую базу SQLite.")
  
