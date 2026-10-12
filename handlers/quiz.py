import re
import random
asyncio_module = __import__('asyncio')
from datetime import datetime
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import bot
from database import db_query
from utils import is_authorized_chat, try_delete, get_text

router = Router()

@router.message(F.text)
async def create_quiz_handler(m: types.Message):
    if not await is_authorized_chat(m.chat.id):
        return

    text = m.text.strip()
    if not text.lower().startswith("викторина"):
        return

    # Проверка тега Vee
    tag_row = await db_query(
        "SELECT 1 FROM user_tags WHERE chat_id=? AND user_id=? AND LOWER(tag)='vee'",
        (m.chat.id, m.from_user.id),
        fetchone=True
    )
    if not tag_row:
        no_vee = await get_text(m.chat.id, "quiz_no_vee")
        await m.answer(no_vee)
        return

    # Парсинг команды: викторина [вопрос] Ответы:[|1|; |2|; ...]
    match = re.match(r'викторина\s+(.+?)\s+ответы:\s*\[(.+)\]', text, re.IGNORECASE)
    if not match:
        err_msg = await get_text(m.chat.id, "quiz_format_err")
        await m.answer(err_msg)
        return

    question = match.group(1).strip()
    raw_answers = match.group(2)
    
    # Извлекаем варианты из карманов |вариант|
    options = [opt.strip().strip('|') for opt in raw_answers.split(';') if '|' in opt]
    if len(options) < 2:
        await m.answer("🌫️ Укажите хотя бы один правильный и один неправильный ответ через разделитель |.")
        return

    correct_answer = options[0]
    shuffled_options = options.copy()
    random.shuffle(shuffled_options)

    await try_delete(m)

    # Создаем клавиатуру с перемешанными ответами
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"quiz_ans:{opt[:30]}")] 
        for opt in shuffled_options
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    quiz_text = await get_text(m.chat.id, "quiz_started", question=question)
    sent_msg = await m.answer(quiz_text, reply_markup=keyboard)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await db_query(
        "INSERT INTO quizzes (chat_id, message_id, creator_id, question, correct_answer, status, created_at) VALUES (?,?,?,?,?,1,?)",
        (m.chat.id, sent_msg.message_id, m.from_user.id, question, correct_answer, now_str),
        commit=True
    )
    
    res = await db_query("SELECT last_insert_rowid()", fetchone=True)
    quiz_id = res[0]

    # Запускаем фоновый таймер на 15 минут (900 секунд)
    asyncio_module.create_task(quiz_timer(m.chat.id, sent_msg.message_id, quiz_id, question, correct_answer, m.from_user.id))


async def quiz_timer(chat_id: int, message_id: int, quiz_id: int, question: str, correct_answer: str, creator_id: int):
    await asyncio_module.sleep(900) # 15 минут
    
    # Проверяем, не завершена ли викторина
    q_row = await db_query("SELECT status FROM quizzes WHERE quiz_id=?", (quiz_id,), fetchone=True)
    if not q_row or q_row[0] == 0:
        return

    await finish_quiz(chat_id, message_id, quiz_id, question, correct_answer, creator_id)


async def finish_quiz(chat_id: int, message_id: int, quiz_id: int, question: str, correct_answer: str, creator_id: int):
    # Помечаем викторину завершенной
    await db_query("UPDATE quizzes SET status=0 WHERE quiz_id=?", (quiz_id,), commit=True)

    answers = await db_query("SELECT user_id, user_name, answer, is_correct FROM quiz_answers WHERE quiz_id=?", (quiz_id,), fetchall=True)

    correct_users = [row[1] for row in answers if row[3] == 1]
    incorrect_users = [row[1] for row in answers if row[3] == 0]

    correct_list_str = "\n".join([f"• {name}" for name in correct_users]) if correct_users else "Никто"
    incorrect_list_str = "\n".join([f"• {name}" for name in incorrect_users]) if incorrect_users else "Никто"

    # Сообщение в чат
    final_text = await get_text(
        chat_id, 
        "quiz_finished", 
        question=question, 
        correct_list=correct_list_str, 
        incorrect_list=incorrect_list_str
    )

    try:
        await bot.edit_message_text(final_text, chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        await bot.send_message(chat_id, final_text)

    # Отчет создателю в ЛС
    creator_text = await get_text(
        chat_id,
        "quiz_creator_pm",
        question=question,
        correct_list=correct_list_str,
        incorrect_list=incorrect_list_str
    )
    try:
        await bot.send_message(creator_id, creator_text)
    except Exception:
        pass


@router.callback_query(F.data.startswith("quiz_ans:"))
async def quiz_callback_handler(call: types.CallbackQuery):
    selected_prefix = call.data.split(":", 1)[1]
    user_id = call.from_user.id
    user_name = call.from_user.first_name or "Участник"
    chat_id = call.message.chat.id

    # Находим активную викторину по message_id
    quiz_row = await db_query(
        "SELECT quiz_id, creator_id, question, correct_answer, status FROM quizzes WHERE chat_id=? AND message_id=?",
        (chat_id, call.message.message_id),
        fetchone=True
    )

    if not quiz_row or quiz_row[4] == 0:
        await call.answer("⏳ Эта викторина уже завершена.", show_alert=True)
        return

    quiz_id, creator_id, question, correct_answer, status = quiz_row

    # Проверяем, ответил ли уже пользователь
    ans_check = await db_query("SELECT 1 FROM quiz_answers WHERE quiz_id=? AND user_id=?", (quiz_id, user_id), fetchone=True)
    if ans_check:
        await call.answer("❌ Вы уже ответили на этот вопрос!", show_alert=True)
        return

    # Определяем правильность (сравнение по префиксу или поиск точного совпадения в кнопках)
    is_correct = 1 if selected_prefix.lower() in correct_answer.lower() else 0

    # Сохраняем ответ
    await db_query(
        "INSERT INTO quiz_answers (quiz_id, user_id, user_name, answer, is_correct) VALUES (?,?,?,?,?)",
        (quiz_id, user_id, user_name, selected_prefix, is_correct),
        commit=True
    )

    if is_correct:
        # +5 лент за правильный ответ
        await db_query("UPDATE users SET tapes = tapes + 5 WHERE chat_id=? AND user_id=?", (chat_id, user_id), commit=True)
        await call.answer("✅ Верно! +5📼", show_alert=True)
    else:
        # -5 лент за неправильный ответ
        await db_query("UPDATE users SET tapes = MAX(0, tapes - 5) WHERE chat_id=? AND user_id=?", (chat_id, user_id), commit=True)
        
        # Автору викторины +5 лент и уведомление в ЛС
        await db_query("UPDATE users SET tapes = tapes + 5 WHERE chat_id=? AND user_id=?", (chat_id, creator_id), commit=True)
        try:
            penalty_msg = await get_text(chat_id, "quiz_penalty_pm", user=user_name)
            await bot.send_message(creator_id, penalty_msg)
        except Exception:
            pass

        await call.answer("❌ Неверно! -5📼", show_alert=True)
      
