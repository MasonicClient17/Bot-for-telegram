import asyncio
import random
import re
from datetime import datetime
from aiogram import Router, F, types, html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from config import CREATOR_ID, bot
from database import db_query
from utils import (
    check_access,
    get_user_tag,
    get_display_name,
    try_delete,
    schedule_sync
)

router = Router()

@router.message(F.text.lower().startswith("викторина"))
async def create_quiz_handler(m: types.Message):
    # Проверка тэга Vee
    user_tag = await get_user_tag(m.chat.id, m.from_user.id)
    if user_tag.lower() != "vee":
        return await m.answer("🌫️ Задавать викторины может только пользователь с тэгом <b>Vee</b>!")

    # Парсинг: викторина Текст вопроса? Ответы: [Правильный, Неправильный1, Неправильный2]
    match = re.match(r"^викторина\s+(.+?)\s+ответы:\s*\[(.+)\]$", m.text.strip(), re.I | re.S)
    if not match:
        return await m.answer(
            "🫗 <b>Формат команды:</b>\n"
            "<code>викторина [Вопрос]? Ответы: [Правильный ответ, Вариант2, Вариант3, Вариант4]</code>\n\n"
            "<i>Первым в скобках всегда указывается правильный ответ!</i>"
        )

    question = match.group(1).strip()
    raw_answers = [a.strip() for a in match.group(2).split(",") if a.strip()]

    if len(raw_answers) < 2:
        return await m.answer("🫗 Викторина должна содержать минимум 2 варианта ответа!")

    correct_answer = raw_answers[0]  # Первый ответ всегда правильный
    shuffled_answers = raw_answers.copy()
    random.shuffle(shuffled_answers)  # Перемешиваем кнопки

    # Сохраняем черновик викторины в БД
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = await db_query(
        "INSERT INTO quizzes (chat_id, message_id, creator_id, question, correct_answer, is_active, created_at) VALUES (?, 0, ?, ?, ?, 1, ?)",
        (m.chat.id, m.from_user.id, question, correct_answer, now_str),
        commit=True
    )

    # Получаем quiz_id
    quiz_res = await db_query("SELECT last_insert_rowid()", fetchone=True)
    quiz_id = quiz_res[0]

    # Строим инлайн-клавиатуру
    builder = InlineKeyboardBuilder()
    for idx, ans in enumerate(shuffled_answers):
        builder.button(
            text=ans,
            callback_data=f"quiz_ans:{quiz_id}:{idx}"
        )
    builder.adjust(1)

    # Запоминаем варианты ответа для кликбейта по индексам
    # Для этого сохраняем перемешанный массив в память через callback_data или временное хранение
    # Чтобы не перегружать callback_data (лимит 64 байта), зашифруем индексы/текст
    
    await try_delete(m)

    vee_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    msg_text = f"🌸 <b>Викторина от {html.quote(vee_name)}!</b>\n\n<b>{html.quote(question)}</b>"

    # Создаём клавиатуру со встроенными значениями вариантов
    kb_builder = InlineKeyboardBuilder()
    for ans in shuffled_answers:
        # Используем hash или короткий индекс
        is_corr = 1 if ans == correct_answer else 0
        # В callback передаем id викторины и флаг правильности (1 или 0)
        kb_builder.button(
            text=ans,
            callback_data=f"qans:{quiz_id}:{is_corr}"
        )
    kb_builder.adjust(1)

    sent_msg = await m.answer(msg_text, reply_markup=kb_builder.as_markup())

    # Обновляем message_id в БД
    await db_query("UPDATE quizzes SET message_id=? WHERE quiz_id=?", (sent_msg.message_id, quiz_id), commit=True)
    schedule_sync()

    # Запускаем фоновый таймер на 15 минут (900 секунд)
    asyncio.create_task(finish_quiz_after_delay(quiz_id, m.chat.id, sent_msg.message_id, 900))


