from aiogram import Router
from handlers import norms, start, moderation, social, economy, custom_cmds

main_router = Router()
main_router.include_router(norms.router)
main_router.include_router(start.router)
main_router.include_router(moderation.router)
main_router.include_router(social.router)
main_router.include_router(economy.router)
main_router.include_router(custom_cmds.router)
