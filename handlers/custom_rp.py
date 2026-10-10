from aiogram import Router, F, types, html
from database import db_query
from utils import check_access, parse_rp_text, try_delete

router = Router()

@router.message(F.text.lower().startswith("сделать команда"))
async def make_custom_cmd(m: types.Message):
    if m.chat.type == "private" or not await check_access(m, "сделать команда"):
        return
    parts = m.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("☕ Формат: <code>сделать команда [имя] [текст действия с {c}]</code>")
    cmd_name, response = parts[1].lower(), parts[2]
    await db_query("INSERT OR REPLACE INTO custom_commands VALUES (?, ?, ?)", (m.chat.id, cmd_name, response), commit=True)
    await try_delete(m)
    await m.answer(f"🌿 РП-команда «<code>{cmd_name}</code>» успешно создана!")

# Перехват кастомных команд и обработка {c}
@router.message()
async def execute_custom_cmd(m: types.Message):
    if m.chat.type == "private" or not m.text:
        return
    cmd_word = m.text.strip().split()[0].lower()
    row = await db_query("SELECT response_text FROM custom_commands WHERE chat_id=? AND command_name=?", (m.chat.id, cmd_word), fetchone=True)
    if row:
        raw_resp = row[0]
        parsed = parse_rp_text(raw_resp)
        await try_delete(m)
        await m.answer(parsed)
        
