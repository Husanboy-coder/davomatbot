import os
import traceback
from datetime import datetime, timezone, timedelta
import aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Message, 
    CallbackQuery, 
    BotCommand
)
from aiogram.enums import ParseMode

# Load secrets securely from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

# Parse admin IDs from environment (comma-separated string)
admin_ids_env = os.getenv("ADMIN_IDS", "93372553,7196958222")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(",") if x.strip()]

DB_PATH = "/tmp/davomat.db"

# Uzbekistan time zone (UTC+5)
TASHKENT_TZ = timezone(timedelta(hours=5))

def get_now() -> datetime:
    return datetime.now(TASHKENT_TZ)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS davomat (
                user_id INTEGER,
                date TEXT,
                full_name TEXT,
                status TEXT,
                group_id INTEGER,
                photo_file_id TEXT,
                verified TEXT DEFAULT 'none',
                PRIMARY KEY (user_id, date)
            )
        """)
        await db.commit()

@app.on_event("startup")
async def startup_event():
    await init_db()
    commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="davomat", description="Guruhga davomat e'lon qilish (Admin)"),
        BotCommand(command="hisobot", description="Bugungi natijalarni ko'rish (Admin)")
    ]
    await bot.set_my_commands(commands)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- 1. ADMIN COMMAND: Announce Attendance in Group with Deep Link ---
@dp.message(Command("davomat"))
async def start_attendance(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Bu buyruq faqat admin uchun.")
        return

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👉 Botga o'tish va davomat berish", 
                url=f"https://t.me/{bot_username}?start=davomat"
            )
        ]
    ])

    date_str = get_now().strftime('%d.%m.%Y %H:%M')

    await message.answer(
        f"📋 <b>Davomat boshlandi!</b>\n"
        f"Sana: {date_str}\n\n"
        f"Guruhni toza saqlash uchun iltimos quyidagi tugmani bosib, bot orqali davomatingizni belgilang.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

# --- 2. START HANDLER ---
@dp.message(Command("start"))
async def start(message: Message, command: CommandObject):
    user = message.from_user
    date = get_now().strftime("%Y-%m-%d")

    if command.args == "davomat":
        await init_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT verified FROM davomat WHERE user_id = ? AND date = ?", 
                (user.id, date)
            ) as cursor:
                row = await cursor.fetchone()

        if row and row[0] in ["approved", "pending_admin"]:
            await message.answer("⚠️ Siz bugun allaqachon davomat topshirgansiz yoki tasdiqlanishi kutilmoqda.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Keldi", callback_data="opt:keldi"),
                InlineKeyboardButton(text="❌ Kelmadi", callback_data="opt:kelmadi")
            ],
            [
                InlineKeyboardButton(text="🕐 Kechikdi", callback_data="opt:kechikdi")
            ]
        ])

        await message.answer(
            "📋 <b>Davomat uchun holatingizni tanlang:</b>", 
            reply_markup=keyboard, 
            parse_mode=ParseMode.HTML
        )
        return

    if is_admin(user.id):
        await message.answer(
            "Assalomu alaykum, Admin!\n\n"
            "Buyruqlar:\n"
            "/davomat — guruhga davomat e'lon qilish\n"
            "/hisobot — bugungi natijalarni ko‘rish"
        )
    else:
        await message.answer(
            "Assalomu alaykum!\n"
            "Davomat berish uchun Telegram guruhdagi **'Botga o'tish va davomat berish'** tugmasini bosing."
        )

# --- 3. OPTION SELECTION & CONFIRMATION ---
@dp.callback_query(F.data.startswith("opt:"))
async def process_option(callback: CallbackQuery):
    option = callback.data.split(":")[1]
    user = callback.from_user
    date = get_now().strftime("%Y-%m-%d")

    await init_db()

    if option == "kelmadi":
        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, Kelmadi", callback_data="conf:kelmadi:yes"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="conf:kelmadi:no")
            ]
        ])
        await callback.message.edit_text(
            "⚠️ Haqiqatan ham **Kelmadi** deb belgilamoqchimisiz?",
            reply_markup=confirm_keyboard,
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
    else:
        status_placeholder = f"⏳ {option.capitalize()} (Selfe kutilmoqda)"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO davomat (user_id, date, full_name, status, group_id, verified) 
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, date) DO UPDATE SET 
                   status=excluded.status, verified='awaiting_photo', full_name=excluded.full_name""",
                (user.id, date, user.full_name, status_placeholder, callback.message.chat.id, f"awaiting_photo_{option}")
            )
            await db.commit()

        await callback.answer("Holat tanlandi. Endi selfeingizni yuboring!")
        await callback.message.edit_text(
            f"📸 <b>{user.full_name}</b>, iltimos o'zingizning hozirgi **selfie rasmingizni** chatga yuboring.",
            parse_mode=ParseMode.HTML
        )

