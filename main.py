import asyncio
import logging
import os
import signal
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from db import Database, DB_NAME
from handlers import router, get_storage_chat_id
import phrases

load_dotenv()

bot_token = os.getenv("BOT_TOKEN")
if not bot_token:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")
    
bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
db = Database(DB_NAME)

async def send_shutdown_backup():
    storage_id = get_storage_chat_id()
    if storage_id and os.path.exists(DB_NAME):
        try:
            await db.conn.commit()
            await bot.send_document(
                chat_id=storage_id,
                document=types.FSInputFile(DB_NAME),
                caption=phrases.SHUTDOWN_BACKUP_CAPTION
            )
            logging.info("Автобэкап базы данных успешно отправлен в STORAGE_CHAT_ID.")
        except Exception as e:
            logging.error(f"Не удалось отправить автобэкап при выключении: {e}")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    
    await db.connect()
    await db.init_db()

    dp.include_router(router)
    
    # Передаем объект базы данных в контекст хэндлеров через middleware/workflow_data
    dp['db'] = db

    # Настройка сигналов graceful shutdown для Railway / Docker (SIGTERM, SIGINT)
    loop = asyncio.get_running_loop()
    
    def shutdown_handler():
        logging.info("Получен сигнал завершения работы (SIGTERM/SIGINT). Создаем бэкап...")
        asyncio.create_task(shutdown_sequence())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            # Windows не всегда поддерживает add_signal_handler для SIGTERM
            pass

    async def shutdown_sequence():
        await send_shutdown_backup()
        await db.close()
        await bot.session.close()
        logging.info("Бот успешно остановлен.")
        loop.stop()

    logging.info("Бот запущен и готов к работе.")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот принудительно остановлен пользователем.")
    
