import asyncio
import html
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

import phrases
from config import get_creator_id, get_quota_utc_offset, get_weekly_quota
from db import Database

quota_router = Router()

WARN_DAYS = 7
MAX_REPORTS_PER_CHAT = 30     # защита от потока сообщений владельцу
CHECK_INTERVAL_SECONDS = 600
WEEK_SECONDS = 7 * 24 * 3600


# ---------- помощники ----------

def esc(value) -> str:
    return html.escape(str(value), quote=False)


def user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y")


def joined_text(row: dict) -> str:
    # Telegram не отдаёт ботам дату вступления — её знаем, только если бот видел вступление
    if row.get("joined_at"):
        return fmt_date(row["joined_at"])
    if row.get("first_seen"):
        return f"неизвестно (бот видит участника с {fmt_date(row['first_seen'])})"
    return "неизвестно"


def current_week_start_ts() -> int:
    """Начало текущей недели (понедельник 00:00 в выбранном часовом поясе) в UTC-секундах."""
    offset = timedelta(hours=get_quota_utc_offset())
    local = datetime.now(timezone.utc) + offset
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((monday - offset).timestamp())


def main_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=phrases.QUOTA_BTN_IGNORE, callback_data=f"q:ign:{report_id}"),
         InlineKeyboardButton(text=phrases.QUOTA_BTN_WARN, callback_data=f"q:wrn:{report_id}")],
        [InlineKeyboardButton(text=phrases.QUOTA_BTN_KICK, callback_data=f"q:kck:{report_id}"),
         InlineKeyboardButton(text=phrases.QUOTA_BTN_ERROR404, callback_data=f"q:e404:{report_id}")],
    ])


def confirm_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=phrases.QUOTA_BTN_YES, callback_data=f"q:yes:{report_id}"),
        InlineKeyboardButton(text=phrases.QUOTA_BTN_NO, callback_data=f"q:no:{report_id}"),
    ]])


# ---------- еженедельный отчёт ----------

async def report_chat(bot: Bot, db: Database, chat_id: int, quota: int, grace_cutoff: int):
    chat = await bot.get_chat(chat_id)
    title = chat.title or str(chat_id)

    owner_id = None
    for admin in await bot.get_chat_administrators(chat_id):
        if admin.status == "creator":
            owner_id = admin.user.id
            break
    # Сначала владелец группы, запасной вариант — создатель бота (CREATOR_ID)
    recipients = []
    for rid in (owner_id, get_creator_id()):
        if rid and rid not in recipients:
            recipients.append(rid)
    if not recipients:
        logging.warning("Нет получателя отчётов для чата %s", chat_id)
        return

    candidates = await db.get_quota_candidates(chat_id, quota, grace_cutoff)
    recipient_idx, sent, over = 0, 0, 0

    for row in candidates:
        user_id = row["user_id"]
        if await db.has_pending_report(chat_id, user_id):
            continue
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception as e:
            logging.debug("get_chat_member(%s, %s) не удался: %s", chat_id, user_id, e)
            continue
        if member.status in ("left", "kicked"):
            await db.mark_left(chat_id, user_id)
            continue
        if member.status == "creator" or member.user.is_bot:
            continue
        if sent >= MAX_REPORTS_PER_CHAT:
            over += 1
            continue

        name = row["first_name"] or row["rp_name"] or "Участник"
        who = user_link(user_id, name)
        if row["username"]:
            who += f" (@{esc(row['username'])})"
        who += f" · ID <code>{user_id}</code>"
        text = phrases.QUOTA_REPORT.format(
            chat=esc(title), user=who, count=row["week_count"] or 0,
            quota=quota, joined=esc(joined_text(row)))
        report_id = await db.create_report(
            chat_id, user_id, title, name, row["week_count"] or 0, quota, text)

        delivered = False
        while recipient_idx < len(recipients):
            rcpt = recipients[recipient_idx]
            note = phrases.QUOTA_FALLBACK_NOTE if rcpt != owner_id else ""
            try:
                msg = await bot.send_message(rcpt, text + note, reply_markup=main_keyboard(report_id))
                await db.set_report_delivery(report_id, rcpt, msg.message_id)
                delivered = True
                break
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                logging.warning("Не удалось отправить отчёт пользователю %s: %s", rcpt, e)
                recipient_idx += 1
        if not delivered:
            await db.delete_report(report_id)
            return  # некому отправлять
        sent += 1
        await asyncio.sleep(0.4)  # лимиты Telegram

    if over and recipient_idx < len(recipients):
        try:
            await bot.send_message(
                recipients[recipient_idx],
                phrases.QUOTA_TRUNCATED.format(chat=esc(title), n=over, shown=sent))
        except Exception:
            pass


async def process_week(bot: Bot, db: Database, grace_cutoff: int):
    quota = get_weekly_quota()
    for chat_id in await db.get_group_chat_ids():
        try:
            await report_chat(bot, db, chat_id, quota, grace_cutoff)
        except Exception:
            logging.exception("Ошибка недельного отчёта для чата %s", chat_id)


async def weekly_loop(bot: Bot, db: Database):
    """Раз в 10 минут проверяет, не началась ли новая неделя. Состояние хранится в БД,
    поэтому пропущенный из-за перезапуска понедельник отработается при следующем запуске."""
    while True:
        try:
            await db.cleanup_expired_warns()
            week_start = current_week_start_ts()
            last = await db.get_meta("last_week")
            if last is None:
                # Первый запуск: первая (неполная) неделя без отчётов
                await db.set_meta("last_week", str(week_start))
                await db.set_meta("partial_first", "1")
                await db.reset_week_counts()
            elif week_start > int(last):
                partial = await db.get_meta("partial_first") == "1"
                missed_weeks = week_start - int(last) > WEEK_SECONDS + 3600
                if partial or missed_weeks:
                    logging.info("Неполная неделя — счётчики сбрасываются без отчёта.")
                else:
                    await process_week(bot, db, grace_cutoff=week_start - WEEK_SECONDS)
                await db.reset_week_counts()
                await db.set_meta("partial_first", "0")
                await db.set_meta("last_week", str(week_start))
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Ошибка в недельном цикле")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ---------- кнопки ----------

