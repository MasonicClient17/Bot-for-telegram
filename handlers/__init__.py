from aiogram import Router
from . import welcome, profile, admin, shop, marriages, rules, tags_nicks, custom_rp

router = Router()

router.include_router(welcome.router)
router.include_router(profile.router)
router.include_router(admin.router)
router.include_router(shop.router)
router.include_router(marriages.router)
router.include_router(rules.router)
router.include_router(tags_nicks.router)
router.include_router(custom_rp.router)  # Этот роутер со стандартным F.text всегда идет ПОСЛЕДНИМ!
