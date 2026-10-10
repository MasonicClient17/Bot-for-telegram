import logging
from aiogram import Router, F, types, html
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from config import bot
from database import db_query
from utils import (
    check_access,
    get_display_name,
    try_delete,
    schedule_sync
)

router = Router()

@router.message(F.text.lower().startswith("норма"))
async def set_chat_norm(m: types.Message):
    if m.chat.type == "private":
        return await m.answer("🫗 Эту команду нужно использовать в общем чате группы!")

    # Проверка уровня доступа (например, 2+ или хелпер/модер — используем check_access)
    if not await check_access(m, "норма"):
        return await m.answer("🌫️ У вас недостаточно прав для установки нормы!")

    parts = m.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.answer("🫗 Формат команды: <code>норма [число сообщений]</code> (например: <code>норма 50</code>)")

    norm_val = int(parts[1])

    await db_query(
        "INSERT OR REPLACE INTO chat_norms (chat_id, min_messages) VALUES (?, ?)",
        (m.chat.id, norm_val),
        commit=True
    )
    schedule_sync()
    await try_delete(m)
    await m.answer(f"🌸 Успешно установлена минимальная недельная норма сообщений: <b>{norm_val}</b>!")


# Инлайн-кнопки для наказания/игнорирования за невыполнение нормы
@router.callback_query(F.data.startswith("norm_action:"))
async def process_norm_action(call: types.CallbackQuery):
    _, action, chat_id_str, target_uid_str = call.data.split(":")
    chat_id = int(chat_id_str)
    target_uid = int(target_uid_str)

    if action == "ignore":
        try:
            await call.message.edit_text("✨ Нарушитель проигнорирован (наказание отменено).")
        except TelegramAPIError:
            pass
        return await call.answer("Норма проигнорирована.")

    elif action == "ban":
        try:
            # Баним пользователя в чате
            await bot.ban_chat_member(chat_id=chat_id, user_id=target_uid)
            
            target_name = await get_display_name(chat_id, target_uid, f"ID:{target_uid}")
            
            # Отправляем сообщение в общий чат (как при команде "в банку")
            ban_msg = f"🌚 <b>{html.quote(target_name)}</b> отправляется в банку!"
            await bot.send_message(chat_id, ban_msg)

            await call.message.edit_text(f"🔨 Пользователь {html.quote(target_name)} успешно забанен за невыполнение нормы.")
        except TelegramAPIError as e:
            await call.answer(f"Не удалось забанить: {e}", show_alert=True)
            logging.error(f"[NORM ERROR] Ошибка бана за норму: {e}")
          
