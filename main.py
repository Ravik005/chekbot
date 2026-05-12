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
    raise ValueError("No BOT_TOKEN found in environment variables")

TARGET_BOT_LINK = os.getenv("TARGET_BOT_LINK", "https://t.me/hacks11_bot")
FIRST_CHANNEL = os.getenv("FIRST_CHANNEL", "@VyruchaiCardBotChannel")
OTHER_CHANNELS = os.getenv("OTHER_CHANNELS", "@naruto_boruto_seriess,@XochuKuplu,@madeinvostok,@cattayson").split(",")
REQUIRED_COUNT = int(os.getenv("REQUIRED_COUNT", "3"))
DB_PATH = "users.db"
# =================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_state = {}

def init_db():
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

    # Выбираем 2 случайных канала из OTHER_CHANNELS
    other_list = OTHER_CHANNELS.copy()
    if len(other_list) < 2:
        await message.answer("❌ Ошибка: недостаточно каналов для выбора.")
        return
    random_others = random.sample(other_list, 2)
    selected_channels = [FIRST_CHANNEL] + random_others

    user_state[user_id] = {
        "step": 1,
        "channels": selected_channels
    }
    add_user(user_id, username, first_name, step=1)

    first_channel = selected_channels[0]
    await message.answer(
        f"🔐 Шаг 1 из {REQUIRED_COUNT}\nПодпишись на этот канал:",
        reply_markup=channel_keyboard(first_channel, step_num=1, total=REQUIRED_COUNT)
    )

@dp.callback_query(F.data == "check_step")
async def handle_subscription_check(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_state.get(user_id)
    if not state:
        await callback.message.edit_text("❌ Ошибка. Напиши /start заново.")
        await callback.answer()
        return

    step = state["step"]
    channels = state["channels"]
    current_channel = channels[step - 1]

    if not await is_subscribed(user_id, current_channel):
        await callback.answer(
            f"❌ Ты не подписался на канал {current_channel}. Подпишись и нажми кнопку снова.",
            show_alert=True
        )
        return

    if step < REQUIRED_COUNT:
        state["step"] = step + 1
        update_user_step(user_id, step + 1)
        next_channel = channels[step]
        await callback.message.edit_text(
            f"✅ Шаг {step} пройден!\n\n🔐 Шаг {step + 1} из {REQUIRED_COUNT}\nТеперь подпишись на этот канал:",
            reply_markup=channel_keyboard(next_channel, step_num=step + 1, total=REQUIRED_COUNT)
        )
        await callback.answer(f"Шаг {step} пройден! Переходим к следующему.")
    else:
        update_user_success(user_id)
        await callback.message.edit_text(
            f"🎉 Поздравляю! Ты подписался на все {REQUIRED_COUNT} каналов.\n\n"
            f"🔗 Вот ссылка на основного бота:\n{TARGET_BOT_LINK}\n\nТеперь пользуйся!"
        )
        del user_state[user_id]
        await callback.answer("Доступ открыт!")

def run_bot():
    asyncio.run(dp.start_polling(bot))

@app.route('/')
def index():
    return "Bot is running!"

@app.route('/health')
def health_check():
    return "OK"

if __name__ == '__main__':
    init_db()
    logging.basicConfig(level=logging.INFO)
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
