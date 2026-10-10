import asyncio
import logging
from config import dp, bot, STORAGE_CHAT_ID
from database import init_db, backup_to_telegram, restore_from_telegram
from handlers import router as main_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def periodic_backup():
    while True:
        await asyncio.sleep(21600) # Каждые 6 часов
        await backup_to_telegram()

async def main():
    await init_db()
    if STORAGE_CHAT_ID:
        await restore_from_telegram()
    
    dp.include_router(main_router)
    
    asyncio.create_task(periodic_backup())
    
    logging.info("🌿 Бот запущен в новом уютном стиле!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
