import traceback
from datetime import datetime
import aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Message, 
    CallbackQuery, 
    BotCommand
)
from aiogram.enums import ParseMode

BOT_TOKEN = "8814886432:AAGg7JG5-JghTl0BxoxpDG0Ni5rhF4WGE6k"
ADMIN_IDS = [93372553, 7196958222]
DB_PATH = "/tmp/davomat.db"

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
                verified TEXT DEFAULT 'pending',
                PRIMARY KEY (user_id, date)
            )
        """)
        await db.commit()

@app.on_event("startup")
async def startup_event():
    await init_db()
    commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="davomat", description="Davomatni boshlash (Admin)"),
        BotCommand(command="hisobot", description="Bugungi natijalarni ko'rish (Admin)")
    ]
    await bot.set_my_commands(commands)

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
        await message.answer(
            "Assalomu alaykum!\n"
            "Bu bot davomat uchun mo'ljallangan. Admin davomatni boshlaganda "
            "tugmani bosing va o'z selfeingizni yuboring."
        )

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
        f"O‘quvchilar o'z holatini tanlasin va selfe yuborsin.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

# 1. Student selects status -> Prompt for Selfie
@dp.callback_query(F.data.startswith("status:"))
async def process_status(callback: CallbackQuery):
    status_type = callback.data.split(":")[1]
    user = callback.from_user
    date = datetime.now().strftime("%Y-%m-%d")

    if status_type == "kelmadi":
        status_text = "❌ Kelmadi"
        verified_status = "approved" # Kelmadi doesn't need photo verification
    elif status_type == "keldi":
        status_text = "⏳ Keldi (Selfe kutilmoqda)"
        verified_status = "pending_photo"
    else:
        status_text = "⏳ Kechikdi (Selfe kutilmoqda)"
        verified_status = "pending_photo"

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO davomat (user_id, date, full_name, status, group_id, verified) 
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET 
               status=excluded.status, verified=excluded.verified, full_name=excluded.full_name""",
            (user.id, date, user.full_name, status_text, callback.message.chat.id, verified_status)
        )
        await db.commit()

    if status_type == "kelmadi":
        await callback.answer("Belgilandi: ❌ Kelmadi")
        await callback.message.edit_text(f"✅ {user.full_name} — ❌ Kelmadi deb belgilandi.")
    else:
        await callback.answer("Endi o'zingizning selfeingizni yuboring!")
        await callback.message.answer(
            f"📸 <b>{user.full_name}</b>, iltimos hozirgi holatingizni tasdiqlash uchun **selfie rasmingizni** chatga yuboring.",
            parse_mode=ParseMode.HTML
        )

# 2. Student sends a selfie photo
@dp.message(F.photo)
async def handle_photo(message: Message):
    user = message.from_user
    date = datetime.now().strftime("%Y-%m-%d")
    photo_file_id = message.photo[-1].file_id

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status FROM davomat WHERE user_id = ? AND date = ?", 
            (user.id, date)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        await message.answer("⚠️ Avval /davomat ostidagi tugmalardan birini bosing va keyin rasm yuboring.")
        return

    # Update DB with photo and set verification to pending admin review
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE davomat SET photo_file_id = ?, verified = 'pending_admin' WHERE user_id = ? AND date = ?",
            (photo_file_id, user.id, date)
        )
        await db.commit()

    await message.answer("📤 Selfeingiz adminga yuborildi. Tasdiqlanishi kutilmoqda...")

    # Forward photo to all admins with inline approval buttons
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
                    f"📥 <b>Yangi davomat selfeyi:</b>\n\n"
                    f"👤 O'quvchi: {user.full_name}\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"📅 Sana: {date}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# 3. Admin clicks Approve or Reject
@dp.callback_query(F.data.startswith("verify:"))
async def process_verification(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu tugma faqat admin uchun.", show_alert=True)
        return

    _, action, target_user_id_str = callback.data.split(":")
    target_user_id = int(target_user_id_str)
    date = datetime.now().strftime("%Y-%m-%d")

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        if action == "approve":
            await db.execute(
                "UPDATE davomat SET verified = 'approved', status = '✅ Keldi (Tasdiqlangan)' WHERE user_id = ? AND date = ?",
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
                await bot.send_message(target_user_id, "❌ Afsuski, selfeingiz rad etildi. Qaytadan urinib ko'ring.")
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
            "SELECT full_name, status, verified FROM davomat WHERE date = ? ORDER BY full_name",
            (today,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Bugun hali hiç kim davomat topshirmagan.")
        return

    text = f"📊 <b>Bugungi davomat</b> ({today})\n\n"
    for name, status, verified in rows:
        icon = "🟢" if verified == "approved" else ("🔴" if verified == "rejected" else "🟡")
        text += f"{icon} {name} — {status}\n"

    await message.answer(text, parse_mode=ParseMode.HTML)

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
    return {"status": "Bot is running with Selfie Verification on Vercel!"}
