from aiogram import Router
from . import (
    profile, 
    shop, 
    features, 
    admin, 
    custom_rp, 
    rules, 
    tags_nicks, 
    quizzes, 
    marriages
)

router = Router()
router.include_router(profile.router)
router.include_router(shop.router)
router.include_router(features.router)
router.include_router(admin.router)
router.include_router(custom_rp.router)
router.include_router(rules.router)
router.include_router(tags_nicks.router)
router.include_router(quizzes.router)
router.include_router(marriages.router)
