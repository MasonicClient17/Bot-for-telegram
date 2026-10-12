import re
from aiogram import Router, F, types
from database import db_query
from utils import is_authorized_chat, check_access, try_delete, get_text
from phrases import DEFAULT_COMMANDS

router = Router()

@router.message(F.text)
async def custom_cmds_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip()
    
    # --- 1. Обработка команды переименования: изменить [старое] [новое] или изменить старое новое ---
    if text.lower().startswith("изменить"):
        if not await check_access(m, "ban"):  # Требуются права администратора
            no_acc = await get_text(m.chat.id, "no_access")
            await m.answer(no_acc)
            return
        
        # Парсим аргументы с поддержкой квадратных скобок
        match_brackets = re.findall(r'\[(.*?)\]', text)
        if len(match_brackets) >= 2:
            old_name = match_brackets[0].strip().lower()
            new_name = match_brackets[1].strip().lower()
        else:
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                await m.answer("🌫️ Использование: <code>изменить [старое] [новое]</code> или <code>изменить старое новое</code>")
                return
            old_name = parts[1].strip().lower()
            new_name = parts[2].strip().lower()

        # Ищем системный action_key по дефолтному триггеру или уже существующему кастомному
        action_key = None
        for key, default_trigger in DEFAULT_COMMANDS.items():
            if default_trigger.lower() == old_name:
                action_key = key
                break
            res = await db_query(
                "SELECT action_key FROM dynamic_commands WHERE chat_id=? AND LOWER(cmd_name)=?",
                (m.chat.id, old_name),
                fetchone=True
            )
            if res:
                action_key = res[0]
                break

        if not action_key:
            action_key = old_name

        # Сохраняем новое название команды в базу
        await db_query(
            "INSERT OR REPLACE INTO dynamic_commands (chat_id, action_key, cmd_name) VALUES (?,?,?)",
            (m.chat.id, action_key, new_name),
            commit=True
        )

        await try_delete(m)
        success_msg = await get_text(m.chat.id, "cmd_changed", old_cmd=old_name, new_cmd=new_name)
        await m.answer(success_msg)
        return

    # --- 2. Обработка пользовательских (кастомных) текстовых команд ---
    cmd_candidate = text.split()[0].lower() if text else ""
    custom_res = await db_query(
        "SELECT response_text FROM custom_commands WHERE chat_id=? AND LOWER(command_name)=?",
        (m.chat.id, cmd_candidate),
        fetchone=True
    )
    if custom_res:
        await try_delete(m)
        await m.answer(custom_res[0])
        return
        
