import asyncio
import logging
import random
import os
import sqlite3
from datetime import datetime
from threading import Thread
from flask import Flask

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

FINAL_BOT_LINK = os.getenv("FINAL_BOT_LINK", "https://t.me/hacks11_bot")
VYRUCHAI_BOT_LINK = os.getenv("VYRUCHAI_BOT_LINK", "https://t.me/VyruchaiCardBot")

FIRST_CHANNEL = os.getenv("FIRST_CHANNEL")
if not FIRST_CHANNEL:
    raise ValueError("FIRST_CHANNEL not set")
OTHER_CHANNELS_STR = os.getenv("OTHER_CHANNELS")
if not OTHER_CHANNELS_STR:
    raise ValueError("OTHER_CHANNELS not set")
OTHER_CHANNELS = [ch.strip() for ch in OTHER_CHANNELS_STR.split(",") if ch.strip()]

REQUIRED_COUNT = 3   # три шага: 1 - ручной запуск, 2 - канал1, 3 - канал2
DB_PATH = "data/users.db"
# ========================================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_state = {}

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            start_date TEXT,
            last_step INTEGER,
            success_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, step):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, start_date, last_step)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now().isoformat(), step))
    conn.commit()
    conn.close()

def update_user_step(user_id, step):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE users SET last_step = ? WHERE user_id = ?', (step, user_id))
    conn.commit()
    conn.close()

def update_user_success(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE users SET success_date = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def is_user_already_success(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT success_date FROM users WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] is not None

async def is_subscribed(user_id, channel):
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception as e:
        logging.error(f"Ошибка проверки {channel}: {e}")
        return False

def step1_keyboard():
    """Шаг 1: ручной запуск VyruchaiCardBot"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Перейти в @VyruchaiCardBot и нажать /start", url=VYRUCHAI_BOT_LINK)],
        [InlineKeyboardButton(text="✅ Я запустил бота!", callback_data="step1_done")]
    ])

def channel_keyboard(channel, step_num):
    username = channel.lstrip('@')
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на канал {step_num}", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="✅ Я подписался!", callback_data="check_channel")]
    ])

def final_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Получить доступ к основному боту", url=FINAL_BOT_LINK)]
    ])

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    if is_user_already_success(user_id):
        await message.answer(
            f"🎉 С возвращением, {first_name}! Ваш доступ уже активирован.",
            reply_markup=final_keyboard()
        )
        return

    # Инициализируем состояние: три шага
    user_state[user_id] = {
        "step": 1,
        "channels": [None, FIRST_CHANNEL, random.choice(OTHER_CHANNELS)]  # шаг2 и шаг3
    }
    add_user(user_id, username, first_name, step=1)

    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"🔐 Для получения доступа к основному боту нужно:\n"
        f"1️⃣ Запустить бота @VyruchaiCardBot (нажать /start)\n"
        f"2️⃣ Подписаться на канал {FIRST_CHANNEL}\n"
        f"3️⃣ Подписаться на канал (будет выбран случайно)\n\n"
        f"**Шаг 1 из 3**\n"
        f"Перейдите в бота и нажмите /start, затем вернитесь и нажмите кнопку ниже:",
        reply_markup=step1_keyboard()
    )

@dp.callback_query(F.data == "step1_done")
async def step1_done(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_state.get(user_id)
    if not state or state["step"] != 1:
        await callback.answer("Ошибка. Напишите /start заново.", show_alert=True)
        return

    # Переходим к шагу 2 (первый канал)
    state["step"] = 2
    update_user_step(user_id, 2)
    first_channel = state["channels"][1]
    await callback.message.edit_text(
        f"✅ Отлично! Теперь **Шаг 2 из 3**\n"
        f"Подпишись на этот канал:",
        reply_markup=channel_keyboard(first_channel, step_num=2)
    )
    await callback.answer()

@dp.callback_query(F.data == "check_channel")
async def check_channel(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_state.get(user_id)
    if not state:
        await callback.answer("Ошибка. Напишите /start заново.", show_alert=True)
        return

    step = state["step"]
    if step == 2:
        channel = state["channels"][1]
        if not await is_subscribed(user_id, channel):
            await callback.answer(
                f"❌ Вы не подписались на канал {channel}. Подпишитесь и нажмите снова.",
                show_alert=True
            )
            return
        # Переходим к шагу 3
        state["step"] = 3
        update_user_step(user_id, 3)
        second_channel = state["channels"][2]
        await callback.message.edit_text(
            f"✅ Шаг 2 пройден!\n\n"
            f"**Шаг 3 из 3**\n"
            f"Теперь подпишись на этот канал:",
            reply_markup=channel_keyboard(second_channel, step_num=3)
        )
        await callback.answer("Шаг 2 пройден!")

    elif step == 3:
        channel = state["channels"][2]
        if not await is_subscribed(user_id, channel):
            await callback.answer(
                f"❌ Вы не подписались на канал {channel}. Подпишитесь и нажмите снова.",
                show_alert=True
            )
            return
        # Все шаги выполнены
        update_user_success(user_id)
        await callback.message.edit_text(
            f"🎉 Поздравляю!\n\n"
            f"Вы выполнили все условия:\n"
            f"✅ Запустили @VyruchaiCardBot\n"
            f"✅ Подписались на {state['channels'][1]}\n"
            f"✅ Подписались на {state['channels'][2]}\n\n"
            f"🔗 Ваша ссылка на основного бота:\n{FINAL_BOT_LINK}",
            reply_markup=final_keyboard()
        )
        del user_state[user_id]
        await callback.answer("Доступ открыт!")

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)

@app.route('/')
def index():
    return "Bot is running!"

@app.route('/health')
def health_check():
    return "OK"

if __name__ == '__main__':
    init_db()
    logging.basicConfig(level=logging.INFO)
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    asyncio.run(dp.start_polling(bot))
