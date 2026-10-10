import random
import re
import logging
from aiogram import Router, F, types, html
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from config import bot
from database import db_query
from utils import (
    get_user_tag,
    get_display_name,
    try_delete,
    schedule_sync
)

router = Router()

@router.message(F.text.lower().startswith("викторина"))
async def create_quiz_handler(m: types.Message):
    logging.info(f"[QUIZ_LOG] Пользователь {m.from_user.id} вызвал команду создания викторины в чате {m.chat.id}. Текст: {m.text}")
    
    # Проверка тэга Vee
    user_tag = await get_user_tag(m.chat.id, m.from_user.id)
    logging.info(f"[QUIZ_LOG] Тэг пользователя {m.from_user.id}: '{user_tag}'")
    
    if user_tag.lower() != "vee":
        logging.warning(f"[QUIZ_LOG] Отказано в создании викторины: у пользователя нет тэга Vee.")
        return await m.answer("🌫️ Задавать викторины может только пользователь с тэгом <b>Vee</b>!")

    match = re.match(r"^викторина\s+(.+?)\s+ответы:\s*\[(.+)\]$", m.text.strip(), re.I | re.S)
    if not match:
        logging.warning(f"[QUIZ_LOG] Ошибка парсинга аргументов викторины.")
        return await m.answer(
            "🫗 <b>Формат команды:</b>\n"
            "<code>викторина [Вопрос]? Ответы: [Правильный ответ; Вариант 2; Вариант 3]</code>\n\n"
            "<i>Варианты разделяются точкой с запятой (;). Первый ответ — правильный!</i>"
        )

    question = match.group(1).strip()
    raw_answers = [a.strip() for a in match.group(2).split(";") if a.strip()]
    logging.info(f"[QUIZ_LOG] Распознан вопрос: '{question}', вариантов ответа: {len(raw_answers)}")

    if len(raw_answers) < 2:
        return await m.answer("🫗 Викторина должна содержать минимум 2 варианта ответа, разделенных точкой с запятой (;).")

    correct_answer = raw_answers[0]
    shuffled_answers = raw_answers.copy()
    random.shuffle(shuffled_answers)

    # Сохраняем в БД
    try:
        await db_query(
            "INSERT INTO quizzes (chat_id, message_id, creator_id, question, correct_answer, is_active, created_at) VALUES (?, 0, ?, ?, ?, 1, datetime('now'))",
            (m.chat.id, m.from_user.id, question, correct_answer),
            commit=True
        )
        quiz_res = await db_query("SELECT last_insert_rowid()", fetchone=True)
        quiz_id = quiz_res[0]
        logging.info(f"[QUIZ_LOG] Викторина успешно записана в БД с ID: {quiz_id}")
    except Exception as e:
        logging.error(f"[QUIZ_LOG ERROR] Ошибка записи викторины в БД: {e}")
        return await m.answer("👁️ Произошла ошибка при сохранении викторины в базу данных.")

    await try_delete(m)

    vee_name = await get_display_name(m.chat.id, m.from_user.id, m.from_user.first_name)
    msg_text = f"🌸 <b>Викторина от {html.quote(vee_name)}!</b>\n\n<b>{html.quote(question)}</b>\n\n<i>Для завершения автор может ответить на это сообщение словом «завершить».</i>"

    kb_builder = InlineKeyboardBuilder()
    for ans in shuffled_answers:
        is_corr = 1 if ans == correct_answer else 0
        kb_builder.button(
            text=ans,
            callback_data=f"qans:{quiz_id}:{is_corr}"
        )
    kb_builder.adjust(1)

    try:
        sent_msg = await m.answer(msg_text, reply_markup=kb_builder.as_markup())
        logging.info(f"[QUIZ_LOG] Сообщение викторины отправлено в чат. Message ID: {sent_msg.message_id}")
    except Exception as e:
        logging.error(f"[QUIZ_LOG ERROR] Не удалось отправить сообщение викторины: {e}")
        return

    # Закрепляем сообщение
    try:
        await bot.pin_chat_message(chat_id=m.chat.id, message_id=sent_msg.message_id, disable_notification=True)
        logging.info(f"[QUIZ_LOG] Сообщение викторины закреплено.")
    except TelegramAPIError as e:
        logging.warning(f"[QUIZ_LOG] Не удалось закрепить сообщение: {e}")

    await db_query("UPDATE quizzes SET message_id=? WHERE quiz_id=?", (sent_msg.message_id, quiz_id), commit=True)
    schedule_sync()


