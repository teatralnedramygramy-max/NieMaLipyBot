import os
import asyncio
from flask import Flask
import threading
import psycopg2
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # Twój Render DB URL

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- FLASK KEEP ALIVE ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

# --- DATABASE ---
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS sellers (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    city TEXT NOT NULL,
    description TEXT,
    telegram_user_id BIGINT,
    avg_rating FLOAT DEFAULT 0,
    rating_count INT DEFAULT 0,
    reports_count INT DEFAULT 0,
    risk_status TEXT DEFAULT 'LOW',
    created_at TIMESTAMP DEFAULT NOW()
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    id SERIAL PRIMARY KEY,
    seller_id INT REFERENCES sellers(id),
    user_id BIGINT,
    rating INT,
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(seller_id, user_id)
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    seller_id INT REFERENCES sellers(id),
    user_id BIGINT,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(seller_id, user_id)
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS legit_checks (
    id SERIAL PRIMARY KEY,
    seller_id INT REFERENCES sellers(id),
    buyer_id BIGINT,
    rating_id INT REFERENCES ratings(id),
    confirmed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
""")

conn.commit()

# --- HELPERS ---
def update_risk(reports_count):
    if reports_count >= 5:
        return "HIGH"
    if reports_count >= 2:
        return "MEDIUM"
    return "LOW"

# --- STATE ---
user_state = {}

# --- COMMANDS ---
@dp.message(Command(commands=['start','help']))
async def start(message: types.Message):
    await message.answer(
        "Komendy:\n"
        "/dodaj_sprzedawce – zarejestruj siebie lub sprzedawcę\n"
        "/ocen – oceń sprzedawcę\n"
        "/zglos – zgłoś problem\n"
        "/sprawdz @nick – sprawdź sprzedawcę\n"
        "/zweryfikuj – sprzedawca potwierdza konto"
    )

# --- ADD SELLER ---
@dp.message(Command(commands=['dodaj_sprzedawce']))
async def add_seller_start(message: types.Message):
    user_state[message.from_user.id] = {"step":"username"}
    await message.answer("Podaj @username sprzedawcy")

@dp.message()
async def add_seller_flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state:
        return

    step = user_state[uid]["step"]

    if step=="username":
        username = message.text.strip()
        cur.execute("SELECT id FROM sellers WHERE username=%s",(username,))
        if cur.fetchone():
            await message.answer("Ten sprzedawca już istnieje.")
            user_state.pop(uid)
            return
        user_state[uid]["username"]=username
        user_state[uid]["step"]="city"
        await message.answer("Podaj miasto działania sprzedawcy")

    elif step=="city":
        user_state[uid]["city"]=message.text.strip()
        user_state[uid]["step"]="description"
        await message.answer("Podaj krótki opis sprzedawcy")

    elif step=="description":
        data = user_state.pop(uid)
        cur.execute(
            "INSERT INTO sellers (username, city, description) VALUES (%s,%s,%s)",
            (data["username"], data["city"], message.text.strip())
        )
        conn.commit()
        await message.answer("✅ Sprzedawca dodany.")

# --- VERIFY SELLER ---
@dp.message(Command(commands=['zweryfikuj']))
async def verify_seller(message: types.Message):
    user_state[message.from_user.id] = {"step":"verify_username"}
    await message.answer("Podaj swój @username")

# Flow verify
@dp.message()
async def verify_flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state or user_state[uid]["step"]!="verify_username":
        return
    username = message.text.strip()
    cur.execute("SELECT id FROM sellers WHERE username=%s",(username,))
    row = cur.fetchone()
    if not row:
        await message.answer("Nie ma takiego sprzedawcy w bazie.")
        user_state.pop(uid)
        return
    seller_id = row[0]
    cur.execute("UPDATE sellers SET telegram_user_id=%s WHERE id=%s",(uid,seller_id))
    conn.commit()
    user_state.pop(uid)
    await message.answer("✅ Konto zweryfikowane. Teraz możesz otrzymywać Legit Check!")

# --- RATE ---
@dp.message(Command(commands=['ocen']))
async def rate_start(message: types.Message):
    user_state[message.from_user.id]={"step":"rate_username"}
    await message.answer("Podaj @username sprzedawcy")

@dp.message()
async def rate_flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state:
        return
    step = user_state[uid]["step"]

    if step=="rate_username":
        cur.execute("SELECT id,telegram_user_id FROM sellers WHERE username=%s",(message.text.strip(),))
        row = cur.fetchone()
        if not row:
            await message.answer("Nie ma takiego sprzedawcy.")
            user_state.pop(uid)
            return
        user_state[uid]["seller_id"]=row[0]
        user_state[uid]["seller_telegram_id"]=row[1]
        user_state[uid]["step"]="rate_value"
        await message.answer("Podaj ocenę 1–5")

    elif step=="rate_value":
        try:
            rating=int(message.text.strip())
            if rating<1 or rating>5: raise ValueError
        except:
            await message.answer("Podaj liczbę 1–5")
            return
        user_state[uid]["rating"]=rating
        user_state[uid]["step"]="rate_comment"
        await message.answer("Dodaj komentarz (albo wpisz -)")

    elif step=="rate_comment":
        data = user_state.pop(uid)
        try:
            cur.execute(
                "INSERT INTO ratings (seller_id,user_id,rating,comment) VALUES (%s,%s,%s,%s) RETURNING id",
                (data["seller_id"], uid, data["rating"], message.text.strip())
            )
            rating_id = cur.fetchone()[0]
            # update seller
            cur.execute("""
                UPDATE sellers SET rating_count=rating_count+1,
                avg_rating=((avg_rating*rating_count)+%s)/(rating_count+1) WHERE id=%s
            """,(data["rating"],data["seller_id"]))
            conn.commit()
            await message.answer("✅ Opinia zapisana.")

            # send legit check
            if data["seller_telegram_id"]:
                kb = InlineKeyboardMarkup().add(
                    InlineKeyboardButton("✅ Legit Check", callback_data=f"legit_{rating_id}")
                )
                await bot.send_message(data["seller_telegram_id"],
                    f"Zostałeś oceniony przez @{message.from_user.username}. Potwierdź transakcję:",
                    reply_markup=kb
                )
        except:
            await message.answer("Już oceniałeś tego sprzedawcę.")

# --- LEGIT CHECK ---
@dp.callback_query(lambda c: c.data.startswith("legit_"))
async def legit_check(callback: types.CallbackQuery):
    rating_id = int(callback.data.split("_")[1])
    cur.execute("SELECT seller_id,buyer_id FROM ratings WHERE id=%s",(rating_id,))
    row = cur.fetchone()
    if row:
        seller_id,buyer_id = row
        cur.execute("INSERT INTO legit_checks (seller_id,buyer_id,rating_id,confirmed) VALUES (%s,%s,%s,TRUE)",
                    (seller_id,buyer_id,rating_id))
        conn.commit()
        await callback.answer("Potwierdzono transakcję!")
        await bot.send_message(buyer_id,"✅ Sprzedawca potwierdził udaną transakcję.")

# --- REPORT ---
@dp.message(Command(commands=['zglos']))
async def report_start(message: types.Message):
    user_state[message.from_user.id]={"step":"report_username"}
    await message.answer("Podaj @username sprzedawcy")

@dp.message()
async def report_flow(message: types.Message):
    uid = message.from_user.id
    if uid not in user_state:
        return
    step=user_state[uid]["step"]
    if step=="report_username":
        cur.execute("SELECT id,reports_count FROM sellers WHERE username=%s",(message.text.strip(),))
        row=cur.fetchone()
        if not row:
            await message.answer("Nie ma takiego sprzedawcy.")
            user_state.pop(uid)
            return
        user_state[uid]["seller_id"]=row[0]
        user_state[uid]["step"]="report_desc"
        await message.answer("Opisz krótko problem")
    elif step=="report_desc":
        data=user_state.pop(uid)
        try:
            cur.execute("INSERT INTO reports (seller_id,user_id,description) VALUES (%s,%s,%s)",
                        (data["seller_id"],uid,message.text.strip()))
            cur.execute("UPDATE sellers SET reports_count=reports_count+1 WHERE id=%s",(data["seller_id"],))
            cur.execute("SELECT reports_count FROM sellers WHERE id=%s",(data["seller_id"],))
            reports_count = cur.fetchone()[0]
            risk = update_risk(reports_count)
            cur.execute("UPDATE sellers SET risk_status=%s WHERE id=%s",(risk,data["seller_id"]))
            conn.commit()
            await message.answer("🚨 Zgłoszenie zapisane.")
        except:
            await message.answer("Już zgłaszałeś tego sprzedawcę.")

# --- CHECK ---
@dp.message(Command(commands=['sprawdz']))
async def check_seller(message: types.Message):
    parts = message.text.split()
    if len(parts)!=2:
        await message.answer("Użycie: /sprawdz @nick")
        return
    username = parts[1].strip()
    cur.execute("SELECT username,city,avg_rating,rating_count,reports_count,risk_status FROM sellers WHERE username=%s",(username,))
    row = cur.fetchone()
    if not row:
        await message.answer("❌ Nie znaleziono sprzedawcy.")
        return
    await message.answer(
        f"Sprzedawca: {row[0]}\n"
        f"Miasto: {row[1]}\n"
        f"Ocena: ⭐ {round(row[2],2)} ({row[3]} opinii)\n"
        f"Zgłoszenia: {row[4]}\n"
        f"Ryzyko: {row[5]}"
    )

# --- RUN ---
if __name__=="__main__":
    keep_alive()
    asyncio.run(dp.start_polling(bot))