async def _finish_message(call: CallbackQuery, text: str, delete: bool = False):
    """Убирает кнопки: удаляет сообщение или заменяет его текстом-итогом."""
    if not call.message:
        return
    if delete:
        try:
            await call.message.delete()
            return
        except Exception:  # например, прошло больше 48 часов
            pass
    try:
        await call.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest:
        pass


async def _safe_dm(bot: Bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


@quota_router.callback_query(F.data.startswith("q:"))
async def on_quota_button(call: CallbackQuery, bot: Bot, db: Database):
    try:
        _, action, report_id_raw = call.data.split(":")
        report_id = int(report_id_raw)
    except ValueError:
        await call.answer()
        return

    report = await db.get_report(report_id)
    if not report or report["status"] != "pending":
        await call.answer(phrases.QUOTA_ALREADY, show_alert=True)
        if call.message:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
        return
    if call.from_user.id not in (report["recipient_id"], get_creator_id()):
        await call.answer(phrases.ERR_NO_PERMISSION, show_alert=True)
        return

    chat_id, user_id = report["chat_id"], report["user_id"]
    title = esc(report["chat_title"])
    who = user_link(user_id, report["user_name"])

    if action == "ign":
        delivered = await _safe_dm(bot, user_id, phrases.QUOTA_USER_IGNORED.format(
            chat=title, count=report["week_count"], quota=report["quota"]))
        await db.set_report_status(report_id, "ignored")
        await _finish_message(call, phrases.QUOTA_RES_IGNORE.format(user=who), delete=True)
        if delivered:
            await call.answer()
        else:
            await call.answer(phrases.QUOTA_DM_FAILED, show_alert=True)

    elif action == "wrn":
        try:
            current = await db.get_total_warns(chat_id, user_id)
            if current + 1 >= 3:
                await bot.ban_chat_member(chat_id, user_id)
                await db.reset_warns(chat_id, user_id)
                result = phrases.QUOTA_RES_WARN_BAN.format(user=who, chat=title)
                status = "warn_ban"
            else:
                total = await db.add_temp_warn(chat_id, user_id, int(time.time()) + WARN_DAYS * 86400)
                result = phrases.QUOTA_RES_WARN.format(user=who, total=total)
                status = "warned"
                await _safe_dm(bot, user_id, phrases.QUOTA_USER_WARNED.format(
                    chat=title, count=report["week_count"], quota=report["quota"]))
        except Exception as e:
            await call.answer(phrases.QUOTA_ACTION_FAILED.format(error=str(e)[:150]), show_alert=True)
            return
        await db.set_report_status(report_id, status)
        await _finish_message(call, f"{report['text']}\n\n{result}")
        await call.answer()

    elif action == "kck":
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)  # кик без вечного бана
        except Exception as e:
            await call.answer(phrases.QUOTA_ACTION_FAILED.format(error=str(e)[:150]), show_alert=True)
            return
        await db.set_report_status(report_id, "kicked")
        await _finish_message(call, f"{report['text']}\n\n{phrases.QUOTA_RES_KICK.format(user=who, chat=title)}")
        await call.answer()

    elif action == "e404":
        if call.message:
            await call.message.edit_text(
                phrases.QUOTA_CONFIRM.format(user=who, chat=title),
                reply_markup=confirm_keyboard(report_id))
        await call.answer()

    elif action == "no":
        if call.message:
            await call.message.edit_text(report["text"], reply_markup=main_keyboard(report_id))
        await call.answer()

    elif action == "yes":
        try:
            await bot.ban_chat_member(chat_id, user_id)
        except Exception as e:
            await call.answer(phrases.QUOTA_ACTION_FAILED.format(error=str(e)[:150]), show_alert=True)
            return
        await db.set_report_status(report_id, "banned")
        await _finish_message(call, f"{report['text']}\n\n{phrases.QUOTA_RES_BAN.format(user=who, chat=title)}")
        await call.answer()

    else:
        await call.answer()


# ---------- учёт вступлений и выходов ----------

@quota_router.message(F.new_chat_members)
async def on_new_members(message: Message, db: Database):
    ts = int(message.date.timestamp())
    for user in message.new_chat_members:
        if not user.is_bot:
            await db.record_join(message.chat.id, user.id, user.username, user.first_name, ts)


@quota_router.message(F.left_chat_member)
async def on_left_member(message: Message, db: Database):
    if message.left_chat_member and not message.left_chat_member.is_bot:
        await db.mark_left(message.chat.id, message.left_chat_member.id)


@quota_router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated, db: Database):
    """Ловит вступления без служебного сообщения (нужно, чтобы бот был админом группы)."""
    user = event.new_chat_member.user
    if user.is_bot:
        return
    old, new = event.old_chat_member.status, event.new_chat_member.status
    if new in ("left", "kicked"):
        await db.mark_left(event.chat.id, user.id)
    elif old in ("left", "kicked") and new in ("member", "restricted", "administrator", "creator"):
        await db.record_join(event.chat.id, user.id, user.username, user.first_name, int(event.date.timestamp()))
