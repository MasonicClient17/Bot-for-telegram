import math
import re
from aiogram import Router, F, types, html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from config import CREATOR_ID, bot
from database import db_query
from utils import (
    check_access,
    resolve_target,
    get_display_name,
    get_user_tag,
    try_delete,
    schedule_sync
)

router = Router()

# ==================== ПОСТАВКИ (DYLE) ====================

@router.message(F.text.lower().startswith(("доставлять", "доставляю")))
async def dyle_deliver_item(m: types.Message):
    # Только в общем чате/группе
    if m.chat.type == "private":
        return await m.answer("🫗 Эту команду нужно использовать в общем чате группы!")

    # Проверка тэга Dyle
    user_tag = await get_user_tag(m.chat.id, m.from_user.id)
    if user_tag.lower() != "dyle":
        return await m.answer("🌫️ Доставлять продукты для магазина может только поставщик с тэгом <b>Dyle</b>!")

    # Парсинг: доставлять [название] [количество] [цена]
    match = re.match(r"^(доставлять|доставляю)\s+(.+?)\s+(\d+)\s+(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer(
            "🫗 <b>Формат команды:</b>\n"
            "<code>доставлять [название] [количество] [цена за штуку]</code>"
        )

    item_name = match.group(2).strip()
    count = int(match.group(3))
    price = int(match.group(4))

    if count <= 0 or price <= 0:
        return await m.answer("🫗 Количество и цена должны быть больше 0!")

    # Расход трети цены товара у самого Dyle (за каждую штуку или за всю партию? По логике — треть от общей стоимости партии или цены штуки. Спишем треть от общей суммы поставки: count * price / 3)
    total_cost = count * price
    dyle_cost = math.ceil(total_cost / 3)

    dyle_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    dyle_tapes = (dyle_tapes_res[0] if dyle_tapes_res else 0) or 0

    if dyle_tapes < dyle_cost:
        return await m.answer(f"📼 У вас недостаточно кассет для закупки партии! Требуется (1/3 от стоимости): <b>{dyle_cost}</b> 📼 (у вас: {dyle_tapes} 📼).")

    # Списываем треть стоимости у Dyle
    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (dyle_cost, m.chat.id, m.from_user.id), commit=True)

    # Сохраняем поставку в базу
    await db_query(
        "INSERT INTO deliveries (chat_id, dyle_user_id, item_name, count, cost, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (m.chat.id, m.from_user.id, item_name, count, price),
        commit=True
    )

    schedule_sync()
    await try_delete(m)
    await m.answer(f"🌸 <b>{html.quote(item_name)}</b> успешно поставлено! (С вашего списано {dyle_cost} 📼 за организацию).")


# ==================== ЛИЧНЫЕ СООБЩЕНИЯ DANDY: СПИСОК ПОСТАВОК ====================

@router.message(F.text.lower() == "список поставок")
async def dandy_list_deliveries_private(m: types.Message):
    if m.chat.type != "private":
        return await m.answer("🫗 Эту команду нужно писать в личные сообщения боту!")

    # Ищем чаты, где пользователь является Dandy
    dandy_chats = await db_query("SELECT chat_id FROM user_tags WHERE LOWER(tag_name)='dandy' AND user_id=?", (m.from_user.id,), fetchall=True)
    if not dandy_chats:
        return await m.answer("🌫️ Эта команда доступна только торговцам с тэгом <b>Dandy</b>!")

    chat_id = dandy_chats[0][0]  # Берем первый чат, где он Dandy (или можно выводить со всех)

    deliveries = await db_query(
        "SELECT delivery_id, item_name, count, cost FROM deliveries WHERE chat_id=? ORDER BY delivery_id DESC",
        (chat_id,),
        fetchall=True
    )

    if not deliveries:
        return await m.answer("🫙 Актуальных поставок пока нет.")

    # Отправляем первую страницу (по 10 штук)
    await send_deliveries_page(m, deliveries, page=1)


async def send_deliveries_page(message_or_callback, deliveries, page=1):
    per_page = 10
    total_pages = math.ceil(len(deliveries) / per_page) or 1
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    page_items = deliveries[start_idx:start_idx + per_page]

    txt = f"✨ <b>Вот список поставок товаров [Стр. {page}/{total_pages}]:</b>\n\n"
    for idx, (del_id, name, cnt, cost) in enumerate(page_items, start_idx + 1):
        txt += f"{idx}. <b>{html.quote(name)}</b> — {cnt} шт. (Закупка: {cost} 📼)\n"

    # Инлайн кнопки пагинации
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="◀️ Назад", callback_data=f"dels_page:{page-1}")
    if page < total_pages:
        builder.button(text="Вперед ▶️", callback_data=f"dels_page:{page+1}")
    builder.adjust(2)

    markup = builder.as_markup() if (total_pages > 1) else None

    if isinstance(message_or_callback, types.CallbackQuery):
        try:
            await message_or_callback.message.edit_text(txt, reply_markup=markup)
        except TelegramAPIError:
            pass
    else:
        await message_or_callback.answer(txt, reply_markup=markup)


@router.callback_query(F.data.startswith("dels_page:"))
async def pagination_deliveries_callback(call: types.CallbackQuery):
    page = int(call.data.split(":")[1])
    dandy_chats = await db_query("SELECT chat_id FROM user_tags WHERE LOWER(tag_name)='dandy' AND user_id=?", (call.from_user.id,), fetchall=True)
    if not dandy_chats:
        return await call.answer("Доступ запрещен.", show_alert=True)
    
    chat_id = dandy_chats[0][0]
    deliveries = await db_query(
        "SELECT delivery_id, item_name, count, cost FROM deliveries WHERE chat_id=? ORDER BY delivery_id DESC",
        (chat_id,),
        fetchall=True
    )
    await send_deliveries_page(call, deliveries, page=page)
    await call.answer()


