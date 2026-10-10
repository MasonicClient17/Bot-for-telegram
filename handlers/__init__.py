from aiogram import Router
from . import profile, shop, features, admin, custom_rp

router = Router()
router.include_router(profile.router)
router.include_router(shop.router)
router.include_router(features.router)
router.include_router(admin.router)
router.include_router(custom_rp.router)
