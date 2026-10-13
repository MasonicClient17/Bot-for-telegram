
import re
import random
asyncio_module = __import__('asyncio')
from datetime import datetime
from aiogram import Router, F, types
from aiogram.handler import SkipHandler
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import bot
from database import db_query
from utils import is_authorized_chat, try_delete, get_text

router = Router()

@router.message(F.text)
async def create_quiz_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        raise SkipHandler()

    text = m.text.strip()
    if not text.lower().startswith("викторина"):
        raise SkipHandler()
    ...
    
