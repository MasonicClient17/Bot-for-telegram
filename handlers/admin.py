import logging
from datetime import datetime
from aiogram import Router, F, types, html
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError
from config import bot
from database import db_query, get_text, get_cmd_name
from utils import check_access, get_display_name, try_delete, schedule_sync

router = Router()

# Установка нормы
@router.message(F.text.lower().startswith("норма"))
async def set_chat_norm(m: types.Message):
    if m.chat.type == "private" or not await check_access(m, "норма"):
        return
    parts = m.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.answer("☕ Формат: <code>норма [число]</code>")
    val = int(parts[1])
    await db_query("INSERT OR REPLACE INTO chat_norms (chat_id, min_messages) VALUES (?, ?)", (m.chat.id, val), commit=True)
    schedule_sync()
    await try_delete(m)
    text = await get_text(m.chat.id, "norm_set", val=val)
    await m.answer(text)

# Изменение текстов бота через чат: +текст [ключ] [значение]
@router.message(F.text.lower().startswith("+текст"))
async def set_dynamic_phrase(m: types.Message):
    if m.chat.type == "private" or not await check_access(m, "+текст"):
        return
    parts = m.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("☕ Формат: <code>+текст [ключ] [новый текст]</code>\n\nКлючи: <code>profile_title</code>, <code>welcome_text</code>, <code>norm_set</code>, <code>cookie_get</code>, <code>cookie_cooldown</code>")
    key, val = parts[1], parts[2]
    await db_query("INSERT OR REPLACE INTO dynamic_phrases VALUES (?, ?, ?)", (m.chat.id, key, val), commit=True)
    await m.answer(f"🌿 Текст для ключа <code>{key}</code> успешно обновлен!")

# Изменение названий админ-команд через чат: +команда [действие] [новое_имя]
@router.message(F.text.lower().startswith("+команда"))
async def set_dynamic_command(m: types.Message):
    if m.chat.type == "private" or not await check_access(m, "+команда"):
        return
    parts = m.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("☕ Формат: <code>+команда [действие] [новое имя]</code>\n\nДействия: <code>ban</code>, <code>mute</code>, <code>unmute</code>, <code>warn</code>")
    action, name = parts[1].lower(), parts[2].lower()
    await db_query("INSERT OR REPLACE INTO dynamic_commands VALUES (?, ?, ?)", (m.chat.id, action, name), commit=True)
    await m.answer(f"🌿 Команда для действия <code>{action}</code> теперь называется: <b>{name}</b>")

# Универсальный обработчик админ-команд (удалить, -звук и т.д. по ответу или упоминанию)
@router.message()
async def dynamic_admin_handler(m: types.Message):
    if m.chat.type == "private" or not m.text:
        return
    text_lower = m.text.strip().lower()
    
    ban_cmd = await get_cmd_name(m.chat.id, "ban")
    mute_cmd = await get_cmd_name(m.chat.id, "mute")
    
    if text_lower.startswith(ban_cmd):
        if not await check_access(m, "ban"):
            return
        target_id = None
        if m.reply_to_message:
            target_id = m.reply_to_message.from_user.id
        elif len(m.text.split()) > 1:
            # Попытка извлечь упоминание или ID
            args = m.text.split()[1]
            if args.isdigit():
                target_id = int(args)
        
        if target_id:
            try:
                await bot.ban_chat_member(m.chat.id, target_id)
                name = await get_display_name(m.chat.id, target_id, "Участник")
                await m.answer(f"🌚 <b>{html.quote(name)}</b> отправляется в банку!")
                await try_delete(m)
            except TelegramAPIError as e:
                await m.answer(f"⚠️ Ошибка бана: {e}")

# Функция проверки нормок (вызывается из хэндлера сообщений)
async def check_and_enforce_norm(chat_id: int, user_id: int, user_first_name: str):
    current_week = datetime.now().strftime('%Y-W%V')
    user_data = await db_query("SELECT week_number, week_count FROM users WHERE chat_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
    if not user_data:
        return
    db_week_num, week_count = user_data[0], user_data[1]

    if db_week_num and db_week_num != current_week:
        norm_res = await db_query("SELECT min_messages FROM chat_norms WHERE chat_id=?", (chat_id,), fetchone=True)
        if norm_res and norm_res[0] > 0:
            min_norm = norm_res[0]
            if (week_count or 0) < min_norm:
                creator_res = await db_query("SELECT user_id FROM users WHERE chat_id=? ORDER BY role_level DESC LIMIT 1", (chat_id,), fetchone=True)
                if creator_res:
                    creator_id = creator_res[0]
                    target_name = await get_display_name(chat_id, user_id, user_first_name)
                    alert_text = (
                        f"Эта мультяшка не набрала норму, что делаем?\n\n"
                        f"👤 Пользователь: <b>{html.quote(target_name)}</b>\n"
                        f"📊 Сообщений: <b>{week_count or 0}</b> из <b>{min_norm}</b>."
                    )
                    builder = InlineKeyboardBuilder()
                    builder.button(text="Игнорировать", callback_data=f"norm_action:ignore:{chat_id}:{user_id}")
                    builder.button(text="Бан", callback_data=f"norm_action:ban:{chat_id}:{user_id}")
                    builder.adjust(2)
                    try:
                        await bot.send_message(creator_id, alert_text, reply_markup=builder.as_markup())
                    except TelegramAPIError:
                        pass
        await db_query("UPDATE users SET week_count = 1, week_number = ? WHERE chat_id=? AND user_id=?", (current_week, chat_id, user_id), commit=True)
    else:
        await db_query("UPDATE users SET msg_count = msg_count + 1, week_count = COALESCE(week_count, 0) + 1, week_number = COALESCE(week_number, ?) WHERE chat_id=? AND user_id=?", (current_week, chat_id, user_id), commit=True)

@router.callback_query(F.data.startswith("norm_action:"))
async def process_norm_action(call: types.CallbackQuery):
    _, action, chat_id_str, target_uid_str = call.data.split(":")
    chat_id, target_uid = int(chat_id_str), int(target_uid_str)
    if action == "ignore":
        await call.message.edit_text("✨ Нарушитель проигнорирован.")
        return await call.answer()
    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id, target_uid)
            target_name = await get_display_name(chat_id, target_uid, "Участник")
            await bot.send_message(chat_id, f"🌚 <b>{html.quote(target_name)}</b> отправляется в банку!")
            await call.message.edit_text("🔨 Забанен.")
        except TelegramAPIError as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)
            
