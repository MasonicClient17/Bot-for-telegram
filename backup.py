import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import FSInputFile

from db import Database


async def send_backup(bot: Bot, db: Database, chat_id: int, caption: str, pin: bool = True):
    """Делает снимок БД, отправляет в чат-хранилище и закрепляет (чтобы потом восстановить)."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"backup_{stamp}.db"
    snapshot = os.path.join(tempfile.gettempdir(), filename)
    await db.make_snapshot(snapshot)
    try:
        msg = await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(snapshot, filename=filename),
            caption=caption,
        )
    finally:
        if os.path.exists(snapshot):
            os.remove(snapshot)

    if pin:
        try:
            old = (await bot.get_chat(chat_id)).pinned_message
            await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
            if old and old.message_id != msg.message_id:
                await bot.unpin_chat_message(chat_id, old.message_id)
        except Exception as e:
            logging.warning("Не удалось закрепить бэкап (нужны права админа с правом закрепа): %s", e)
    return msg


async def restore_from_pinned(bot: Bot, chat_id: int, target_path: str) -> bool:
    """Скачивает закреплённый в чате-хранилище .db и кладёт его на место target_path."""
    chat = await bot.get_chat(chat_id)
    pinned = chat.pinned_message
    if not pinned or not pinned.document:
        logging.warning("В хранилище нет закреплённого файла с бэкапом — восстанавливать нечего.")
        return False

    tmp_path = target_path + ".restore"
    await bot.download(pinned.document.file_id, destination=tmp_path)
    try:
        check = sqlite3.connect(tmp_path)
        try:
            ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            check.close()
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        os.remove(tmp_path)
        logging.error("Закреплённый файл повреждён или не является базой SQLite.")
        return False

    os.replace(tmp_path, target_path)
    return True
  
