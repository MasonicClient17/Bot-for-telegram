from aiogram import Router
from handlers import moderation, social, economy, custom_cmds, norms, start

main_router = Router()
main_router.include_router(start.router)
# Сначала проверяем все специфичные команды и триггеры
main_router.include_router(moderation.router)
main_router.include_router(social.router)
main_router.include_router(economy.router)
main_router.include_router(custom_cmds.router)
main_router.include_router(norms.router)

# В самом конце обрабатываем профиль, сохранение и обычные сообщения чата

