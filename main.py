import asyncio
import logging
from config import bot, dp
from database import init_db, restore_from_telegram, backup_to_telegram
from handlers import router as main_router

# Регистрируем главную группу роутеров
dp.include_router(main_router)

async def main():
    logging.info("⚙ Инициализация БД...")
    await init_db()
    logging.info("🚀 Восстановление из Telegram...")
    await restore_from_telegram()
    logging.info("🧪 Отправка автобэкапа...")
    await backup_to_telegram()
    logging.info("🌸 Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
