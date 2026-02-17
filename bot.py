import os
import asyncio
import psycopg2
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# --- TABLES ---
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
    communication INT,
    bhp INT,
    comment TEXT,
    UNIQUE(seller_id, reviewer_username)
);
""")

conn.commit()

# --- MENU ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Oceń sprzedawcę", callback_data="rate")],
        [InlineKeyboardButton(text="🔍 Sprawdź sprzedawcę", callback_data="check")],
        [InlineKeyboardButton(text="🏆 TOP sprzedawców", callback_data="top")]
    ])

# --- HELPERS ---
def calculate_avg(ratings):
    total = 0
    for r in ratings:
        total += (r[0]*0.4 + r[1]*0.25 + r[2]*0.2 + r[3]*0.15)
    return round(total/len(ratings),2)

def update_status(seller_id):
    cur.execute("SELECT rating_count, avg_rating FROM sellers WHERE id=%s",(seller_id,))
    rating_count, avg = cur.fetchone()

    if rating_count <5:
        status = "🆕 Nowy użytkownik"
    elif avg >4.3:
        status = "🟢 Verified Safe"
    elif avg >=3:
        status = "🟡 Caution"
    else:
        status = "🔴 High Risk"

    cur.execute("UPDATE sellers SET risk_status=%s WHERE id=%s",(status,seller_id))
    conn.commit()

user_state = {}

# --- START ---
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("📊 Panel reputacji\n\nWybierz opcję:", reply_markup=main_menu())

# --- CALLBACK ---
@dp.callback_query()
async def menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    await callback.answer()

    if callback.data == "rate":
        user_state[uid] = {"step":"username"}
        await callback.message.edit_text("Podaj @username sprzedawcy:", reply_markup=None)

    elif callback.data == "check":
        user_state[uid] = {"step":"check_username"}
        await callback.message.edit_text("Podaj @username do sprawdzenia:", reply_markup=None)

    elif callback.data == "top":
        cur.execute("SELECT username, avg_rating, rating_count FROM sellers ORDER BY avg_rating DESC LIMIT 5")
        rows = cur.fetchall()
        text="🏆 TOP 5 sprzedawców:\n\n"
        for i,r in enumerate(rows,1):
            text += f"{i}. @{r[0]} ⭐ {r[1]} ({r[2]} opinii)\n"

        await callback.message.edit_text(text, reply_markup=main_menu())

# --- FLOW ---
@dp.message()
async def flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state:
        return

    state = user_state[uid]
    text = message.text.strip()

    # --- CHECK ---
    if state["step"]=="check_username":
        cur.execute("SELECT username, avg_rating, rating_count, risk_status FROM sellers WHERE username=%s",(text,))
        row = cur.fetchone()

        if not row:
            await message.answer("Brak sprzedawcy", reply_markup=main_menu())
        else:
            await message.answer(
                f"Sprzedawca: @{row[0]}\n"
                f"⭐ {row[1]} ({row[2]} opinii)\n"
                f"Status: {row[3]}",
                reply_markup=main_menu()
            )
        user_state.pop(uid)
        return

    # --- RATE FLOW ---
    if state["step"]=="username":
        cur.execute("SELECT id FROM sellers WHERE username=%s",(text,))
        row = cur.fetchone()
        if row:
            seller_id=row[0]
        else:
            cur.execute("INSERT INTO sellers (username) VALUES (%s) RETURNING id",(text,))
            seller_id=cur.fetchone()[0]
            conn.commit()

        state.update({"seller_id":seller_id,"username":text,"step":"q1"})
        await message.answer("🛍️ Jakość produktu 1-5")

    elif state["step"]=="q1":
        state["q1"]=int(text)
        state["step"]="q2"
        await message.answer("⏱️ Czas realizacji 1-5")

 elif state["step"]=="q2":
    try:
    state["q2"]=int(text)
except:
    await message.answer("Podaj liczbę od 1 do 5")
    return
    state["step"]="q3"
    await message.answer("📦 Zgodność z opisem 1-5")
