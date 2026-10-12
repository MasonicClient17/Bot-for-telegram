from aiogram import Router, F, types
from config import bot, GROUP_ID
from database import db_query
from utils import (
    is_authorized_chat,
    get_text,
    get_cmd_name,
    check_access,
    get_norm_keyboard,
    try_delete
)

router = Router()

# Кэш сессий проверки норм: {admin_id: [user_ids]}
ACTIVE_NORMS = {}

@router.message(F.text)
async def norms_handler(m: types.Message):
    # 1. Настройка личного напоминания в ЛС бота
    if m.chat.type == "private":
        text = m.text.strip()
        text_lower = text.lower()
        cmd_reminder = await get_cmd_name(m.chat.id, "reminder")
        
        if text_lower.startswith("напоминание") or text_lower.startswith(cmd_reminder.lower()):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await m.answer("🌫️ Использование: <code>напоминание [ваш текст для отправки должникам]</code>")
                return
            reminder_text = parts[1].strip()
            await db_query(
                "INSERT OR REPLACE INTO custom_reminders (chat_id, user_id, reminder_text) VALUES (?,?,?)",
                (m.chat.id, m.from_user.id, reminder_text),
                commit=True
            )
            success_msg = await get_text(m.chat.id, "reminder_set_success")
            await m.answer(success_msg)
            return
        return

    # 2. Обработка команды проверки нормы в групповом чате
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip().lower()
    cmd_norm = await get_cmd_name(m.chat.id, "norm")

    if text not in ("норма", "проверить норму", cmd_norm.lower()):
        return

    if not await check_access(m, "ban"):
        no_acc = await get_text(m.chat.id, "no_access")
        await m.answer(no_acc)
        return

    await try_delete(m)

    # Получаем минимальную норму чата
    norm_row = await db_query("SELECT min_messages FROM chat_norms WHERE chat_id=?", (m.chat.id,), fetchone=True)
    min_norm = norm_row[0] if norm_row else 10

    # Находим должников
    rows = await db_query(
        "SELECT user_id, msg_count FROM users WHERE chat_id=? AND msg_count < ?",
        (m.chat.id, min_norm),
        fetchall=True
    )

    if not rows:
        msg = await get_text(m.chat.id, "norm_completed_all")
        await m.answer(msg)
        return

    non_compliant_ids = [row[0] for row in rows]
    ACTIVE_NORMS[m.from_user.id] = non_compliant_ids

    target_id = non_compliant_ids[0]
    text_content, keyboard = await build_personal_file_view(m.chat.id, target_id, 0, len(non_compliant_ids))
    
    try:
        await bot.send_message(m.from_user.id, text_content, reply_markup=keyboard)
        await m.answer("🌃 Отчет по невыполненной норме отправлен вам в личные сообщения.")
    except Exception:
        await m.answer(text_content, reply_markup=keyboard)


async def build_personal_file_view(chat_id: int, target_id: int, page: int, total: int):
    target_row = await db_query(
        "SELECT joined_at, tapes, msg_count, status, rep FROM users WHERE chat_id=? AND user_id=?",
        (chat_id, target_id),
        fetchone=True
    )
    member_row = await db_query(
        "SELECT first_name FROM chat_members WHERE chat_id=? AND user_id=?",
        (chat_id, target_id),
        fetchone=True
    )
    norm_row = await db_query("SELECT min_messages FROM chat_norms WHERE chat_id=?", (chat_id,), fetchone=True)
    min_norm = norm_row[0] if norm_row else 10

    user_name = member_row[0] if member_row else "Участник"
    joined_at = target_row[0] if target_row else "-"
    tapes = target_row[1] if target_row else 0
    msg_count = target_row[2] if target_row else 0
    status = target_row[3] if target_row else "Участник"
    rep = target_row[4] if target_row else 0

    profile_text = await get_text(
        chat_id,
        "profile",
        user=f"{user_name} (Должник {page + 1}/{total})",
        joined_at=joined_at,
        tapes=tapes,
        msg_count=msg_count,
        min_norm=min_norm,
        status=status,
        rep=rep
    )
    keyboard = get_norm_keyboard(target_id, page, total)
    return profile_text, keyboard


@router.callback_query(F.data.startswith("norm_"))
async def norm_callback_handler(call: types.CallbackQuery):
    data_parts = call.data.split(":")
    action = data_parts[1]
    admin_id = call.from_user.id

    if admin_id not in ACTIVE_NORMS or not ACTIVE_NORMS[admin_id]:
        await call.answer("Сессия проверки устарела. Запустите команду заново.", show_alert=True)
        return

    user_ids = ACTIVE_NORMS[admin_id]
    total = len(user_ids)

    if action == "page":
        new_page = int(data_parts[2])
        if new_page < 0:
            new_page = total - 1
        elif new_page >= total:
            new_page = 0
        
        target_id = user_ids[new_page]
        text_content, keyboard = await build_personal_file_view(GROUP_ID, target_id, new_page, total)
        await call.message.edit_text(text_content, reply_markup=keyboard)
        await call.answer()
        return

    target_id = int(data_parts[2])
    page = int(data_parts[3]) if len(data_parts) > 3 else 0
    chat_id = GROUP_ID

    if action == "ignore":
        await call.answer("Участник проигнорирован.")
        next_page = (page + 1) % total
        target_id = user_ids[next_page]
        text_content, keyboard = await build_personal_file_view(chat_id, target_id, next_page, total)
        await call.message.edit_text(text_content, reply_markup=keyboard)

    elif action == "warn":
        await db_query("UPDATE users SET warns = warns + 1 WHERE chat_id=? AND user_id=?", (chat_id, target_id), commit=True)
        await call.answer("Предупреждение выдано!", show_alert=True)
        next_page = (page + 1) % total
        target_id = user_ids[next_page]
        text_content, keyboard = await build_personal_file_view(chat_id, target_id, next_page, total)
        await call.message.edit_text(text_content, reply_markup=keyboard)

    elif action == "remind":
        rem_row = await db_query("SELECT reminder_text FROM custom_reminders WHERE chat_id=? AND user_id=?", (chat_id, admin_id), fetchone=True)
        if not rem_row:
            rem_row = await db_query("SELECT reminder_text FROM custom_reminders WHERE user_id=?", (admin_id,), fetchone=True)
        
        reminder_text = rem_row[0] if rem_row else await get_text(chat_id, "reminder_default")
        
        try:
            await bot.send_message(target_id, f"🌌 <b>Напоминание от администрации:</b>\n{reminder_text}")
            await call.answer("Напоминание отправлено в личные сообщения участнику!", show_alert=True)
        except Exception:
            await call.answer("Не удалось отправить сообщение (возможно, бот заблокирован пользователем).", show_alert=True)

    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id, target_id)
            await call.answer("Участник забанен!", show_alert=True)
            if target_id in user_ids:
                user_ids.remove(target_id)
            if not user_ids:
                await call.message.edit_text("🌃 Все должники обработаны!")
                return
            next_page = page % len(user_ids)
            target_id = user_ids[next_page]
            text_content, keyboard = await build_personal_file_view(chat_id, target_id, next_page, len(user_ids))
            await call.message.edit_text(text_content, reply_markup=keyboard)
        except Exception as e:
            await call.answer(f"Ошибка при бане: {e}", show_alert=True)
  
