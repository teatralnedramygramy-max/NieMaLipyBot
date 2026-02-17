import os
import asyncio
import logging
import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- KONFIGURACJA ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Połączenie z bazą danych
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# --- DEFINICJE KLAWIATUR (MENU) ---

# Menu główne (zawsze na dole)
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 Oceń sprzedawcę"), KeyboardButton(text="🔍 Sprawdź sprzedawcę")],
        [KeyboardButton(text="🏆 TOP 5"), KeyboardButton(text="ℹ️ Pomoc")]
    ],
    resize_keyboard=True,
    persistent=True
)

# Menu anulowania (widoczne w trakcie wypełniania formularza)
cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Anuluj")]],
    resize_keyboard=True
)

# --- STAN FSM (MASZYNA STANÓW) ---
class RateSeller(StatesGroup):
    waiting_for_username = State()
    waiting_for_q1 = State()
    waiting_for_q2 = State()
    waiting_for_q3 = State()
    waiting_for_q4 = State()
    waiting_for_comment = State()

class CheckSeller(StatesGroup):
    waiting_for_check_username = State()

# --- LOGIKA BIZNESOWA ---

def update_seller_stats(seller_id):
    """Przelicza średnią ważoną i aktualizuje status sprzedawcy."""
    cur.execute("SELECT product_quality, delivery_time, communication, bhp FROM ratings WHERE seller_id=%s", (seller_id,))
    ratings = cur.fetchall()
    
    if not ratings:
        return

    # Wagi: Jakość (0.4), Czas (0.25), Kontakt (0.2), BHP (0.15)
    total_score = 0
    for r in ratings:
        score = (r[0]*0.4) + (r[1]*0.25) + (r[2]*0.2) + (r[3]*0.15)
        total_score += score
    
    final_avg = round(total_score / len(ratings), 2)
    
    cur.execute("SELECT reports_count FROM sellers WHERE id=%s", (seller_id,))
    reports = cur.fetchone()[0]

    # Logika statusów
    if reports >= 5: status = "⚫ Blacklisted"
    elif len(ratings) < 3: status = "🆕 Nowy użytkownik"
    elif final_avg > 4.5: status = "🟢 Verified Safe"
    elif final_avg >= 3: status = "🟡 Caution"
    else: status = "🔴 High Risk"

    cur.execute("""
        UPDATE sellers SET avg_rating=%s, rating_count=%s, risk_status=%s WHERE id=%s
    """, (final_avg, len(ratings), status, seller_id))

# --- HANDLERY GLOBALNE ---

@dp.message(CommandStart())
@dp.message(F.text == "❌ Anuluj")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Witaj w systemie **Bez Lipy**!\n\n"
        "Wybierz opcję z menu poniżej, aby zacząć.",
        reply_markup=main_menu_kb,
        parse_mode="Markdown"
    )

# --- HANDLER: SPRAWDZANIE SPRZEDAWCY ---

@dp.message(F.text == "🔍 Sprawdź sprzedawcę")
@dp.message(Command("check"))
async def check_start(message: types.Message, state: FSMContext):
    await state.set_state(CheckSeller.waiting_for_check_username)
    await message.answer("Wpisz @username sprzedawcy, którego chcesz sprawdzić:", reply_markup=cancel_kb)

@dp.message(CheckSeller.waiting_for_check_username)
async def process_check(message: types.Message, state: FSMContext):
    username = message.text.replace("@", "").strip().lower()
    cur.execute("SELECT username, avg_rating, rating_count, reports_count, risk_status FROM sellers WHERE username=%s", (username,))
    row = cur.fetchone()
    
    await state.clear()
    if not row:
        await message.answer(f"❌ Sprzedawca @{username} nie widnieje w naszej bazie.", reply_markup=main_menu_kb)
    else:
        await message.answer(
            f"👤 **Profil:** @{row[0]}\n"
            f"⭐ **Ocena:** {row[1]}/5.0 ({row[2]} opinii)\n"
            f"⚠️ **Zgłoszenia:** {row[3]}\n"
            f"🛡️ **Status:** {row[4]}",
            reply_markup=main_menu_kb,
            parse_mode="Markdown"
        )

