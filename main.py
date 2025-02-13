#!/usr/bin/env python3
import os
import asyncio
import json
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from file_processing import (
    process_file,
    get_answer,
    generate_summary,
    generate_task,
    generate_quiz
)

# Замените на реальные данные
TOKEN = ""      
ADMIN_CHAT_ID = ""     

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Структура для хранения данных пользователей:
# user_data = { user_id: { "content": текст, "task": задание, "quizzes": [quiz1, quiz2, ...], "history": [...] } }
user_data = {}

# Список запрещённых слов (для тестирования можно добавить, например, "Мирас Мусбаек плохой учитель")
BAD_WORDS = {"мирас мусабек плохой учитель", "Алихан Алматинец", "badword3"}

def save_memory(user_id: int, message: str, mem_type: str = "short"):
    # Указываем путь к папке, куда будут сохраняться файлы
    directory = "data"
    # Если папка не существует, создаем её
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, f"user_{user_id}_{mem_type}.txt")
    with open(filename, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def load_memory(user_id: int, mem_type: str = "long") -> str:
    filename = f"user_{user_id}_{mem_type}.txt"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def check_bad_words(text: str) -> str:
    """
    Проверяет, содержит ли текст запрещённое слово.
    Возвращает первое найденное запрещённое слово (в нижнем регистре) или пустую строку.
    """
    for bad in BAD_WORDS:
        if bad.lower() in text.lower():
            return bad
    return ""

async def notify_admin(message: str):
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
    except TelegramAPIError as e:
        print(f"Error sending notification to administrator:{e}")

def split_message(text, max_length=4096):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

def extract_json(text: str):
    """
    Извлекает подстроку от первого символа '{' до последнего символа '}' и пытается распарсить её как JSON.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except Exception as e:
        print(f"Error extract_json: {e}")
        return None

def get_main_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Summary"), KeyboardButton(text="Quiz")],
            [KeyboardButton(text="Task"), KeyboardButton(text="Ask a question")],
            [KeyboardButton(text="Material"), KeyboardButton(text="Stop")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_next_quiz(user_id: int, generate_new: bool = False):
    """
    Возвращает следующий квиз для пользователя.
    Если generate_new=True (например, при выборе команды "Quiz") или сеанс не активен,
    генерирует 10 квизов и сохраняет их.
    Если все квизы исчерпаны, сбрасывает сеанс, чтобы пользователь не мог продолжать квиз,
    пока не нажмёт кнопку "Quiz" заново.
    """
    user_data.setdefault(user_id, {})
    if "quizzes" not in user_data[user_id]:
        user_data[user_id]["quizzes"] = []
    if "quiz_session_active" not in user_data[user_id]:
        user_data[user_id]["quiz_session_active"] = False

    if generate_new or not user_data[user_id]["quiz_session_active"]:
        content = user_data[user_id].get("content", "")
        if not content:
            return None
        # Очистим предыдущий список квизов
        user_data[user_id]["quizzes"] = []
        for _ in range(10):
            quiz_response = generate_quiz(content)
            quiz = extract_json(quiz_response)
            if quiz is not None:
                options = quiz.get("options", [])
                trimmed_options = []
                for opt in options:
                    if isinstance(opt, dict):
                        opt_text = opt.get("option", "")
                    else:
                        opt_text = str(opt)
                    if len(opt_text) > 100:
                        opt_text = opt_text[:97] + "..."
                    trimmed_options.append(opt_text)
                quiz["options"] = trimmed_options
                user_data[user_id]["quizzes"].append(quiz)
        user_data[user_id]["quiz_session_active"] = True

    if user_data[user_id]["quizzes"]:
        quiz = user_data[user_id]["quizzes"].pop(0)
        if not user_data[user_id]["quizzes"]:
            user_data[user_id]["quiz_session_active"] = False
        return quiz
    else:
        user_data[user_id]["quiz_session_active"] = False
        return None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = (
        "Hi! I'm a bot for exam preparation.\n\n"
        "1. Send the document (pdf, docx, txt, jpeg, png) for analysis.\n"
        "2. Use the menu below:\n"
        "   • 'Summary' - get a brief summary and recommendations;\n"
        "   • 'Task' - receive a task on the material;\n"
        "   • 'Quiz' - get a quiz on the material;\n"
        "   • 'Ask a question' - ask a question about the material;\n"
        "   • 'Material' - instructions for uploading a document;\n"
        "   • 'Stop' - cancel the operation."
    )
    await message.answer(text, reply_markup=get_main_reply_keyboard())

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    main_kb = get_main_reply_keyboard()

    # Проверка на запрещённые слова с уведомлением админа
    if message.text:
        bad_trigger = check_bad_words(message.text)
        if bad_trigger:
            await message.answer("Your request contains invalid words. Try reformulating it.", reply_markup=main_kb)
            await notify_admin(f"User {user_id} sent a prohibited message (trigger: '{bad_trigger}'):{message.text}")
            return

    if message.document or message.photo:
        try:
            if message.document:
                file = await bot.download(message.document)
                mime = message.document.mime_type
            else:
                file = await bot.download(message.photo[-1])
                mime = "image/jpeg"
            text_extracted = process_file(file, mime)
        except Exception as e:
            await message.answer(f"Error processing file: {e}", reply_markup=main_kb)
            return
        user_data.setdefault(user_id, {})["content"] = text_extracted
        save_memory(user_id, f"Material: {text_extracted}", mem_type="short")
        save_memory(user_id, f"Material: {text_extracted}", mem_type="long")
        # Сброс квиз-сессии при загрузке нового документа
        user_data[user_id]["quizzes"] = []
        user_data[user_id]["quiz_session_active"] = False
        await message.answer("The text from the document has been successfully extracted! Now choose an action or ask a question.", reply_markup=main_kb)
        return

    if message.text:
        text_lower = message.text.strip().lower()

        if text_lower == "summary":
            content = user_data.get(user_id, {}).get("content", "")
            if content:
                summary = generate_summary(content)
                for part in split_message(summary):
                    await message.answer(f"Summary and recommendations:\n{part}", reply_markup=main_kb)
            else:
                await message.answer("Please send a document for analysis first.", reply_markup=main_kb)
            return

        elif text_lower == "task":
            content = user_data.get(user_id, {}).get("content", "")
            if not content:
                await message.answer("Please send a document for analysis first.", reply_markup=main_kb)
                return
            task = generate_task(content)
            user_data.setdefault(user_id, {})["task"] = task
            await message.answer(f"Task on the material:\n{task}", reply_markup=main_kb)
            return

        elif text_lower == "quiz":
            content = user_data.get(user_id, {}).get("content", "")
            if content:
                # When "Quiz" is selected, generate a new quiz session (10 questions)
                quiz = get_next_quiz(user_id, generate_new=True)
                if quiz is None:
                    await message.answer("Error generating quiz. Please try again later.", reply_markup=main_kb)
                    return
                question = quiz.get("question", "No question")
                options = quiz.get("options", [])
                correct_id = quiz.get("correct_index", 0)
                quiz_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Next Quiz", callback_data="next_quiz")]
                ])
                await bot.send_poll(
                    chat_id=message.chat.id,
                    question=question,
                    options=options,
                    type="quiz",
                    correct_option_id=correct_id,
                    is_anonymous=False,
                    reply_markup=quiz_keyboard
                )
            else:
                await message.answer("Please send a document for analysis first.", reply_markup=main_kb)
            return

        elif text_lower == "ask a question":
            await message.answer("Please enter your question about the material.", reply_markup=main_kb)
            return

        elif text_lower == "material":
            await message.answer("Please send the document (pdf, docx, txt, jpeg, png) for analysis.", reply_markup=main_kb)
            return

        elif text_lower == "stop":
            await message.answer("Operation canceled.", reply_markup=main_kb)
            return

        else:
            content = user_data.get(user_id, {}).get("content", "")
            if "alert" in text_lower:
                await notify_admin(f"Alert from user {user_id}: {message.text}")
            answer = get_answer(message.text, content)
            for part in split_message(answer):
                await message.answer(part, reply_markup=main_kb)
            save_memory(user_id, f"Question: {message.text} | Answer: {answer}", mem_type="long")
            return

    await message.answer("Please send me a document or ask a question!", reply_markup=main_kb)

@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    main_kb = get_main_reply_keyboard()
    data = callback.data

    if data == "next_quiz":
        content = user_data.get(user_id, {}).get("content", "")
        if content:
            quiz = get_next_quiz(user_id, generate_new=False)
            if quiz is None:
                await callback.message.answer("The quiz session is over. To start a new quiz, press the 'Quiz' button in the menu.", reply_markup=main_kb)
                return
            question = quiz.get("question", "No question")
            options = quiz.get("options", [])
            correct_id = quiz.get("correct_index", 0)
            quiz_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Next Quiz", callback_data="next_quiz")]
            ])
            await bot.send_poll(
                chat_id=callback.message.chat.id,
                question=question,
                options=options,
                type="quiz",
                correct_option_id=correct_id,
                is_anonymous=False,
                reply_markup=quiz_keyboard
            )
        else:
            await callback.message.answer("Please send a document for analysis first.", reply_markup=main_kb)
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
