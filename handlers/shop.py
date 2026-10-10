import re
from aiogram import Router, F, types, html
from aiogram.exceptions import TelegramAPIError

from database import db_query
from utils import (
    get_user_tag,
    get_display_name,
    try_delete,
    schedule_sync
)

router = Router()

# ==================== СВОБОДНАЯ ПРОДАЖА (DANDY & DYLE) ====================

@router.message(F.text.lower().startswith(("продаю", "продать")))
async def free_sell_item_handler(m: types.Message):
    if m.chat.type == "private":
        return await m.answer("🫗 Эту команду нужно использовать в общем чате!")

    # Проверяем, есть ли у пользователя тэг Dandy или Dyle
    user_tag = (await get_user_tag(m.chat.id, m.from_user.id)).lower()
    if user_tag not in ["dandy", "dyle"]:
        return await m.answer("🌫️ Продавать товары могут только участники с тэгами <b>Dandy</b> или <b>Dyle</b>!")

    # Формат: продаю [название] за [число] (или продать [название] [число])
    match = re.match(r"^(продаю|продать)\s+(.+?)\s+(?:за\s+)?(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer("🫗 <b>Формат:</b> <code>продать [название] за [цена]</code>")

    item_name = match.group(2).strip()
    price = int(match.group(3))

    if price < 0:
        return await m.answer("🫗 Цена не может быть отрицательной!")

    # Выставляем в общую лавку (merchant_catalog) без каких-либо лимитов и налогов
    await db_query(
        "INSERT OR REPLACE INTO merchant_catalog (chat_id, item_name, price, is_master_item) VALUES (?, ?, ?, 0)",
        (m.chat.id, item_name, price),
        commit=True
    )
    
    schedule_sync()
    await try_delete(m)
    
    seller_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    role_title = "Dandy" if user_tag == "dandy" else "Dyle"
    
    await m.answer(
        f"🛍 <b>{role_title} {html.quote(seller_name)}</b> выставил на продажу:\n"
        f"✨ <b>{html.quote(item_name)}</b> за <b>{price}</b> 📼\n\n"
        f"<i>Напишите «купить {html.quote(item_name)}», чтобы приобрести!</i>"
    )


# ==================== ПОКУПКА ВЕЩЕЙ ИЗ МАГАЗИНА ====================

@router.message(F.text.lower().startswith(("купить", "покупаю")))
async def buy_item_handler(m: types.Message):
    if m.chat.type == "private":
        return await m.answer("🫗 Покупать вещи нужно в общем чате группы!")

    query = m.text[6:].strip() if m.text.lower().startswith("купить") else m.text[7:].strip()
    
    if not query and m.reply_to_message:
        rep_text = m.reply_to_message.text or m.reply_to_message.caption or ""
        match_item = re.search(r"✨\s+<b>(.+?)<\/b>", rep_text)
        if match_item:
            query = match_item.group(1)

    if not query:
        return await m.answer("🫗 Укажите название вещи или ответьте на товар в чате!")

    # Ищем товар в каталоге
    item_row = await db_query(
        "SELECT item_price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", # исправим колонку price
        # Поправим запрос под реальную структуру price:
        # SELECT price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)
        fetchall=False
    )
    
    # Сделаем точный и надежный запрос к merchant_catalog:
    item_data = await db_query(
        "SELECT price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)",
        (m.chat.id, query),
        fetchone=True
    )

    if not item_data:
        return await m.answer(f"🫙 Вещь «{html.quote(query)}» не найдена в продаже!")

    price = item_data[0]

    # Проверяем баланс покупателя
    buyer_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    buyer_tapes = (buyer_res[0] if buyer_res else 0) or 0

    if buyer_tapes < price:
        return await m.answer(f"📼 Недостаточно кассет! Требуется: <b>{price}</b> 📼 (у вас: {buyer_tapes} 📼).")

    # Списываем кассеты у покупателя
    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (price, m.chat.id, m.from_user.id), commit=True)

    # Добавляем вещь в инвентарь покупателя
    await db_query(
        "INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?, ?, ?, 1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count = count + 1",
        (m.chat.id, m.from_user.id, query),
        commit=True
    )

    # Удаляем товар из активного каталога магазина после покупки
    await db_query("DELETE FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, query), commit=True)

    schedule_sync()
    await try_delete(m)

    buyer_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    await m.answer(f"🎉 <b>{html.quote(buyer_name)}</b> успешно купил(а) <b>{html.quote(query)}</b> за <b>{price}</b> 📼! Вещь добавлена в инвентарь.")
    
