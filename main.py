import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import phrases
from backup import restore_from_pinned, send_backup
from config import DB_NAME, get_backup_interval_hours, get_storage_chat_id
from db import Database
from handlers import router

bot_token = os.getenv("BOT_TOKEN")
if not bot_token:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")

bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
db = Database(DB_NAME)


async def backup_to_storage(caption: str):
    storage_id = get_storage_chat_id()
    if not storage_id:
        logging.warning("STORAGE_CHAT_ID не задан — бэкап пропущен.")
        return
    try:
        await send_backup(bot, db, storage_id, caption)
        logging.info("Бэкап отправлен в STORAGE_CHAT_ID.")
    except Exception:
        logging.exception("Не удалось отправить бэкап в STORAGE_CHAT_ID")


async def periodic_backup(hours: float):
    while True:
        await asyncio.sleep(hours * 3600)
        await backup_to_storage(phrases.PERIODIC_BACKUP_CAPTION)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Файловая система Railway временная: если БД пропала (новый деплой без Volume),
    # пробуем достать последний закреплённый бэкап из чата-хранилища.
    storage_id = get_storage_chat_id()
    if storage_id and not os.path.exists(DB_NAME):
        try:
            if await restore_from_pinned(bot, storage_id, DB_NAME):
                logging.info("База восстановлена из закреплённого бэкапа.")
        except Exception:
            logging.exception("Не удалось восстановить базу из хранилища")

    await db.connect()
    await db.init_db()

    dp.include_router(router)
    dp["db"] = db

    backup_task = None
    interval = get_backup_interval_hours()
    if storage_id and interval > 0:
        backup_task = asyncio.create_task(periodic_backup(interval))

    logging.info("Бот запущен и готов к работе.")
    try:
        # aiogram сам ставит обработчики SIGTERM/SIGINT и корректно завершает polling
        # (свои loop.add_signal_handler он всё равно перезаписывает). Бэкап делаем ПОСЛЕ.
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        if backup_task:
            backup_task.cancel()
        logging.info("Polling остановлен. Создаём финальный бэкап...")
        try:
            await asyncio.wait_for(backup_to_storage(phrases.SHUTDOWN_BACKUP_CAPTION), timeout=25)
        except asyncio.TimeoutError:
            logging.error("Финальный бэкап не уложился в таймаут.")
        await db.close()
        await bot.session.close()
        logging.info("Бот успешно остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