@router.callback_query(F.data.startswith("qans:"))
async def process_quiz_answer(call: types.CallbackQuery):
    _, quiz_id_str, is_corr_str = call.data.split(":")
    quiz_id = int(quiz_id_str)
    is_correct = int(is_corr_str) == 1
    uid = call.from_user.id
    cid = call.message.chat.id

    # Проверяем, активна ли викторина
    quiz = await db_query("SELECT is_active, creator_id, question FROM quizzes WHERE quiz_id=?", (quiz_id,), fetchone=True)
    if not quiz or quiz[0] == 0:
        return await call.answer("🫗 Эта викторина уже завершена!", show_alert=True)

    creator_id, question = quiz[1], quiz[2]

    # Проверяем, не отвечал ли пользователь ранее
    already_answered = await db_query("SELECT is_correct FROM quiz_answers WHERE quiz_id=? AND user_id=?", (quiz_id, uid), fetchone=True)
    if already_answered:
        return await call.answer("🌸 Вы уже давали ответ на эту викторину!", show_alert=True)

    user_disp_name = await get_display_name(cid, uid, call.from_user.first_name)

    # Фиксируем ответ в БД
    await db_query("INSERT INTO quiz_answers VALUES (?,?,?)", (quiz_id, uid, 1 if is_correct else 0), commit=True)

    if is_correct:
        # Начисление 5 кассет ответившему
        await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + 5 WHERE chat_id=? AND user_id=?", (cid, uid), commit=True)
        await call.answer("Правильно!👏🏻 Вы получаете 5📼!", show_alert=True)

        # Уведомление Создателю в ЛС
        try:
            await bot.send_message(
                CREATOR_ID,
                f"✅ <b>Викторина:</b> {html.quote(question)}\n"
                f"Пользователь <b>{html.quote(user_disp_name)}</b> (ID: {uid}) ответил(а) <b>ПРАВИЛЬНО</b>!"
            )
        except TelegramAPIError:
            pass
    else:
        # Списание 5 кассет у ошибшегося (не ниже 0)
        user_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
        curr_tapes = (user_tapes_res[0] if user_tapes_res else 0) or 0
        penalty = min(curr_tapes, 5)

        await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (penalty, cid, uid), commit=True)
        
        # Перечисление проигранных кассет создателю викторины (Vee)
        await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + ? WHERE chat_id=? AND user_id=?", (penalty, cid, creator_id), commit=True)

        await call.answer("Неправильно!👎🏻 Вы потеряли 5📼!", show_alert=True)

        # Уведомление Создателю в ЛС
        try:
            await bot.send_message(
                CREATOR_ID,
                f"❌ <b>Викторина:</b> {html.quote(question)}\n"
                f"Пользователь <b>{html.quote(user_disp_name)}</b> (ID: {uid}) ответил(а) <b>НЕПРАВИЛЬНО</b>!"
            )
        except TelegramAPIError:
            pass

    schedule_sync()


async def finish_quiz_after_delay(quiz_id: int, chat_id: int, message_id: int, delay: int = 900):
    await asyncio.sleep(delay)

    # Проверяем статус викторины
    quiz = await db_query("SELECT is_active, creator_id FROM quizzes WHERE quiz_id=?", (quiz_id,), fetchone=True)
    if not quiz or quiz[0] == 0:
        return

    # Закрываем викторину
    await db_query("UPDATE quizzes SET is_active=0 WHERE quiz_id=?", (quiz_id,), commit=True)

    creator_id = quiz[1]
    vee_name = await get_display_name(chat_id, creator_id, "Vee")

    # Собираем список ответивших
    answers = await db_query("SELECT user_id, is_correct FROM quiz_answers WHERE quiz_id=?", (quiz_id,), fetchall=True) or []

    correct_users = []
    incorrect_users = []

    for uid, is_corr in answers:
        name = await get_display_name(chat_id, uid, f"ID:{uid}")
        if is_corr == 1:
            correct_users.append(f"• {html.quote(name)}")
        else:
            incorrect_users.append(f"• {html.quote(name)}")

    corr_text = "\n".join(correct_users) if correct_users else "<i>Никто</i>"
    incorr_text = "\n".join(incorrect_users) if incorrect_users else "<i>Никто</i>"

    final_msg = (
        f"🌸 <b>Викторина от {html.quote(vee_name)} окончена!</b>\n\n"
        f"<b>Ответившие правильно:</b>\n{corr_text}\n\n"
        f"<b>Ответившие неправильно:</b>\n{incorr_text}"
    )

    try:
        await bot.edit_message_text(
            text=final_msg,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None
        )
    except TelegramAPIError:
        pass

    schedule_sync()
  
