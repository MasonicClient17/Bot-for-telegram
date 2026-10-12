# Centralized text templates and command triggers using the new emoji style:
# ☁️🪼🌌🌃📺📷📸📞🩻📃📼🎇🌫️

DEFAULT_PHRASES = {
    # General / Profile
    "profile": (
        "🌌 <b>ПРОФИЛЬ УЧАСТНИКА</b> :: {user}\n\n"
        "📃 Дата подключения.txt: <code>{joined_at}</code>\n"
        "📼 Кассет.dll: <code>{tapes}</code>\n"
        "📺 [Н О Р М А.exe]: <code>{msg_count}</code> / {min_norm} сообщений\n"
        "🩻 Статус: <i>{status}</i>\n"
        "📸 Репутация: <code>{rep}</code>"
    ),
    
    # Access and errors
    "no_access": "🌫️ У вас недостаточно прав для выполнения этой команды.",
    "wrong_chat": "🌫️ Бот работает только в авторизованных чатах.",
    "user_not_found": "🌫️ Участник не найден или не зарегистрирован в базе.",
    
    # Moderation
    "ban_success": "🌃 Участник {target} был исключен из чата. Причина: <i>{reason}</i>",
    "mute_success": "🩻 Участнику {target} ограничен голос на {time}. Причина: <i>{reason}</i>",
    "unmute_success": "📞 Участнику {target} возвращена возможность говорить.",
    "warn_success": "🩻 Участник {target} получил предупреждение ({warns}/3). Причина: <i>{reason}</i>",
    "unwarn_success": "📃 С участника {target} снято предупреждение ({warns}/3).",
    
    # Social / Marriages
    "marry_req": "💍 {user} предлагает {target} заключить брак.\n\n📷 Напишите <code>+брак</code> для согласия или <code>-брак</code> для отказа.",
    "marry_success": "🌌 Поздравляем! {user} и {target} теперь состоят в браке! 🎆",
    "marry_decline": "🌫️ Предложение брака отклонено.",
    "divorce_success": "🌫️ Брак между {user} и {target} был расторгнут.",
    
    # Economy / Items
    "cookie_get": "🍪 Предсказание на сегодня:\n\n💬 <i>«{text}»</i>\n\n📼 Начислено кассет: +<code>{tapes}</code>",
    "cookie_cooldown": "📷 Вы уже получали предсказание сегодня. Загляните завтра!",
    
    # Backup & Admin
    "backup_success": "📼 <b>Успешно!</b> Все данные, настройки и сообщения сохранены в архив.",
    "backup_error": "🌫️ Ошибка при попытке создания бэкапа: {error}",
    "cmd_changed": "📸 Команда <code>{old_cmd}</code> успешно переименована в <code>{new_cmd}</code>!"
}

# Default triggers mapped to internal action keys
DEFAULT_COMMANDS = {
    "ban": "бан",
    "mute": "мут",
    "unmute": "размут",
    "warn": "варн",
    "unwarn": "разварн",
    "profile": "профиль",
    "whoami": "кто я",
    "whois": "кто ты",
    "marry": "+брак",
    "divorce": "-брак",
    "save": "/save"
}
