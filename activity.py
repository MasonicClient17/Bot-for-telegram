"""Подсчёт сообщений: ЕДИНСТВЕННАЯ точка, где растут счётчики.

Middleware срабатывает один раз на каждое сообщение — раньше любых хендлеров и фильтров — и сразу
записывает его в базу (общий и недельный счётчик одной командой). Все остальные части бота
(профиль, «актив», «/неактив», отчёты о норме, «/чистка») только ЧИТАЮТ эти значения из базы.
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from db import Database
from utils import is_group

# Какие сообщения считаются (служебные — вступление, закреп, смена названия и т.п. — не считаются)
COUNTED_CONTENT_TYPES = {
    "text", "photo", "video", "animation", "audio", "voice", "video_note", "document",
    "sticker", "poll", "contact", "location", "venue", "dice", "game",
}
TELEGRAM_SERVICE_USER_ID = 777000   # автопересылки из связанного канала


def is_countable(message: Message) -> bool:
    user = message.from_user
    if not is_group(message) or user is None or user.is_bot or user.id == TELEGRAM_SERVICE_USER_ID:
        return False
    content_type = getattr(message.content_type, "value", message.content_type)
    return content_type in COUNTED_CONTENT_TYPES


class ActivityMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
                       event: Message, data: dict[str, Any]) -> Any:
        if is_countable(event):
            try:
                user = event.from_user
                await self.db.record_message(event.chat.id, user.id, user.username, user.first_name)
            except Exception:  # сбой подсчёта не должен ломать обработку команд
                logging.exception("Не удалось записать сообщение в статистику")
        return await handler(event, data)
