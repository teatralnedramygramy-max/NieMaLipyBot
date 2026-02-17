import os
import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

# --- KONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# --- MENU ---
keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("➕ Dodaj sprzedawcę")],
        [KeyboardButton("⭐ Oceń sprzedawcę")],
        [KeyboardButton("🔍 Sprawdź sprzedawcę")],
        [KeyboardButton("👤 Sprawdź klienta")],
        [KeyboardButton("🏆 TOP sprzedawców")]
    ],
    resize_keyboard=True
)

# --- POŁĄCZENIE Z BAZĄ ---
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# --- START ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("Wybierz opcję:", reply_markup=keyboard)

# --- HANDLERY MENU ---
@dp.message_handler()
async def handle_message(message: types.Message):
    text = message.text.strip()

    if text == "➕ Dodaj sprzedawcę":
        await message.answer("Podaj @username sprzedawcy:")
        dp.register_message_handler(add_seller, state=None)
    elif text == "⭐ Oceń sprzedawcę":
        await message.answer("Podaj @username sprzedawcy, którego chcesz ocenić:")
        dp.register_message_handler(rate_seller, state=None)
    elif text == "🔍 Sprawdź sprzedawcę":
        await message.answer("Użyj komendy: /check @username")
    elif text == "👤 Sprawdź klienta":
        await message.answer("Podaj @username klienta:")
        dp.register_message_handler(check_client, state=None)
    elif text == "🏆 TOP sprzedawców":
        await show_top_sellers(message)
    else:
        await message.answer("Nie rozumiem. Wybierz opcję z menu.")

# --- FUNKCJE BOT ---
async def add_seller(message: types.Message):
    username = message.text.strip().lstrip("@")
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sellers (username, rating, reviews, reports, status) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
            (username, 0, 0, 0, "NEW")
        )
        conn.commit()
        cur.close()
        conn.close()
        await message.answer(f"Sprzedawca @{username} dodany ✅")
    except Exception as e:
        await message.answer(f"Błąd: {e}")

async def rate_seller(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Podaj w formacie: @username ocena (np. @user 5)")
        return

    username = parts[0].lstrip("@")
    try:
        rating = float(parts[1])
        if rating < 1 or rating > 5:
            raise ValueError
    except ValueError:
        await message.answer("Ocena musi być liczbą od 1 do 5")
        return

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT rating, reviews FROM sellers WHERE username=%s", (username,))
        seller = cur.fetchone()
        if not seller:
            await message.answer("Nie znaleziono sprzedawcy")
            return
        new_reviews = seller["reviews"] + 1
        new_rating = (seller["rating"] * seller["reviews"] + rating) / new_reviews
        cur.execute(
            "UPDATE sellers SET rating=%s, reviews=%s WHERE username=%s",
            (new_rating, new_reviews, username)
        )
        conn.commit()
        cur.close()
        conn.close()
        await message.answer(f"Ocena zaktualizowana ✅ Nowa średnia: {new_rating:.1f} ({new_reviews} opinii)")
    except Exception as e:
        await message.answer(f"Błąd: {e}")

async def check_client(message: types.Message):
    username = message.text.strip().lstrip("@")
    # tutaj możesz dodać logikę sprawdzania klienta
    await message.answer(f"Klient @{username} sprawdzony (przykład)")

async def show_top_sellers(message: types.Message):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT username, rating, reviews FROM sellers ORDER BY rating DESC LIMIT 5")
        sellers = cur.fetchall()
        cur.close()
        conn.close()
        if not sellers:
            await message.answer("Brak sprzedawców w bazie.")
            return
        text = "🏆 TOP 5 sprzedawców:\n"
        for i, s in enumerate(sellers, 1):
            text += f"{i}. @{s['username']} ⭐ {s['rating']:.1f} ({s['reviews']} opinii)\n"
        await message.answer(text)
    except Exception as e:
        await message.answer(f"Błąd: {e}")

# --- START ---
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
