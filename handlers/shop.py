import re
from aiogram import Router, F, types, html
from database import db_query
from utils import get_user_tag, get_display_name, try_delete, schedule_sync

router = Router()

@router.message(F.text.lower().startswith(("продаю", "продать")))
async def free_sell_item_handler(m: types.Message):
    if m.chat.type == "private":
        return
    user_tag = (await get_user_tag(m.chat.id, m.from_user.id)).lower()
    if user_tag not in ["dandy", "dyle"]:
        return await m.answer("🌿 Продавать вещи могут только участники с тэгами Dandy или Dyle!")

    match = re.match(r"^(продаю|продать)\s+(.+?)\s+(?:за\s+)?(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer("☕ Формат: <code>продать [название] за [цена]</code>")

    item_name = match.group(2).strip()
    price = int(match.group(3))

    await db_query("INSERT OR REPLACE INTO merchant_catalog (chat_id, item_name, price) VALUES (?, ?, ?)", (m.chat.id, item_name, price), commit=True)
    schedule_sync()
    await try_delete(m)
    
    seller_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    await m.answer(f"🛍 <b>{html.quote(seller_name)}</b> выставил на продажу:\n✨ <b>{html.quote(item_name)}</b> за <b>{price}</b> 📼\n\n💬 <i>Напишите «купить {html.quote(item_name)}»</i>")

@router.message(F.text.lower().startswith(("купить", "покупаю")))
async def buy_item_handler(m: types.Message):
    if m.chat.type == "private":
        return
    query = m.text[6:].strip() if m.text.lower().startswith("купить") else m.text[7:].strip()
    if not query:
        return await m.answer("☕ Укажите название вещи!")

    item_data = await db_query("SELECT price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, query), fetchone=True)
    if not item_data:
        return await m.answer(f"🌿 Вещь «{html.quote(query)}» не найдена в продаже.")

    price = item_data[0]
    buyer_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    tapes = (buyer_res[0] if buyer_res else 0) or 0

    if tapes < price:
        return await m.answer(f"📼 Недостаточно кассет! Нужно: {price} 📼 (у вас: {tapes}).")

    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (price, m.chat.id, m.from_user.id), commit=True)
    await db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?, ?, ?, 1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count = count + 1", (m.chat.id, m.from_user.id, query), commit=True)
    await db_query("DELETE FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, query), commit=True)
    
    await try_delete(m)
    buyer_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    await m.answer(f"🎉 <b>{html.quote(buyer_name)}</b> приобрел(а) <b>{html.quote(query)}</b> за {price} 📼!")

# Дарение вещей
@router.message(F.text.lower().startswith(("подарить", "отдать")))
async def give_item_handler(m: types.Message):
    if m.chat.type == "private" or not m.reply_to_message:
        return await m.answer("☕ Ответьте на сообщение участника, которому хотите подарить вещь!")
    
    parts = m.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("☕ Укажите название вещи для подарка (например: <code>подарить чашку чая</code>)")
    
    item_name = parts[1].strip()
    target_user = m.reply_to_message.from_user

    # Проверяем наличие у дарителя
    inv = await db_query("SELECT count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, m.from_user.id, item_name), fetchone=True)
    if not inv or inv[0] <= 0:
        return await m.answer(f"🌿 У вас нет вещи «{html.quote(item_name)}» в инвентаре.")

    # Пересчитываем
    await db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, m.from_user.id, item_name), commit=True)
    await db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?, ?, ?, 1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count = count + 1", (m.chat.id, target_user.id, item_name), commit=True)
    
    await try_delete(m)
    giver_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    receiver_name = await get_display_name(m.chat.id, target_user.id, target_user.first_name)
    await m.answer(f"🎁 <b>{html.quote(giver_name)}</b> подарил(а) <b>{html.quote(receiver_name)}</b> вещь: <b>{html.quote(item_name)}</b>!")
    
