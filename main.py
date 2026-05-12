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

# ========== ВСЕ НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in environment")

TARGET_BOT_LINK = os.getenv("TARGET_BOT_LINK", "https://t.me/hacks11_bot")
FIRST_CHANNEL = os.getenv("FIRST_CHANNEL")
if not FIRST_CHANNEL:
    raise ValueError("FIRST_CHANNEL not set in environment")
OTHER_CHANNELS_STR = os.getenv("OTHER_CHANNELS")
if not OTHER_CHANNELS_STR:
    raise ValueError("OTHER_CHANNELS not set in environment")
OTHER_CHANNELS = [ch.strip() for ch in OTHER_CHANNELS_STR.split(",") if ch.strip()]
REQUIRED_COUNT = int(os.getenv("REQUIRED_COUNT", "3"))
DB_PATH = "data/users.db"
# ============================================================

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

def add_user(user_id: int, username: str, first_name: str, step: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, start_date, last_step)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now().isoformat(), step))
    conn.commit()
    conn.close()

def update_user_step(user_id: int, step: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE users SET last_step = ? WHERE user_id = ?', (step, user_id))
    conn.commit()
    conn.close()

def update_user_success(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE users SET success_date = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def is_user_already_success(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT success_date FROM users WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] is not None

async def is_subscribed(user_id: int, channel: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    except Exception as e:
        logging.error(f"Ошибка проверки {channel}: {e}")
        return False

def channel_keyboard(channel: str, step_num: int, total: int) -> InlineKeyboardMarkup:
    username = channel.lstrip('@')
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на канал {step_num}", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="✅ Я подписался!", callback_data="check_step")]
    ])

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    # Если пользователь уже получал доступ — сразу даём ссылку без подписок
    if is_user_already_success(user_id):
        await message.answer(
            f"🎉 С возвращением, {first_name}!\n\n"
            f"Вы уже активировали доступ. Вот ваша ссылка:\n"
            f"{TARGET_BOT_LINK}\n\n"
            f"Пожалуйста, не пытайтесь пройти проверку заново — это не требуется."
        )
        return

    if len(OTHER_CHANNELS) < 2:
        await message.answer("❌ Ошибка: недостаточно каналов для выбора (нужно минимум 2 в OTHER_CHANNELS).")
        return

    random_others = random.sample(OTHER_CHANNELS, 2)
    selected_channels = [FIRST_CHANNEL] + random_others

    user_state[user_id] = {
        "step": 1,
        "channels": selected_channels
    }
    add_user(user_id, username, first_name, step=1)

    first_channel = selected_channels[0]
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"🔐 Добро пожаловать! Для получения доступа к боту {TARGET_BOT_LINK}\n"
        f"необходимо подписаться на {REQUIRED_COUNT} каналов.\n\n"
        f"**Шаг 1 из {REQUIRED_COUNT}**\n"
        f"Пожалуйста, подпишись на этот канал и нажми кнопку «Я подписался!»:",
        reply_markup=channel_keyboard(first_channel, step_num=1, total=REQUIRED_COUNT)
    )

@dp.callback_query(F.data == "check_step")
async def handle_subscription_check(callback: CallbackQuery):
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name or "Пользователь"

    # Если пользователь уже успешен — не даём проходить заново
    if is_user_already_success(user_id):
        await callback.message.edit_text(
            f"✅ Вы уже получили доступ. Ваша ссылка: {TARGET_BOT_LINK}\n\n"
            f"Пожалуйста, не пытайтесь пройти проверку снова."
        )
        await callback.answer("Доступ уже был открыт")
        return

    state = user_state.get(user_id)
    if not state:
        await callback.message.edit_text("❌ Ошибка сессии. Пожалуйста, перезапустите бота командой /start")
        await callback.answer()
        return

    step = state["step"]
    channels = state["channels"]
    current_channel = channels[step - 1]

    # Проверяем подписку
    if not await is_subscribed(user_id, current_channel):
        await callback.answer(
            f"❌ {first_name}, вы ещё не подписались на канал {current_channel}.\n"
            "Подпишитесь и нажмите кнопку снова.",
            show_alert=True
        )
        return

    # Подписка подтверждена
    if step < REQUIRED_COUNT:
        # Переход к следующему шагу
        state["step"] = step + 1
        update_user_step(user_id, step + 1)
        next_channel = channels[step]
        await callback.message.edit_text(
            f"✅ Отлично, {first_name}! Шаг {step} пройден.\n\n"
            f"🔐 Шаг {step + 1} из {REQUIRED_COUNT}\n"
            f"Теперь подпишись на этот канал:",
            reply_markup=channel_keyboard(next_channel, step_num=step + 1, total=REQUIRED_COUNT)
        )
        await callback.answer(f"Шаг {step} пройден! Переходим к следующему.")
    else:
        # Все шаги выполнены – выдаём ссылку и записываем в БД успех
        update_user_success(user_id)
        await callback.message.edit_text(
            f"🎉 Поздравляю, {first_name}!\n\n"
            f"Вы успешно подписались на все {REQUIRED_COUNT} каналов.\n\n"
            f"🔗 Ваша ссылка на основного бота:\n{TARGET_BOT_LINK}\n\n"
            f"Теперь вы можете пользоваться ботом.\n\n"
            f"⚠️ Повторная проверка не потребуется, команда /start будет сразу выдавать ссылку."
        )
        if user_id in user_state:
            del user_state[user_id]
        await callback.answer("Доступ открыт! Спасибо за подписки.")

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
    # Запускаем Flask в фоновом потоке-демоне
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # Запускаем бота в главном потоке
    asyncio.run(dp.start_polling(bot))
