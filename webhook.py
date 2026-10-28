import asyncio
from datetime import datetime
import aiosqlite
from flask import Flask, request
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, Update
from aiogram.enums import ParseMode
BOT_TOKEN = "8814886432:AAGg7JG5-JghTl0BxoxpDG0Ni5rhF4WGE6k"
ADMIN_IDS = [93372553, 7196958222]
DB_PATH = "/tmp/davomat.db"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = Flask(__name__)
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS davomat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                full_name TEXT,
                status TEXT,
                date TEXT,
                group_id INTEGER
            )
        """)
        await db.commit()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.message(Command("start"))
async def start(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "Assalomu alaykum, Admin!\n\n"
            "Buyruqlar:\n"
            "/davomat — davomatni boshlash\n"
            "/hisobot — bugungi natijalarni ko‘rish"
        )
    else:
        await message.answer("Bu bot faqat admin boshqaruvida ishlaydi.")

@dp.message(Command("davomat"))
async def start_attendance(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Bu buyruq faqat admin uchun.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Keldi", callback_data="status:keldi"),
            InlineKeyboardButton(text="❌ Kelmadi", callback_data="status:kelmadi")
        ],
        [
            InlineKeyboardButton(text="🕐 Kechikdi", callback_data="status:kechikdi")
        ]
    ])

    await message.answer(
        f"📋 <b>Davomat boshlandi</b>\n"
        f"Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"O‘quvchilar holatini tanlasin.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("status:"))
async def process_status(callback: CallbackQuery):
    status = callback.data.split(":")[1]
    user = callback.from_user
    date = datetime.now().strftime("%Y-%m-%d")

    status_text = {
        "keldi": "✅ Keldi",
        "kelmadi": "❌ Kelmadi",
        "kechikdi": "🕐 Kechikdi"
    }.get(status, status)

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO davomat (user_id, full_name, status, date, group_id) VALUES (?, ?, ?, ?, ?)",
            (user.id, user.full_name, status_text, date, callback.message.chat.id)
        )
        await db.commit()

    await callback.answer(f"Qabul qilindi: {status_text}")

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📥 Yangi belgi:\n\n"
                f"👤 {user.full_name}\n"
                f"📊 {status_text}\n"
                f"🕐 {datetime.now().strftime('%H:%M')}"
            )
        except:
            pass

@dp.message(Command("hisobot"))
async def report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Faqat admin ko‘ra oladi.")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, status FROM davomat WHERE date = ? ORDER BY id",
            (today,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Bugun hali hech kim belgilamagan.")
        return

    text = f"📊 <b>Bugungi davomat</b> ({today})\n\n"
    for name, status in rows:
        text += f"• {name} — {status}\n"

    await message.answer(text, parse_mode=ParseMode.HTML)

# --- Flask Webhook Handler ---
@app.route("/api/webhook", methods=["POST"])
def webhook():
    json_data = request.get_json()
    if json_data:
        update = Update.model_validate(json_data, context={"bot": bot})
        asyncio.run(dp.feed_update(bot, update))
    return {"ok": True}

@app.route("/", methods=["GET"])
def index():
    return {"status": "Bot is running via Flask Webhook on Vercel!"}
