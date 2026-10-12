import re
from aiogram import Router, F, types, html
from aiogram.exceptions import TelegramAPIError
from config import CREATOR_ID, bot
from database import db_query
from utils import check_access, resolve_target, get_display_name, get_user_tag, try_delete, schedule_sync

router = Router()

@router.message(F.text.startswith("+вещи"))
async def give_item_admin(m: types.Message):
    if not await check_access(m, "+вещь"): return
    text = m.text[6:].strip()
    tid, tname, tstr = await resolve_target(m)
    if not tid: return await m.answer("🫗 Укажите пользователя (ответом или через @/ID)!")

    clean_item = text
    if tstr and (tstr.startswith("@") or tstr.isdigit()):
        clean_item = re.sub(re.escape(tstr), "", clean_item, flags=re.I).strip()

    words = clean_item.split()
    count = int(words[-1]) if words and words[-1].isdigit() else 1
    item_name = " ".join(words[:-1]).strip() if words and words[-1].isdigit() else clean_item.strip()
    if not item_name: return await m.answer("🫗 Укажите название вещи! Пример: <code>+вещи [название] [кол-во] [юзер]</code>")

    await db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,?) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+excluded.count", (m.chat.id, tid, item_name, count), commit=True)
    admin_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    target_name = await get_display_name(m.chat.id, tid, tname)

    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 <b>{html.quote(admin_name)}</b> выгрузил(а) из инвентаря <b>{html.quote(item_name)}</b> ({count} шт.) и передал(а) <b>{html.quote(target_name)}</b>.")

@router.message(F.text.lower().startswith(("+вещь", "создать предмет")))
async def master_add_item_handler(m: types.Message):
    if not await check_access(m, "+вещь"): return
    match = re.match(r"^\+вещь\s+(.+?)\s+(\d+)$", m.text.strip(), re.I)
    if not match: return await m.answer("🫗 Формат: <code>+вещь [название] [цена]</code>")
    item_name, price = match.group(1).strip(), int(match.group(2))
    await db_query("INSERT OR REPLACE INTO master_items (chat_id, item_name, base_price) VALUES (?,?,?)", (m.chat.id, item_name, price), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 Создана вещь 4 уровня: <b>{html.quote(item_name)}</b> (Базовая цена: {price} 📼)")

@router.message(F.text.lower().startswith("создать вещь"))
async def merchant_create_item_handler(m: types.Message):
    if (await get_user_tag(m.chat.id, m.from_user.id)).lower() != "dandy":
        return await m.answer("🌫️ Создавать товары для магазина может только Торговец (Dandy)!")
    match = re.match(r"^создать вещь\s+(.+?)\s+(\d+)$", m.text.strip(), re.I)
    if not match: return await m.answer("🫗 Формат: <code>создать вещь [название] [цена]</code>")
    item_name, price = match.group(1).strip(), int(match.group(2))
    
    master_item = await db_query("SELECT base_price FROM master_items WHERE (chat_id=? OR chat_id=0) AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), fetchone=True)
    is_master = 0
    if master_item:
        is_master = 1
        base_p = master_item[0]
        if not (int(base_p * 0.8) <= price <= int(base_p * 1.2)):
            return await m.answer(f"🌫️ Торговец может продавать вещь 4 уровня '{html.quote(item_name)}' только в пределах ±20% от базовой цены ({base_p} 📼)!\nДопустимая цена: от {int(base_p * 0.8)} до {int(base_p * 1.2)} 📼.")

    await db_query("INSERT OR REPLACE INTO merchant_catalog (chat_id, item_name, price, is_master_item) VALUES (?,?,?,?)", (m.chat.id, item_name, price, is_master), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🛍 Торговец Dandy выставил на продажу: <b>{html.quote(item_name)}</b> за <b>{price}</b> 📼")

@router.message(F.text.lower().startswith("удалить вещь"))
async def merchant_delete_item_handler(m: types.Message):
    if (await get_user_tag(m.chat.id, m.from_user.id)).lower() != "dandy":
        return await m.answer("🌫️ Удалять товары может только Торговец (Dandy)!")
    item_name = m.text[12:].strip()
    await db_query("DELETE FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), commit=True)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🛍 Товар <b>{html.quote(item_name)}</b> убран из магазина.")

@router.message(F.text.lower().in_(["список товаров", "товары", "магазин"]))
async def show_merchant_shop_handler(m: types.Message):
    if not await check_access(m, "список товаров"): return
    items = await db_query("SELECT item_name, price FROM merchant_catalog WHERE chat_id=?", (m.chat.id,), fetchall=True)
    if not items: return await m.answer("🫙 У Торговца Dandy пока нет товаров на продажу.")
    txt = "🛍 <b>Лавка торговца Dandy:</b>\n\n" + "\n".join([f"• <b>{html.quote(n)}</b> — {p} 📼" for n, p in items]) + "\n\nДля покупки используйте команду: <code>купить [название]</code>"
    await try_delete(m); await m.answer(txt)

@router.message(F.text.lower().startswith("купить"))
async def buy_item_handler(m: types.Message):
    if not await check_access(m, "купить"): return
    item_name = m.text[6:].strip()
    if not item_name: return await m.answer("🫗 Использование: <code>купить [название вещи]</code>")

    item = await db_query("SELECT item_name, price FROM merchant_catalog WHERE chat_id=? AND LOWER(item_name)=LOWER(?)", (m.chat.id, item_name), fetchone=True)
    if not item: return await m.answer("🫙 Такого товара нет у торговца!")

    real_iname, price = item
    user_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (m.chat.id, m.from_user.id), fetchone=True)
    user_tapes = user_tapes_res[0] if user_tapes_res else 0
    if user_tapes < price: return await m.answer(f"📼 Недостаточно кассет! Требуется: <b>{price}</b> 📼, у вас: <b>{user_tapes}</b> 📼.")

    dandy_res = await db_query("SELECT user_id FROM user_tags WHERE chat_id=? AND LOWER(tag_name)='dandy'", (m.chat.id,), fetchone=True)
    await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (price, m.chat.id, m.from_user.id), commit=True)
    if dandy_res:
        await db_query("INSERT INTO users (chat_id, user_id, tapes) VALUES (?,?,?) ON CONFLICT(chat_id, user_id) DO UPDATE SET tapes=COALESCE(tapes,0)+excluded.tapes", (m.chat.id, dandy_res[0], price), commit=True)

    await db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+1", (m.chat.id, m.from_user.id, real_iname), commit=True)
    buyer_nick = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    schedule_sync(); await try_delete(m)
    await m.answer(f"✨ <b>{html.quote(buyer_nick)}</b> приобретает <b>{html.quote(real_iname)}</b> у Dandy за <b>{price}</b> 📼!")

@router.message(F.text.lower().in_(["мои вещи", "инвентарь"]))
async def show_inventory_handler(m: types.Message):
    if not await check_access(m, "мои вещи"): return
    items = await db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND count > 0", (m.chat.id, m.from_user.id), fetchall=True)
    uname = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    if not items: return await m.answer(f"🫙 В карманах у <b>{html.quote(uname)}</b> пока пусто.")
    txt = f"🎒 <b>Инвентарь {html.quote(uname)}:</b>\n\n" + "\n".join([f"• <b>{html.quote(n)}</b> — {c} шт." for n, c in items])
    await try_delete(m); await m.answer(txt)

@router.message(F.text.lower().startswith("вещь"))
async def transfer_item_handler(m: types.Message):
    if not await check_access(m, "вещь"): return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("🌸 Ответьте на сообщение пользователя, которому хотите передать вещь!")

    item_name = m.text[4:].strip()
    if not item_name: return await m.answer("🫗 Укажите название вещи! Пример: <code>вещь [название]</code>")

    inv_item = await db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?) AND count > 0", (m.chat.id, m.from_user.id, item_name), fetchone=True)
    if not inv_item: return await m.answer("🫙 У вас нет этой вещи!")

    real_iname = inv_item[0]
    tid = m.reply_to_message.from_user.id
    if tid == m.from_user.id: return await m.answer("🫗 Нельзя передавать вещи самому себе!")

    await db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND item_name=?", (m.chat.id, m.from_user.id, real_iname), commit=True)
    await db_query("INSERT INTO inventory (chat_id, user_id, item_name, count) VALUES (?,?,?,1) ON CONFLICT(chat_id, user_id, item_name) DO UPDATE SET count=count+1", (m.chat.id, tid, real_iname), commit=True)

    sender_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    receiver_name = await get_display_name(m.chat.id, tid, m.reply_to_message.from_user.first_name)
    schedule_sync(); await try_delete(m)
    await m.answer(f"🌸 <b>{html.quote(sender_name)}</b> передал(а) вещь <b>{html.quote(real_iname)}</b> пользователю <b>{html.quote(receiver_name)}</b>.")

