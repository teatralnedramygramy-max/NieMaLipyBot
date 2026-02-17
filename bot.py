import os
import asyncio
import logging
import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- KONFIGURACJA ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Połączenie z bazą
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# --- FSM (Stany rozmowy) ---
class RateSeller(StatesGroup):
    waiting_for_username = State()
    waiting_for_q1 = State()
    waiting_for_q2 = State()
    waiting_for_q3 = State()
    waiting_for_q4 = State()
    waiting_for_comment = State()

# --- LOGIKA BIZNESOWA ---
def calculate_avg(seller_id):
    cur.execute("SELECT product_quality, delivery_time, communication, bhp FROM ratings WHERE seller_id=%s", (seller_id,))
    ratings = cur.fetchall()
    if not ratings: return 0
    
    total = 0
    for r in ratings:
        total += (r[0]*0.4 + r[1]*0.25 + r[2]*0.2 + r[3]*0.15)
    return round(total / len(ratings), 2)

def update_status(seller_id):
    cur.execute("SELECT rating_count, avg_rating, reports_count FROM sellers WHERE id=%s", (seller_id,))
    res = cur.fetchone()
    if not res: return
    count, avg, reports = res

    if reports >= 5: status = "⚫ Blacklisted"
    elif count < 5: status = "🆕 Nowy użytkownik"
    elif avg > 4.3: status = "🟢 Verified Safe"
    elif avg >= 3: status = "🟡 Caution"
    else: status = "🔴 High Risk"

    cur.execute("UPDATE sellers SET risk_status=%s WHERE id=%s", (status, seller_id))

# --- HANDLERY ---

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Oceń sprzedawcę", callback_data="rate")],
        [InlineKeyboardButton(text="🔍 Sprawdź sprzedawcę", callback_data="check_info")]
    ])
    await message.answer("Witaj w systemie weryfikacji sprzedawców!", reply_markup=kb)

@dp.callback_query(F.data == "rate")
async def start_rating(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(RateSeller.waiting_for_username)
    await callback.message.answer("Podaj @username sprzedawcy:")
    await callback.answer()

@dp.message(RateSeller.waiting_for_username)
async def process_username(message: types.Message, state: FSMContext):
    username = message.text.replace("@", "").strip()
    # Sprawdź lub stwórz sprzedawcę
    cur.execute("INSERT INTO sellers (username) VALUES (%s) ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING id", (username,))
    seller_id = cur.fetchone()[0]
    
    await state.update_data(seller_id=seller_id, username=username)
    await state.set_state(RateSeller.waiting_for_q1)
    await message.answer("🛍️ Jakość produktu (1-5):")

@dp.message(RateSeller.waiting_for_q1)
async def q1(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        return await message.answer("Wpisz cyfrę od 1 do 5!")
    
    await state.update_data(q1=int(message.text))
    await state.set_state(RateSeller.waiting_for_q2)
    await message.answer("⏱️ Czas realizacji (1-5):")

# ... (Tutaj analogicznie q2, q3, q4) ...

@dp.message(Command("check"))
async def check_cmd(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Użycie: /check @username")
    
    username = args[1].replace("@", "")
    cur.execute("SELECT username, avg_rating, rating_count, reports_count, risk_status FROM sellers WHERE username=%s", (username,))
    row = cur.fetchone()
    
    if not row:
        return await message.answer("Nie znaleziono takiego sprzedawcy w bazie.")

    await message.answer(
        f"👤 **Sprzedawca:** @{row[0]}\n"
        f"⭐ **Ocena:** {row[1]} ({row[2]} opinii)\n"
        f"🚨 **Zgłoszenia:** {row[3]}\n"
        f"🛡️ **Status:** {row[4]}",
        parse_mode="Markdown"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