@router.message(F.text.lower() == "завершить")
async def manual_finish_quiz_handler(m: types.Message):
    logging.info(f"[QUIZ_LOG] Пользователь {m.from_user.id} запросил завершение викторины через реплай в чате {m.chat.id}")
    if not m.reply_to_message:
        return

    quiz = await db_query(
        "SELECT quiz_id, chat_id, creator_id, is_active FROM quizzes WHERE chat_id=? AND message_id=?",
        (m.chat.id, m.reply_to_message.message_id),
        fetchone=True
    )

    if not quiz:
        logging.info(f"[QUIZ_LOG] Викторина по message_id {m.reply_to_message.message_id} не найдена в БД.")
        return

    quiz_id, chat_id, creator_id, is_active = quiz
    logging.info(f"[QUIZ_LOG] Найдена викторина ID {quiz_id}. Статус is_active: {is_active}, создатель: {creator_id}")

    if is_active == 0:
        return await m.answer("🍋")

    if m.from_user.id != creator_id:
        logging.warning(f"[QUIZ_LOG] Пользователь {m.from_user.id} попытался завершить чужую викторину (автор: {creator_id})")
        return await m.answer("🌫️ Завершить викторину может только её создатель!")

    await finalize_quiz(quiz_id, chat_id, m.reply_to_message.message_id, creator_id)
    await try_delete(m)


@router.message(F.text.lower() == "завершить все")
async def finish_all_quizzes_private(m: types.Message):
    logging.info(f"[QUIZ_LOG] Пользователь {m.from_user.id} запросил 'завершить все' в ЛС.")
    if m.chat.type != "private":
        return await m.answer("🫗 Эту команду нужно писать в личные сообщения боту!")

    active_quizzes = await db_query(
        "SELECT quiz_id, chat_id, message_id, creator_id FROM quizzes WHERE creator_id=? AND is_active=1",
        (m.from_user.id,),
        fetchall=True
    )

    if not active_quizzes:
        logging.info(f"[QUIZ_LOG] Активных викторин для пользователя {m.from_user.id} не найдено.")
        return await m.answer("🫙 У вас нет активных викторин.")

    count = 0
    for quiz_id, chat_id, message_id, creator_id in active_quizzes:
        await finalize_quiz(quiz_id, chat_id, message_id, creator_id)
        count += 1

    logging.info(f"[QUIZ_LOG] Успешно завершено активных викторин: {count}")
    await m.answer(f"✨ Успешно завершено ваших викторин: <b>{count}</b>.")