@router.message(F.text.lower().startswith("использовать"))
async def use_item_handler(m: types.Message):
    if not await check_access(m, "использовать"): return
    item_name = m.text[12:].strip()
    inv_item = await db_query("SELECT item_name, count FROM inventory WHERE chat_id=? AND user_id=? AND LOWER(item_name)=LOWER(?) AND count > 0", (m.chat.id, m.from_user.id, item_name), fetchone=True)
    if not inv_item: return await m.answer("🫙 У вас нет такой вещи в инвентаре!")

    real_iname = inv_item[0]
    uname = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)

    if real_iname.lower() == "освобождение от нормы":
        await db_query("UPDATE inventory SET count = count - 1 WHERE chat_id=? AND user_id=? AND item_name=?", (m.chat.id, m.from_user.id, real_iname), commit=True)
        try:
            await bot.send_message(CREATOR_ID, f"📜 <b>Уведомление об Освобождении от нормы:</b>\nПользователь <b>{html.quote(uname)}</b> (ID: {m.from_user.id}) применил вещь 'Освобождение от нормы' в чате {html.quote(m.chat.title or str(m.chat.id))}!")
            await m.answer(f"✨ <b>{html.quote(uname)}</b> использовал(а) <b>Освобождение от нормы</b>! Создатель группы получил уведомление в ЛС.")
        except TelegramAPIError as e:
            await m.answer(f"✨ <b>{html.quote(uname)}</b> использовал(а) <b>Освобождение от нормы</b>! (Не удалось отправить ЛС Создателю: {e})")
        schedule_sync(); await try_delete(m)
        return

    await m.answer(f"🫗 Предмет <b>{html.quote(real_iname)}</b> пока не имеет встроенной активации.")
  
