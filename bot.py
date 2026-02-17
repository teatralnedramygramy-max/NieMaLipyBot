import os
import asyncio
import logging
import psycopg2
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# Pobieranie zmiennych środowiskowych
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Sprawdzenie czy zmienne istnieją
if not BOT_TOKEN or not DATABASE_URL:
    raise ValueError("Brak BOT_TOKEN lub DATABASE_URL w zmiennych środowiskowych!")

# Inicjalizacja bota i dispatchera
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Połączenie z bazą (psycopg2)
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True # Automatycznie zapisuje zmiany (COMMIT)
cur = conn.cursor()

# -------------------- TWORZENIE TABEL --------------------

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sellers (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        avg_rating FLOAT DEFAULT 0,
        rating_count INT DEFAULT 0,
        reports_count INT DEFAULT 0,
        risk_status TEXT DEFAULT '🆕 Nowy użytkownik'
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        id SERIAL PRIMARY KEY,
        seller_id INT REFERENCES sellers(id),
        reviewer_username TEXT,
        product_quality INT,
        delivery_time INT,
        communication INT
    );
    """)

# -------------------- HANDLERY --------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Witaj w systemie ocen sprzedawców!")

# -------------------- URUCHOMIENIE --------------------

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()  # Inicjalizacja bazy przy starcie
    print("Bot i baza danych gotowe!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        cur.close()
        conn.close()
