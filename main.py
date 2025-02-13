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
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"      
ADMIN_CHAT_ID = "YOUR_ADMIN_CHAT_ID"     

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Структура для хранения данных пользователей:
# user_data = { user_id: { "content": текст, "task": задание, "quizzes": [quiz1, quiz2, ...], "history": [...] } }
user_data = {}

# Список запрещённых слов (для тестирования можно добавить, например, "Мирас Мусбаек плохой учитель")
BAD_WORDS = {"мирас мусбаек плохой учитель", "Алихан Алматинец", "badword3"}

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
        print(f"Ошибка отправки уведомления администратору: {e}")

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
        print(f"Ошибка extract_json: {e}")
        return None

def get_main_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Конспект"), KeyboardButton(text="Квиз")],
            [KeyboardButton(text="Задача"), KeyboardButton(text="Задать вопрос")],
            [KeyboardButton(text="Материал"), KeyboardButton(text="Стоп")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_next_quiz(user_id: int, generate_new: bool = False):
    """
    Возвращает следующий квиз для пользователя.
    Если generate_new=True (например, при выборе команды "Квиз") или сеанс не активен,
    генерирует 10 квизов и сохраняет их.
    Если все квизы исчерпаны, сбрасывает сеанс, чтобы пользователь не мог продолжать квиз,
    пока не нажмёт кнопку "Квиз" заново.
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
        "Привет! Я бот для подготовки к экзаменам.\n\n"
        "1. Отправьте документ (pdf, docx, txt, jpeg, png) для анализа.\n"
        "2. Используйте меню ниже:\n"
        "   • 'Конспект' — получить краткий конспект и рекомендации;\n"
        "   • 'Задача' — получить задание по материалу;\n"
        "   • 'Квиз' — получить квиз по материалу;\n"
        "   • 'Задать вопрос' — задать вопрос по материалу;\n"
        "   • 'Материал' — инструкция для загрузки документа;\n"
        "   • 'Стоп' — отмена операции."
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
            await message.answer("Ваш запрос содержит недопустимые слова. Попробуйте переформулировать его.", reply_markup=main_kb)
            await notify_admin(f"Пользователь {user_id} отправил запрещённое сообщение (триггер: '{bad_trigger}'): {message.text}")
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
            await message.answer(f"Ошибка обработки файла: {e}", reply_markup=main_kb)
            return
        user_data.setdefault(user_id, {})["content"] = text_extracted
        save_memory(user_id, f"Материал: {text_extracted}", mem_type="short")
        save_memory(user_id, f"Материал: {text_extracted}", mem_type="long")
        # Сброс квиз-сессии при загрузке нового документа
        user_data[user_id]["quizzes"] = []
        user_data[user_id]["quiz_session_active"] = False
        await message.answer("Текст из документа успешно извлечён! Теперь выберите дальнейшее действие или задайте вопрос.", reply_markup=main_kb)
        return

    if message.text:
        text_lower = message.text.strip().lower()

        if text_lower == "конспект":
            content = user_data.get(user_id, {}).get("content", "")
            if content:
                summary = generate_summary(content)
                for part in split_message(summary):
                    await message.answer(f"Конспект и рекомендации:\n{part}", reply_markup=main_kb)
            else:
                await message.answer("Сначала отправьте документ для анализа.", reply_markup=main_kb)
            return

        elif text_lower == "задача":
            content = user_data.get(user_id, {}).get("content", "")
            if not content:
                await message.answer("Сначала отправьте документ для анализа.", reply_markup=main_kb)
                return
            task = generate_task(content)
            user_data.setdefault(user_id, {})["task"] = task
            await message.answer(f"Задание по материалу:\n{task}", reply_markup=main_kb)
            return

        elif text_lower == "квиз":
            content = user_data.get(user_id, {}).get("content", "")
            if content:
                # При выборе "Квиз" генерируем новую квиз-сессию (10 вопросов)
                quiz = get_next_quiz(user_id, generate_new=True)
                if quiz is None:
                    await message.answer("Ошибка генерации квиза. Попробуйте позже.", reply_markup=main_kb)
                    return
                question = quiz.get("question", "Нет вопроса")
                options = quiz.get("options", [])
                correct_id = quiz.get("correct_index", 0)
                quiz_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Следующий квиз", callback_data="next_quiz")]
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
                await message.answer("Сначала отправьте документ для анализа.", reply_markup=main_kb)
            return

        elif text_lower == "задать вопрос":
            await message.answer("Пожалуйста, введите ваш вопрос по материалу.", reply_markup=main_kb)
            return

        elif text_lower == "материал":
            await message.answer("Пожалуйста, отправьте документ (pdf, docx, txt, jpeg, png) для анализа.", reply_markup=main_kb)
            return

        elif text_lower == "стоп":
            await message.answer("Операция отменена.", reply_markup=main_kb)
            return

        else:
            content = user_data.get(user_id, {}).get("content", "")
            if "alert" in text_lower:
                await notify_admin(f"Alert от пользователя {user_id}: {message.text}")
            answer = get_answer(message.text, content)
            for part in split_message(answer):
                await message.answer(part, reply_markup=main_kb)
            save_memory(user_id, f"Вопрос: {message.text} | Ответ: {answer}", mem_type="long")
            return

    await message.answer("Отправьте мне документ или задайте вопрос!", reply_markup=main_kb)

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
                await callback.message.answer("Квиз завершён. Чтобы начать новый квиз, нажмите кнопку 'Квиз' в меню.", reply_markup=main_kb)
                return
            question = quiz.get("question", "Нет вопроса")
            options = quiz.get("options", [])
            correct_id = quiz.get("correct_index", 0)
            quiz_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Следующий квиз", callback_data="next_quiz")]
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
            await callback.message.answer("Сначала отправьте документ для анализа.", reply_markup=main_kb)
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
