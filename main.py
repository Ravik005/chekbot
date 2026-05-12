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

FINAL_BOT_LINK = os.getenv("FINAL_BOT_LINK", "https://t.me/hacks11_bot")   # То, что выдаём в конце
VYRUCHAI_BOT_LINK = os.getenv("VYRUCHAI_BOT_LINK", "https://t.me/VyruchaiCardBot")   # Бот для ручного запуска

FIRST_CHANNEL = os.getenv("FIRST_CHANNEL")
if not FIRST_CHANNEL:
    raise ValueError("FIRST_CHANNEL not set")
OTHER_CHANNELS_STR = os.getenv("OTHER_CHANNELS")
if not OTHER_CHANNELS_STR:
    raise ValueError("OTHER_CHANNELS not set")
OTHER_CHANNELS = [ch.strip() for ch in OTHER_CHANNELS_STR.split(",") if ch.strip()]
REQUIRED_COUNT = 4   # теперь 4 шага (3 подписки + ручное подтверждение)
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

def channel_keyboard(channel, step_num, total):
    username = channel.lstrip('@')
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на канал {step_num}", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="✅ Я подписался!", callback_data="check_step")]
    ])

def vyruchai_keyboard():
    """Клавиатура для 4-го шага: переход в VyruchaiCardBot и ручное подтверждение"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Перейти в бот VyruchaiCardBot и нажать /start", url=VYRUCHAI_BOT_LINK)],
        [InlineKeyboardButton(text="✅ Я запустил бота!", callback_data="check_step")]
    ])

def final_keyboard():
    """Финальная клавиатура с ссылкой на hacks11_bot"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Перейти к основному боту", url=FINAL_BOT_LINK)]
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

    if len(OTHER_CHANNELS) < 2:
        await message.answer("❌ Недостаточно каналов в OTHER_CHANNELS (нужно минимум 2).")
        return

    # Выбираем 2 случайных канала из остальных
    random_others = random.sample(OTHER_CHANNELS, 2)
    # Шаги: 1 - первый канал, 2 и 3 - случайные каналы, 4 - ручное подтверждение
    selected_channels = [FIRST_CHANNEL] + random_others + ["__MANUAL__"]   # маркер ручного шага

    user_state[user_id] = {
        "step": 1,
        "channels": selected_channels
    }
    add_user(user_id, username, first_name, step=1)

    first_channel = selected_channels[0]
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"🔐 Для доступа нужно выполнить 4 простых действия:\n"
        f"1️⃣ Подписаться на канал\n"
        f"2️⃣ Подписаться на канал\n"
        f"3️⃣ Подписаться на канал\n"
        f"4️⃣ Запустить бота @VyruchaiCardBot (нажать /start)\n\n"
        f"**Шаг 1 из 4**\nПодпишись на этот канал:",
        reply_markup=channel_keyboard(first_channel, step_num=1, total=4)
    )

@dp.callback_query(F.data == "check_step")
async def handle_subscription_check(callback: CallbackQuery):
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name or ""

    if is_user_already_success(user_id):
        await callback.message.edit_text(
            f"✅ Вы уже получили доступ.",
            reply_markup=final_keyboard()
        )
        await callback.answer()
        return

    state = user_state.get(user_id)
    if not state:
        await callback.message.edit_text("❌ Ошибка. Напиши /start заново.")
        await callback.answer()
        return

    step = state["step"]
    channels = state["channels"]
    current = channels[step - 1]

    # Если текущий шаг — ручное подтверждение (маркер __MANUAL__)
    if current == "__MANUAL__":
        update_user_success(user_id)
        await callback.message.edit_text(
            f"🎉 Отлично, {first_name}!\n\n"
            f"Вы выполнили все условия (подписались на 3 канала и запустили @VyruchaiCardBot).\n\n"
            f"🔗 Нажмите кнопку ниже, чтобы перейти к основному боту:",
            reply_markup=final_keyboard()
        )
        if user_id in user_state:
            del user_state[user_id]
        await callback.answer("Доступ открыт!")
        return

    # Иначе это проверка подписки на канал
    if not await is_subscribed(user_id, current):
        await callback.answer(
            f"❌ {first_name}, вы не подписались на канал {current}. Подпишитесь и нажмите снова.",
            show_alert=True
        )
        return

    # Подписка подтверждена
    if step < len(channels):
        next_step = step + 1
        state["step"] = next_step
        update_user_step(user_id, next_step)
        next_item = channels[next_step - 1]

        if next_item == "__MANUAL__":
            # Переходим к ручному шагу
            await callback.message.edit_text(
                f"✅ Шаг {step} пройден!\n\n"
                f"🔐 **Шаг 4 из 4**\n"
                f"Теперь перейдите в бота @VyruchaiCardBot и нажмите /start, потом вернитесь и нажмите кнопку ниже.",
                reply_markup=vyruchai_keyboard()
            )
        else:
            await callback.message.edit_text(
                f"✅ Шаг {step} пройден!\n\n"
                f"🔐 Шаг {next_step} из {len(channels)}\n"
                f"Теперь подпишись на этот канал:",
                reply_markup=channel_keyboard(next_item, step_num=next_step, total=len(channels))
            )
        await callback.answer(f"Шаг {step} пройден!")
    else:
        # На всякий случай, если шагов больше нет (но у нас всегда есть ручной)
        update_user_success(user_id)
        await callback.message.edit_text(f"🎉 Доступ открыт! {FINAL_BOT_LINK}", reply_markup=final_keyboard())
        await callback.answer()

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
