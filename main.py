import asyncio
import logging
from config import bot, dp
from database import init_db, backup_to_telegram
from handlers import main_router

async def on_startup():
    logging.info("🌌 Инициализация базы данных...")
    await init_db()
    logging.info("🌃 Бот успешно запущен и готов к работе!")

async def on_shutdown():
    logging.info("📼 Создание финального бэкапа перед выключением...")
    await backup_to_telegram()
    logging.info("🌫️ Бот остановлен.")

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    dp.include_router(main_router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
        
