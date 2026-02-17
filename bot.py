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

cur.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    seller_id INT REFERENCES sellers(id),
    reporter_username TEXT,
    description TEXT,
    UNIQUE(seller_id, reporter_username)
);
""")

conn.commit()

weights = {
    "product_quality":0.4,
    "delivery_time":0.25,
    "communication":0.2,
    "bhp":0.15
}

def calculate_avg(ratings):
    total = 0
    for r in ratings:
        total += (
            r[0]*0.4 +
            r[1]*0.25 +
            r[2]*0.2 +
            r[3]*0.15
        )
    return round(total/len(ratings),2)

def update_status(seller_id):
    cur.execute("SELECT rating_count, avg_rating, reports_count FROM sellers WHERE id=%s",(seller_id,))
    rating_count, avg, reports = cur.fetchone()

    if reports >=5:
        status = "⚫ Blacklisted"
    elif rating_count <5:
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Oceń sprzedawcę", callback_data="rate")],
        [InlineKeyboardButton(text="🚨 Zgłoś sprzedawcę", callback_data="report")],
        [InlineKeyboardButton(text="🔍 Sprawdź sprzedawcę", callback_data="check")],
        [InlineKeyboardButton(text="🏆 TOP sprzedawców", callback_data="top")]
    ])
    await message.answer("Wybierz opcję:", reply_markup=kb)

# --- CALLBACK MENU ---
@dp.callback_query()
async def menu(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if callback.data == "rate":
        user_state[uid] = {"step":"username"}
        await callback.message.answer("Podaj @username sprzedawcy")

    elif callback.data == "report":
        user_state[uid] = {"step":"report_username"}
        await callback.message.answer("Podaj @username sprzedawcy")

    elif callback.data == "check":
        await callback.message.answer("Użyj komendy: /check @username")

    elif callback.data == "top":
        cur.execute("SELECT username, avg_rating, rating_count FROM sellers ORDER BY avg_rating DESC LIMIT 5")
        rows = cur.fetchall()
        text="🏆 TOP 5 sprzedawców:\n"
        for i,r in enumerate(rows,1):
            text += f"{i}. @{r[0]} ⭐ {r[1]} ({r[2]} opinii)\n"
        await callback.message.answer(text)

# --- CHECK ---
@dp.message(Command("check"))
async def check(message: types.Message):
    username = message.text.split()[1]
    cur.execute("SELECT username, avg_rating, rating_count, reports_count, risk_status FROM sellers WHERE username=%s",(username,))
    row = cur.fetchone()
    if not row:
        await message.answer("Brak sprzedawcy")
        return

    await message.answer(
        f"Sprzedawca: @{row[0]}\n"
        f"Ocena: ⭐ {row[1]} ({row[2]} opinii)\n"
        f"Zgłoszenia: {row[3]}\n"
        f"Status: {row[4]}"
    )

# --- FLOW ---
@dp.message()
async def flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state:
        return

    state = user_state[uid]
    text = message.text.strip()

    # RATE FLOW
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
        state["q2"]=int(text)
        state["step"]="q3"
        await message.answer("🤙 Komunikacja 1-5")

    elif state["step"]=="q3":
        state["q3"]=int(text)
        state["step"]="q4"
        await message.answer("🚨 BHP 1-5")

    elif state["step"]=="q4":
        state["q4"]=int(text)
        state["step"]="comment"
        await message.answer("Komentarz lub -")

    elif state["step"]=="comment":
        try:
            cur.execute("""
            INSERT INTO ratings (seller_id, reviewer_username, product_quality, delivery_time, communication, bhp, comment)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,(state["seller_id"], message.from_user.username,
                 state["q1"], state["q2"], state["q3"], state["q4"], text))
        except:
            await message.answer("Już oceniałeś tego sprzedawcę")
            user_state.pop(uid)
            return

        cur.execute("SELECT product_quality,delivery_time,communication,bhp FROM ratings WHERE seller_id=%s",(state["seller_id"],))
        ratings=cur.fetchall()
        avg=calculate_avg(ratings)

        cur.execute("UPDATE sellers SET avg_rating=%s, rating_count=%s WHERE id=%s",
                    (avg,len(ratings),state["seller_id"]))
        conn.commit()

        update_status(state["seller_id"])

        await message.answer(
            f"✅ Dziękujemy, ocena dodana!\n\n"
            f"Profil @{state['username']}:\n"
            f"⭐ {avg} ({len(ratings)} opinii)"
        )
        user_state.pop(uid)

# --- RUN ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
