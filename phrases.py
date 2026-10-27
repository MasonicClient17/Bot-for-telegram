# -*- coding: utf-8 -*-

START_MESSAGE = "🌃Привет! Я бот для управления чатом и модерации."

# Ошибки и ограничения
ERR_BOT_TARGET = "🌁Вы не можете рпшить с ботом."
ERR_SYSTEM_COMMAND = "🌁Нельзя использовать системное имя для РП-команды."
ERR_COMMAND_EXISTS = "🌁РП-команда с таким названием уже существует в этом чате."
ERR_COMMAND_NOT_FOUND = "🌁РП-команда не найдена."
ERR_BAD_COMMAND_NAME = "🌁Название РП-команды: до 32 символов, только буквы, цифры, _ и -."
ERR_NO_PERMISSION = "🌁У вас недостаточно прав для выполнения этой команды."
ERR_NOT_STORAGE_CHAT = (
    "🌁Команда /save доступна только в специальном хранилище.\n"
    "ID этого чата: <code>{chat_id}</code>\n"
    "STORAGE_CHAT_ID в настройках: <code>{storage_id}</code>"
)
ERR_USER_NOT_FOUND = "🌁Пользователь не найден. Убедитесь, что отвечаете на его сообщение или указали @username."
ERR_GROUP_ONLY = "🌁Эта команда работает только в группах."
ERR_NEED_REPLY = "🌁Эта РП-команда требует ответа на сообщение пользователя."
ERR_BAD_LEVEL = "🌁Недопустимый уровень модерации."
ERR_TOO_LONG = "🌁Слишком длинный текст (максимум {limit} символов)."
ERR_ACTION_FAILED = "🌁Не удалось выполнить действие: {error}"
ERR_BACKUP_FAILED = "🌁Не удалось отправить бэкап: {error}"

# Подсказки по использованию
USAGE_NICK = "🌁Использование: +ник Имя"
USAGE_TAG = "🌁Использование: тэг @username текст (или ответом на сообщение: тэг текст)"
USAGE_COMMAND_CREATE = "🌁Использование: +команда название текст ({user}, {reply}, {random})"
USAGE_COMMAND_DELETE = "🌁Использование: -команда название"
USAGE_MODER = "🌁Использование: /модер уровень (0–{max}) — ответом на сообщение или с @username в конце"

# Успешные действия
RP_NAME_SET = "🌌Ваш РП-ник успешно установлен: {name}"
RP_NAME_RESET = "🌌Ваш РП-ник сброшен."
TAG_SET = "🌌Тэг для пользователя {user} успешно установлен: {tag}"
COMMAND_CREATED = "🌌РП-команда +{name} успешно создана!"
COMMAND_DELETED = "🌌РП-команда +{name} удалена."

# Модерация
MUTE_SUCCESS = "📃Пользователь {user} заглушен. Срок: {duration}. Причина: {reason}"
UNMUTE_SUCCESS = "📃Пользователь {user} размьючен."
WARN_SUCCESS = "📃Пользователь {user} получил предупреждение ({count}/3). Причина: {reason}"
WARN_LIMIT_REACHED = "📃Пользователь {user} набрал 3 предупреждения и был автоматически заблокирован!"
UNWARN_SUCCESS = "📃С пользователя {user} снято предупреждений: {count}. Текущих: {total}"
BAN_SUCCESS = "📃Пользователь {user} заблокирован. Причина: {reason}"
MODER_SET = "📃Уровень модерации пользователя {user} установлен на {level}."

# Активность и команды
EMPTY_ACTIVITY = "🌉В этом чате пока нет записей об активности."
ACTIVITY_HEADER = "📸 Топ участников чата (Страница {page}/{total}):\n\n"
ACTIVITY_LINE = "🌫️{index}. {name} — {count} сообщ.\n"
COMMANDS_LIST_HEADER = "📜 Список РП-команд:\n\n"
COMMANDS_LIST_ITEM = "• +{name}\n"
COMMANDS_EMPTY = "📺В этом чате пока нет созданных РП-команд."

# Бэкап
BACKUP_SUCCESS = "💾 Ручной бэкап базы данных (/save)."
SHUTDOWN_BACKUP_CAPTION = "🤖 Бот выключается. Автоматический бэкап базы данных."
PERIODIC_BACKUP_CAPTION = "🕓 Плановый бэкап базы данных."

# Недельная норма сообщений
QUOTA_REPORT = (
    "📋 <b>Недельная норма не выполнена</b>\n\n"
    "Группа: {chat}\n"
    "Участник: {user}\n"
    "Сообщений за неделю: {count} из {quota}\n"
    "Присоединился: {joined}"
)
QUOTA_FALLBACK_NOTE = "\n\n⚠️ Владелец группы не запускал бота, поэтому отчёт отправлен вам."
QUOTA_TRUNCATED = "ℹ️ В «{chat}» ещё {n} участников не набрали норму (показаны первые {shown})."
QUOTA_CONFIRM = "⚠️ <b>Вы уверены?</b>\n\nУчастник {user} будет заблокирован в группе «{chat}»."

QUOTA_BTN_IGNORE = "🔵 IGNORE"
QUOTA_BTN_WARN = "🟠 WARN"
QUOTA_BTN_KICK = "🔴 KICK"
QUOTA_BTN_ERROR404 = "🟣 ERROR404"
QUOTA_BTN_YES = "🔴 YES"
QUOTA_BTN_NO = "⚪ NO"

QUOTA_ALREADY = "Этот отчёт уже обработан."
QUOTA_DM_FAILED = "Резюме удалено, но личное предупреждение не доставлено: участник не запускал бота."
QUOTA_RES_IGNORE = "🔵 Игнор: {user}. Участнику отправлено предупреждение."
QUOTA_RES_WARN = "🟠 {user}: выдан варн на 7 дней ({total}/3)."
QUOTA_RES_WARN_BAN = "🔴 {user} набрал 3 предупреждения и заблокирован в «{chat}»."
QUOTA_RES_KICK = "🔴 {user} исключён из «{chat}» (может вернуться по ссылке)."
QUOTA_RES_BAN = "⛔ {user} заблокирован в «{chat}»."
QUOTA_ACTION_FAILED = "Не удалось: {error}"

QUOTA_USER_IGNORED = (
    "🔔 Вы не набрали недельную норму сообщений в группе «{chat}» ({count} из {quota}). "
    "Пока без последствий, но будьте активнее!"
)
QUOTA_USER_WARNED = (
    "⚠️ Вы получили предупреждение на 7 дней в группе «{chat}»: "
    "за неделю {count} из {quota} сообщений."
)