# --- 4. KELMADI CONFIRMATION ---
@dp.callback_query(F.data.startswith("conf:kelmadi:"))
async def confirm_kelmadi(callback: CallbackQuery):
    action = callback.data.split(":")[2]
    user = callback.from_user
    date = get_now().strftime("%Y-%m-%d")

    if action == "no":
        await callback.message.edit_text("❌ Bekor qilindi. /start davomat orqali qaytadan urinib ko'rishingiz mumkin.")
        await callback.answer()
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO davomat (user_id, date, full_name, status, group_id, verified) 
               VALUES (?, ?, ?, ?, ?, 'approved')
               ON CONFLICT(user_id, date) DO UPDATE SET 
               status='❌ Kelmadi', verified='approved', full_name=excluded.full_name""",
            (user.id, date, user.full_name, '❌ Kelmadi', callback.message.chat.id)
        )
        await db.commit()

    await callback.answer("Muvaffaqiyatli saqlandi!")
    await callback.message.edit_text("✅ Sizning holatingiz **❌ Kelmadi** deb muvaffaqiyatli saqlandi.", parse_mode=ParseMode.HTML)

# --- 5. SELFIE RECEIVE & PRE-SUBMISSION PROMPT ---
@dp.message(F.photo)
async def handle_photo(message: Message):
    user = message.from_user
    date = get_now().strftime("%Y-%m-%d")
    photo_file_id = message.photo[-1].file_id

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT verified FROM davomat WHERE user_id = ? AND date = ?", 
            (user.id, date)
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[0].startswith("awaiting_photo_"):
        await message.answer("⚠️ Iltimos, avval guruhdagi tugma orqali davomat tanlang.")
        return

    option = row[0].replace("awaiting_photo_", "")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE davomat SET photo_file_id = ?, verified = ? WHERE user_id = ? AND date = ?",
            (photo_file_id, f"awaiting_pconf_{option}", user.id, date)
        )
        await db.commit()

    conf_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, yuborish", callback_data=f"pconf:{option}:yes"),
            InlineKeyboardButton(text="❌ Boshqatdan tanlash", callback_data=f"pconf:{option}:no")
        ]
    ])

    await message.answer_photo(
        photo=photo_file_id,
        caption=f"🔍 Selfeingiz qabul qilindi. Ushbu rasm va **{option.capitalize()}** holatini adminga yuborishni tasdiqlaysizmi?",
        reply_markup=conf_keyboard,
        parse_mode=ParseMode.HTML
    )

# --- 6. POST-SELFIE CONFIRMATION ---
@dp.callback_query(F.data.startswith("pconf:"))
async def post_photo_confirmation(callback: CallbackQuery):
    _, option, action = callback.data.split(":")
    user = callback.from_user
    date = get_now().strftime("%Y-%m-%d")

    if action == "no":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE davomat SET verified = 'none', photo_file_id = NULL WHERE user_id = ? AND date = ?",
                (user.id, date)
            )
            await db.commit()

        await callback.answer("Bekor qilindi.")
        await callback.message.edit_caption(
            caption="❌ Tasdiqlash bekor qilindi. /start davomat orqali qaytadan urinib ko'rishingiz mumkin."
        )
        return

    status_text = "✅ Keldi (Tasdiqlash kutilmoqda)" if option == "keldi" else "🕐 Kechikdi (Tasdiqlash kutilmoqda)"
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT photo_file_id FROM davomat WHERE user_id = ? AND date = ?", (user.id, date)) as cursor:
            res = await cursor.fetchone()
            photo_file_id = res[0] if res else None

        await db.execute(
            "UPDATE davomat SET status = ?, verified = 'pending_admin' WHERE user_id = ? AND date = ?",
            (status_text, user.id, date)
        )
        await db.commit()

    await callback.answer("Adminga yuborildi!")
    await callback.message.edit_caption(
        caption="📤 Selfeingiz va holatingiz adminga tekshirish uchun yuborildi. Natijasini kuting."
    )

    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"verify:approve:{user.id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"verify:reject:{user.id}")
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=photo_file_id,
                caption=(
                    f"📥 <b>Yangi davomat tekshiruvi:</b>\n\n"
                    f"👤 O'quvchi: {user.full_name}\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"📊 Tanlov: {option.capitalize()}\n"
                    f"📅 Sana: {date}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# --- 7. ADMIN VERIFICATION ---
@dp.callback_query(F.data.startswith("verify:"))
async def process_verification(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu tugma faqat admin uchun.", show_alert=True)
        return

    _, action, target_user_id_str = callback.data.split(":")
    target_user_id = int(target_user_id_str)
    date = get_now().strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        if action == "approve":
            await db.execute(
                "UPDATE davomat SET verified = 'approved', status = '✅ Keldi' WHERE user_id = ? AND date = ?",
                (target_user_id, date)
            )
            await db.commit()
            await callback.answer("Muvaffaqiyatli tasdiqlandi!")
            await callback.message.edit_caption(
                caption=callback.message.caption + "\n\n<b>STATUS: ✅ TASDIQLANDI</b>",
                parse_mode=ParseMode.HTML
            )
            try:
                await bot.send_message(target_user_id, "✅ Sizning davomatingiz admin tomonidan tasdiqlandi!")
            except:
                pass
        else:
            await db.execute(
                "UPDATE davomat SET verified = 'rejected', status = '❌ Rad etildi' WHERE user_id = ? AND date = ?",
                (target_user_id, date)
            )
            await db.commit()
            await callback.answer("Rad etildi.")
            await callback.message.edit_caption(
                caption=callback.message.caption + "\n\n<b>STATUS: ❌ RAD ETILDI</b>",
                parse_mode=ParseMode.HTML
            )
            try:
                await bot.send_message(target_user_id, "❌ Afsuski, selfeingiz rad etildi. /start davomat orqali qaytadan urinib ko'rishingiz mumkin.")
            except:
                pass

# --- 8. HISOBOT COMMAND ---
@dp.message(Command("hisobot"))
async def report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Faqat admin ko‘ra oladi.")
        return

    today = get_now().strftime("%Y-%m-%d")

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, status, verified FROM davomat WHERE date = ? ORDER BY full_name",
            (today,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer(f"Bugun ({today}) hali hech kim davomat topshirmagan.")
        return

    text = f"📊 <b>Bugungi davomat</b> ({today})\n\n"
    for name, status, verified in rows:
        icon = "🟢" if verified == "approved" else ("🔴" if verified == "rejected" else "🟡")
        text += f"{icon} {name} — {status}\n"

    await message.answer(text, parse_mode=ParseMode.HTML)

# --- FastAPI Webhook Handler ---
@app.post("/webhook")
@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        json_data = await request.json()
        if json_data:
            await dp.feed_raw_update(bot, json_data)
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

@app.get("/")
async def index():
    return {"status": "Bot is running securely with Environment Variables!"}
