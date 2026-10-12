# Centralized text templates and command triggers using the new emoji style:
# ☁️🪼🌌🌃📺📷📸📞🩻📃📼🎇🌫️  
DEFAULT_COMMANDS = {
    "ban": "бан",
    "mute": "мут",
    "unmute": "размут",
    "warn": "варн",
    "unwarn": "унварн",
    "marry": "брак",
    "divorce": "развод",
    "profile": "профиль",
    "whoami": "кто я",
    "whois": "кто ты",
    "save": "сохранить",
    "norm": "норма",
    "reminder": "напоминание"
}

DEFAULT_PHRASES = {
    "no_access": "🌫️ У вас недостаточно прав для выполнения этой команды.",
    "user_not_found": "🌫️ Участник не найден. Упомяните его через @ или ответьте на его сообщение.",
    "ban_success": "🌃 Участник <b>{target}</b> был забанен.\nПричина: {reason}",
    "mute_success": "🌃 Участник <b>{target}</b> заглушен на {time}.\nПричина: {reason}",
    "unmute_success": "🌃 С участника <b>{target}</b> снято ограничение речи.",
    "warn_success": "⚠️ Участник <b>{target}</b> получил предупреждение ({warns}/3).\nПричина: {reason}",
    "unwarn_success": "🌃 С участника <b>{target}</b> снято предупреждение ({warns}/3).",
    "marry_req": "🌌 Участник <b>{user}</b> предлагает заключить брак с <b>{target}</b>!\nНапишите <code>брак</code> в ответ, чтобы согласиться.",
    "marry_success": "💍 Союз между <b>{user}</b> и <b>{target}</b> успешно заключен!",
    "divorce_success": "💔 <b>{user}</b> и <b>{target}</b> расторгли свой брак.",
    "cookie_cooldown": "⏳ Вы уже получали печеньку сегодня. Возвращайтесь завтра!",
    "cookie_get": "🍪 <b>Печенька получена!</b>\n{text}\n🎁 Награда: +{tapes} лента(ы).",
    "backup_success": "💾 Резервная копия базы данных успешно отправлена в архивный чат.",
    "backup_error": "🌫️ Ошибка при создании бэкапа: {error}",
    "cmd_changed": "🌃 Команда успешно переименована!\nСтарое название: <code>{old_cmd}</code>\nНовое название: <code>{new_cmd}</code>",
    "profile": (
        "🪼 <b>Личное дело участника: {user}</b>\n\n"
        "📅 В клубе с: <code>{joined_at}</code>\n"
        "📼 Ленты: <b>{tapes}</b>\n"
        "💬 Сообщений: <b>{msg_count}</b> (Мин. норма: {min_norm})\n"
        "✨ Статус: <i>{status}</i>\n"
        "⭐ Репутация: <b>{rep}</b>"
    ),
    "norm_completed_all": "🌃 Все активные участники успешно выполнили дневную норму сообщений!",
    "reminder_default": "Привет! Ты еще не выполнил норму сообщений в чате. Пожалуйста, прояви активность! 🌌",
    "reminder_set_success": "🌃 Текст твоего индивидуального напоминания успешно сохранен!"
}