# ==================== ЛИЧНЫЕ СООБЩЕНИЯ DANDY: КУПИТЬ ПОСТАВКУ ====================

@router.message(F.text.lower().startswith("купить"))
async def dandy_buy_delivery_private(m: types.Message):
    if m.chat.type != "private":
        return  # В общих чатах работает старый buy_item_handler из магазина

    dandy_chats = await db_query("SELECT chat_id FROM user_tags WHERE LOWER(tag_name)='dandy' AND user_id=?", (m.from_user.id,), fetchall=True)
    if not dandy_chats:
        return  # Если не Dandy, игнорируем или обрабатываем в другом месте

    chat_id = dandy_chats[0][0]
    query = m.text[6:].strip()
    if not query:
        return await m.answer("🫗 Укажите номер товара из списка поставок или его название!")

    deliveries = await db_query(
        "SELECT delivery_id, item_name, count, cost FROM deliveries WHERE chat_id=? ORDER BY delivery_id DESC",
        (chat_id,),
        fetchall=True
    )

    target_del = None
    if query.isdigit():
        idx = int(query) - 1
        if 0 <= idx < len(deliveries):
            target_del = deliveries[idx]
    else:
        for d in deliveries:
            if d[1].lower() == query.lower():
                target_del = d
                break

    if not target_del:
        return await m.answer("🫙 Товар с таким номером или названием не найден в поставках!")

    del_id, item_name, count, cost = target_del
    total_price = count * cost

    # Проверяем баланс кассет Dandy
    dandy_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (chat_id, m.from_user.id), fetchone=True)
    dandy_tapes = (dandy_tapes_res[0] if dandy_tapes_res else 0) or 0

    if dandy_tapes < total_price:
        return await m.answer(f"📼 Недостаточно кассет для выкупа партии! Требуется: <b>{total_price}</b> 📼 (у вас: {dandy_tapes} 📼).")

    # Списываем кассеты у Dandy
    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (total_price, chat_id, m.from_user.id), commit=True)

    # Добавляем товар в инвентарь Dandy
    await db_query(
        "INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+excluded.count",
        (chat_id, m.from_user.id, item_name, count),
        commit=True
    )

    # Удаляем поставку из таблицы deliveries
    await db_query("DELETE FROM deliveries WHERE delivery_id=?", (del_id,), commit=True)

    schedule_sync()
    await m.answer(f"✨ Успешно куплено <b>{html.quote(item_name)}</b> ({count} шт.) за <b>{total_price}</b> 📼.")


# ==================== ПРОДАЖА ТОВАРОВ DANDY (В ОБЩЕМ ЧАТЕ) ====================

@router.message(F.text.lower().startswith(("продаю", "продать")))
async def dandy_sell_item_handler(m: types.Message):
    if m.chat.type == "private":
        return await m.answer("🫗 Эту команду нужно использовать в общем чате!")

    if (await get_user_tag(m.chat.id, m.from_user.id)).lower() != "dandy":
        return await m.answer("🌫️ Продавать товары через лавку может только Торговец (Dandy)!")

    # Формат: продаю [название] за [цена] (или продать [название] [цена])
    match = re.match(r"^(продаю|продать)\s+(.+?)\s+(?:за\s+)?(\d+)$", m.text.strip(), re.I)
    if not match:
        return await m.answer("🫗 Формат: <code>продаю [название] за [цена]</code>")

    item_name = match.group(2).strip()
    sell_price = int(match.group(3))

    # Ищем базовую цену: либо в master_items, либо проверяем по средней стоимости закупки из поставок
    master_item = await db_query("SELECT base_price FROM master_items WHERE (chat_id=? OR chat_id=0) AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), fetchone=True)
    
    if master_item:
        base_price = master_item[0]
    else:
        # Ищем по последней закупке
        del_item = await db_query("SELECT cost FROM deliveries WHERE chat_id=? AND LOWER(item_name)=LOWER(?) ORDER BY delivery_id DESC LIMIT 1", (m.chat.id, item_name), fetchone=True)
        if not del_item:
            return await m.answer(f"🌫️ Товар '{html.quote(item_name)}' не найден в базе поставок или мастер-предметов, установить цену невозможно!")
        base_price = del_item[0]

    # Лимиты: не более +50% и не меньше 50% от базовой цены (т.е. от 50% до 150%)
    min_p = int(base_price * 0.5)
    max_p = int(base_price * 1.5)

    if not (min_p <= sell_price <= max_p):
        return await m.answer(f"🌫️ Вы не можете поставить такую цену! Допустимая цена для '{html.quote(item_name)}' от {min_p} до {max_p} 📼 (база: {base_price} 📼).")

    # Добавляем в merchant_catalog
    await db_query("INSERT OR REPLACE INTO merchant_catalog (chat_id, item_name, price, is_master_item) VALUES (?,?,?,0)", (m.chat.id, item_name, sell_price), commit=True)
    
    schedule_sync()
    await try_delete(m)
    await m.answer(f"🛍 Торговец Dandy выставил на продажу: <b>{html.quote(item_name)}</b> за <b>{sell_price}</b> 📼")
    