@router.callback_query(F.data.startswith("qans:"))
async def process_quiz_answer(call: types.CallbackQuery):
    logging.info(f"[QUIZ_LOG] Получен callback от пользователя {call.from_user.id}: {call.data}")
    data_parts = call.data.split(":")
    if len(data_parts) < 3:
        logging.error(f"[QUIZ_LOG ERROR] Некорректный формат callback_data: {call.data}")
        return await call.answer("🍋", show_alert=True)
    
    quiz_id = int(data_parts[1])
    is_correct = int(data_parts[2]) == 1
    uid = call.from_user.id
    cid = call.message.chat.id

    quiz = await db_query("SELECT is_active, creator_id, message_id, question FROM quizzes WHERE quiz_id=?", (quiz_id,), fetchone=True)
    if not quiz:
        logging.warning(f"[QUIZ_LOG] Викторина с ID {quiz_id} вообще не найдена в базе данных при нажатии кнопки!")
        return await call.answer("🍋", show_alert=True)

    is_active, creator_id, message_id, question = quiz[0], quiz[1], quiz[2], quiz[3]
    logging.info(f"[QUIZ_LOG] Состояние викторины {quiz_id}: is_active={is_active}, creator={creator_id}")

    if is_active == 0:
        logging.info(f"[QUIZ_LOG] Попытка ответить на уже завершенную викторину {quiz_id}")
        return await call.answer("🍋", show_alert=True)

    if uid == creator_id:
        return await call.answer("🌸 Вы создатель этой викторины, нельзя отвечать на неё!", show_alert=True)

    already_answered = await db_query("SELECT is_correct FROM quiz_answers WHERE quiz_id=? AND user_id=?", (quiz_id, uid), fetchone=True)
    if already_answered:
        return await call.answer("🌸 Вы уже давали ответ на эту викторину!", show_alert=True)

    user_disp_name = await get_display_name(cid, uid, call.from_user.first_name)

    # Сохраняем ответ
    try:
        await db_query("INSERT INTO quiz_answers VALUES (?,?,?)", (quiz_id, uid, 1 if is_correct else 0), commit=True)
        logging.info(f"[QUIZ_LOG] Ответ пользователя {uid} на викторину {quiz_id} успешно записан. Корректность: {is_correct}")
    except Exception as e:
        logging.error(f"[QUIZ_LOG ERROR] Не удалось записать ответ пользователя в БД: {e}")

    if is_correct:
        await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + 5 WHERE chat_id=? AND user_id=?", (cid, uid), commit=True)
        await call.answer("Правильно!👏🏻 Вы получаете 5📼!", show_alert=True)

        try:
            await bot.send_message(
                creator_id,
                f"✅ <b>Ваша викторина:</b> {html.quote(question)}\n"
                f"Пользователь <b>{html.quote(user_disp_name)}</b> (ID: {uid}) ответил(а) <b>ПРАВИЛЬНО</b>!"
            )
        except TelegramAPIError as e:
            logging.warning(f"[QUIZ_LOG] Не удалось отправить уведомление создателю в ЛС: {e}")
    else:
        user_tapes_res = await db_query("SELECT tapes FROM users WHERE chat_id=? AND user_id=?", (cid, uid), fetchone=True)
        curr_tapes = (user_tapes_res[0] if user_tapes_res else 0) or 0
        penalty = min(curr_tapes, 5)

        await db_query("UPDATE users SET tapes = tapes - ? WHERE chat_id=? AND user_id=?", (penalty, cid, uid), commit=True)
        await db_query("UPDATE users SET tapes = COALESCE(tapes, 0) + ? WHERE chat_id=? AND user_id=?", (penalty, cid, creator_id), commit=True)

        await call.answer("Неправильно!👎🏻 Вы потеряли 5📼!", show_alert=True)

        try:
            await bot.send_message(
                creator_id,
                f"❌ <b>Ваша викторина:</b> {html.quote(question)}\n"
                f"Пользователь <b>{html.quote(user_disp_name)}</b> (ID: {uid}) ответил(а) <b>НЕПРАВИЛЬНО</b>! (+{penalty} 📼 вам)"
            )
        except TelegramAPIError as e:
            logging.warning(f"[QUIZ_LOG] Не удалось отправить уведомление создателю в ЛС: {e}")

    # Проверяем, ответили ли ВСЕ участники чата
    members = await db_query("SELECT user_id FROM chat_members WHERE chat_id=? AND user_id!=?", (cid, creator_id), fetchall=True) or []
    answers = await db_query("SELECT user_id FROM quiz_answers WHERE quiz_id=?", (quiz_id,), fetchall=True) or []

    logging.info(f"[QUIZ_LOG] Проверка автозавершения викторины {quiz_id}: ответило {len(answers)} из {len(members)} участников.")
    if members and len(answers) >= len(members):
        logging.info(f"[QUIZ_LOG] Все участники ответили. Автоматически завершаем викторину {quiz_id}.")
        await finalize_quiz(quiz_id, cid, message_id, creator_id)

    schedule_sync()


async def finalize_quiz(quiz_id: int, chat_id: int, message_id: int, creator_id: int):
    logging.info(f"[QUIZ_LOG] Вызвана функция finalize_quiz для викторины ID {quiz_id} в чате {chat_id}")
    
    await db_query("UPDATE quizzes SET is_active=0 WHERE quiz_id=?", (quiz_id,), commit=True)

    quiz = await db_query("SELECT question FROM quizzes WHERE quiz_id=?", (quiz_id,), fetchone=True)
    question_text = quiz[0] if quiz else ""
    vee_name = await get_display_name(chat_id, creator_id, "Vee")

    answers = await db_query("SELECT user_id, is_correct FROM quiz_answers WHERE quiz_id=?", (quiz_id,), fetchall=True) or []
    logging.info(f"[QUIZ_LOG] Всего ответов получено для итогов викторины {quiz_id}: {len(answers)}")

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
        f"<b>Вопрос:</b> {html.quote(question_text)}\n\n"
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
        logging.info(f"[QUIZ_LOG] Сообщение викторины {quiz_id} успешно отредактировано на результаты.")
    except TelegramAPIError as e:
        logging.error(f"[QUIZ_LOG ERROR] Не удалось отредактировать сообщение с результатами: {e}")

    try:
        await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        logging.info(f"[QUIZ_LOG] Сообщение викторины {quiz_id} откреплено.")
    except TelegramAPIError as e:
        logging.warning(f"[QUIZ_LOG] Не удалось открепить сообщение: {e}")

    try:
        await bot.send_message(
            creator_id,
            f"📊 <b>Результаты вашей викторины:</b>\n\n{final_msg}"
        )
        logging.info(f"[QUIZ_LOG] Результаты отправлены создателю {creator_id} в ЛС.")
    except TelegramAPIError as e:
        logging.warning(f"[QUIZ_LOG] Не удалось отправить результаты создателю в ЛС: {e}")

    schedule_sync()
    
