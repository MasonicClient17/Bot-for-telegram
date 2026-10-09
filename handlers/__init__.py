from aiogram import Router
from . import welcome, profile, admin, shop, marriages, rules, tags_nicks, quizzes, custom_rp

router = Router()

router.include_router(welcome.router)
router.include_router(profile.router)
router.include_router(admin.router)
router.include_router(shop.router)
router.include_router(marriages.router)
router.include_router(rules.router)
router.include_router(tags_nicks.router)
router.include_router(quizzes.router)
router.include_router(custom_rp.router)  # Обязательно идет ПОСЛЕДНИМ!