# --- HANDLER: PROCES OCENIANIA ---

@dp.message(F.text == "🛒 Oceń sprzedawcę")
async def rate_start(message: types.Message, state: FSMContext):
    await state.set_state(RateSeller.waiting_for_username)
    await message.answer("Podaj @username sprzedawcy, którego oceniasz:", reply_markup=cancel_kb)

@dp.message(RateSeller.waiting_for_username)
async def rate_username(message: types.Message, state: FSMContext):
    username = message.text.replace("@", "").strip().lower()
    cur.execute("INSERT INTO sellers (username) VALUES (%s) ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING id", (username,))
    seller_id = cur.fetchone()[0]
    
    await state.update_data(seller_id=seller_id, username=username)
    await state.set_state(RateSeller.waiting_for_q1)
    await message.answer("🛍️ **Jakość produktu** (1-5):", parse_mode="Markdown")

@dp.message(RateSeller.waiting_for_q1)
async def rate_q1(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        return await message.answer("Wpisz cyfrę od 1 do 5!")
    await state.update_data(q1=int(message.text))
    await state.set_state(RateSeller.waiting_for_q2)
    await message.answer("⏱️ **Czas realizacji** (1-5):", parse_mode="Markdown")

@dp.message(RateSeller.waiting_for_q2)
async def rate_q2(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        return await message.answer("Wpisz cyfrę od 1 do 5!")
    await state.update_data(q2=int(message.text))
    await state.set_state(RateSeller.waiting_for_q3)
    await message.answer("📞 **Komunikacja** (1-5):", parse_mode="Markdown")

@dp.message(RateSeller.waiting_for_q3)
async def rate_q3(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        return await message.answer("Wpisz cyfrę od 1 do 5!")
    await state.update_data(q3=int(message.text))
    await state.set_state(RateSeller.waiting_for_q4)
    await message.answer("🛡️ **BHP / Bezpieczeństwo** (1-5):", parse_mode="Markdown")

@dp.message(RateSeller.waiting_for_q4)
async def rate_q4(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        return await message.answer("Wpisz cyfrę od 1 do 5!")
    await state.update_data(q4=int(message.text))
    await state.set_state(RateSeller.waiting_for_comment)
    await message.answer("📝 Dodaj krótki **komentarz**:", parse_mode="Markdown")

@dp.message(RateSeller.waiting_for_comment)
async def rate_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        cur.execute("""
            INSERT INTO ratings (seller_id, reviewer_username, product_quality, delivery_time, communication, bhp, comment)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (data['seller_id'], message.from_user.username, data['q1'], data['q2'], data['q3'], data['q4'], message.text))
        
        update_seller_stats(data['seller_id'])
        await message.answer(f"✅ Dodano opinię dla @{data['username']}!", reply_markup=main_menu_kb)
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        await message.answer("❌ Już wcześniej oceniałeś tego sprzedawcę.", reply_markup=main_menu_kb)
    
    await state.clear()

# --- HANDLERY DODATKOWE ---

@dp.message(F.text == "🏆 TOP 5")
async def show_top(message: types.Message):
    cur.execute("SELECT username, avg_rating, rating_count FROM sellers WHERE rating_count > 0 ORDER BY avg_rating DESC LIMIT 5")
    rows = cur.fetchall()
    if not rows:
        return await message.answer("Baza jest jeszcze pusta.")
    
    text = "🏆 **Ranking najlepiej ocenianych:**\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. @{r[0]} — ⭐ {r[1]} ({r[2]} opinii)\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "ℹ️ Pomoc")
async def show_help(message: types.Message):
    await message.answer(
        "📖 **Instrukcja:**\n\n"
        "1. Kliknij 'Oceń', aby dodać opinię (możesz to zrobić tylko raz dla jednego sprzedawcy).\n"
        "2. Kliknij 'Sprawdź', aby zweryfikować kogoś przed zakupem.\n"
        "3. System wylicza średnią na podstawie jakości, czasu dostawy i kontaktu.",
        reply_markup=main_menu_kb,
        parse_mode="Markdown"
    )

# --- START BOT ---
async def main():
    print("Bot Bez Lipy wystartował!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        cur.close()
        conn.close()
