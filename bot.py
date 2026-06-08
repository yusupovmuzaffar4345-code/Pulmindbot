import asyncio
import re
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# === SOZLAMALAR ===
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# === HOLATLAR (FSM) ===
class TolovHolat(StatesGroup):
    tolov_turi = State()

# === DATABASE ===
async def init_db():
    async with aiosqlite.connect("data.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            category TEXT,
            tolov_turi TEXT,
            sana DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()

# === YORDAMCHI FUNKSIYALAR ===
def get_category(text):
    text = text.lower()
    if any(w in text for w in ["taksi", "yandex", "uber"]):
        return "🚖 Transport"
    elif any(w in text for w in ["ovqat", "tushlik", "nonushta", "kechki", "restoran", "cafe", "kafe"]):
        return "🍽 Ovqat"
    elif any(w in text for w in ["metro", "avtobus", "aftobus", "marshrutka"]):
        return "🚌 Jamoat transport"
    elif any(w in text for w in ["kino", "o'yin", "oyun", "kontsert"]):
        return "🎬 Ko'ngil ochar"
    elif any(w in text for w in ["dori", "apteka", "shifokor"]):
        return "💊 Sog'liq"
    else:
        return "📦 Boshqa"

def get_amount(text):
    text = text.lower()
    text = text.replace(",", "").replace(" ", " ")

    ming_match = re.search(r"(\d+(?:\.\d+)?)\s*ming", text)
    if ming_match:
        return int(float(ming_match.group(1)) * 1000)

    mln_match = re.search(r"(\d+(?:\.\d+)?)\s*m(?:ln|ilion)?", text)
    if mln_match:
        return int(float(mln_match.group(1)) * 1_000_000)

    match = re.search(r"\d+", text)
    return int(match.group()) if match else None

# === MENU TUGMALARI ===
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Hisob"), KeyboardButton(text="📊 Kategoriyalar")],
            [KeyboardButton(text="🗑 Tozalash"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True
    )

def tolov_menu(prefix="t"):
    import time
    uid = str(int(time.time()))[-4:]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💵 Naqd", callback_data=f"tolov_naqd_{uid}_{prefix}"),
                InlineKeyboardButton(text="💳 Karta", callback_data=f"tolov_karta_{uid}_{prefix}"),
            ]
        ]
    )

# === /start ===
@dp.message(Command("start"))
async def start(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        f"👋 Salom, {msg.from_user.first_name}!\n\n"
        "💸 <b>PulMind</b> — xarajat hisoblovchi bot\n\n"
        "📝 <b>Misol:</b>\n"
        "• <code>20000 taksi</code>\n"
        "• <code>20 ming tushlik</code>\n"
        "• Ovozli xabar ham yuborishingiz mumkin\n\n"
        "👇 Pastdagi tugmalardan foydalaning:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === YORDAM ===
@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Yordam")
async def yordam(msg: types.Message):
    await msg.answer(
        "📖 <b>Qo'llanma:</b>\n\n"
        "✏️ <b>Xarajat yozish:</b>\n"
        "<code>20000 taksi</code>\n"
        "<code>20 ming tushlik</code>\n"
        "<code>5000 metro</code>\n\n"
        "🎤 <b>Ovozli xabar</b> ham qabul qilinadi\n\n"
        "📋 <b>Buyruqlar:</b>\n"
        "/hisob — Jami xarajatlar\n"
        "/tozala — Ma'lumotlarni o'chirish\n"
        "/start — Qayta boshlash",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === HISOB ===
@dp.message(Command("hisob"))
@dp.message(F.text == "💰 Hisob")
async def hisob(msg: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect("data.db") as db:
        cursor = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=?", (msg.from_user.id,))
        total = (await cursor.fetchone())[0] or 0

        cursor = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tolov_turi='naqd'", (msg.from_user.id,))
        naqd_sum = (await cursor.fetchone())[0] or 0

        cursor = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tolov_turi='karta'", (msg.from_user.id,))
        karta_sum = (await cursor.fetchone())[0] or 0

        cursor = await db.execute(
            "SELECT category, SUM(amount) FROM transactions WHERE user_id=? GROUP BY category ORDER BY SUM(amount) DESC",
            (msg.from_user.id,))
        cats = await cursor.fetchall()

        cursor = await db.execute(
            "SELECT amount, category, tolov_turi FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (msg.from_user.id,))
        oxirgi = await cursor.fetchall()

    if total == 0:
        await msg.answer("📭 Hali xarajat yo'q.", reply_markup=main_menu())
        return

    cat_text = "".join(f"  {cat}: {amt:,} so'm\n" for cat, amt in cats)
    oxirgi_text = "".join(
        f"  {'💵' if t == 'naqd' else '💳'} {amt:,} so'm — {cat}\n"
        for amt, cat, t in oxirgi
    )

    await msg.answer(
        f"📊 <b>Hisobingiz:</b>\n\n"
        f"💰 <b>Jami: {total:,} so'm</b>\n"
        f"💵 Naqd: {naqd_sum:,} so'm\n"
        f"💳 Karta: {karta_sum:,} so'm\n\n"
        f"📂 <b>Kategoriyalar:</b>\n{cat_text}\n"
        f"🕐 <b>Oxirgi 5 ta:</b>\n{oxirgi_text}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === KATEGORIYALAR ===
@dp.message(F.text == "📊 Kategoriyalar")
async def kategoriyalar(msg: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect("data.db") as db:
        cursor = await db.execute(
            "SELECT category, SUM(amount), COUNT(*) FROM transactions WHERE user_id=? GROUP BY category ORDER BY SUM(amount) DESC",
            (msg.from_user.id,))
        cats = await cursor.fetchall()

    if not cats:
        await msg.answer("📭 Hali xarajat yo'q.", reply_markup=main_menu())
        return

    text = "📊 <b>Kategoriyalar bo'yicha:</b>\n\n"
    text += "".join(f"{cat}\n  💰 {amt:,} so'm ({count} ta)\n\n" for cat, amt, count in cats)
    await msg.answer(text, parse_mode="HTML", reply_markup=main_menu())

# === TOZALASH ===
@dp.message(Command("tozala"))
@dp.message(F.text == "🗑 Tozalash")
async def tozala_confirm(msg: types.Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data="tozala_ha"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data="tozala_yoq"),
    ]])
    await msg.answer("⚠️ Barcha xarajatlarni o'chirishni istaysizmi?", reply_markup=keyboard)

@dp.callback_query(F.data == "tozala_ha")
async def tozala_ha(call: types.CallbackQuery):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("DELETE FROM transactions WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.message.edit_text("✅ Barcha xarajatlar o'chirildi.")
    await call.answer()

@dp.callback_query(F.data == "tozala_yoq")
async def tozala_yoq(call: types.CallbackQuery):
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()

# === OVOZLI XABAR ===
@dp.message(F.voice)
async def ovozli_xabar(msg: types.Message, state: FSMContext):
    await state.clear()
    wait_msg = await msg.answer("🎤 Ovoz qabul qilindi, tanilmoqda...")

    file = await bot.get_file(msg.voice.file_id)
    ogg_path = f"voice_{msg.from_user.id}.ogg"
    wav_path = f"voice_{msg.from_user.id}.wav"

    await bot.download_file(file.file_path, ogg_path)

    text = None
    try:
        from pydub import AudioSegment
        import speech_recognition as sr

        AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            for lang in ["uz-UZ", "ru-RU"]:
                try:
                    text = recognizer.recognize_google(audio_data, language=lang)
                    break
                except:
                    continue
    except Exception as e:
        pass
    finally:
        for f in [ogg_path, wav_path]:
            if os.path.exists(f):
                os.remove(f)

    await wait_msg.delete()

    if not text:
        await msg.answer(
            "⚠️ Ovozni tanib bo'lmadi.\n"
            "Matn ko'rinishida yozing: <code>20000 taksi</code>",
            parse_mode="HTML"
        )
        return

    await msg.answer(f"📝 Tanildi: <b>{text}</b>", parse_mode="HTML")

    amount = get_amount(text)
    if not amount:
        await msg.answer("❌ Summani topa olmadim. Masalan: <code>20000 taksi</code>", parse_mode="HTML")
        return

    category = get_category(text)
    await state.update_data(amount=amount, category=category)
    await state.set_state(TolovHolat.tolov_turi)

    await msg.answer(
        f"💰 <b>{amount:,} so'm</b> — {category}\n\nTo'lov turini tanlang:",
        parse_mode="HTML",
        reply_markup=tolov_menu("v")
    )

# === MATN XARAJAT ===
MENU_BUTTONS = ["💰 Hisob", "📊 Kategoriyalar", "🗑 Tozalash", "ℹ️ Yordam"]

@dp.message(F.text)
async def save(msg: types.Message, state: FSMContext):
    if msg.text in MENU_BUTTONS:
        return

    await state.clear()
    text = msg.text

    amount = get_amount(text)
    if not amount:
        await msg.answer(
            "❌ Summani topa olmadim.\n"
            "Masalan: <code>20000 taksi</code> yoki <code>20 ming tushlik</code>",
            parse_mode="HTML"
        )
        return

    category = get_category(text)
    await state.update_data(amount=amount, category=category)
    await state.set_state(TolovHolat.tolov_turi)

    await msg.answer(
        f"💰 <b>{amount:,} so'm</b> — {category}\n\nTo'lov turini tanlang:",
        parse_mode="HTML",
        reply_markup=tolov_menu("m")
    )

# === TO'LOV TURI CALLBACK ===
@dp.callback_query(TolovHolat.tolov_turi, F.data.startswith("tolov_"))
async def tolov_tanlandi(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    tolov_turi = parts[1]

    data = await state.get_data()
    amount = data.get("amount")
    category = data.get("category")

    if not amount or not category:
        await call.answer("❌ Xatolik, qaytadan yozing", show_alert=True)
        await state.clear()
        return

    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT INTO transactions (user_id, amount, category, tolov_turi) VALUES (?, ?, ?, ?)",
            (call.from_user.id, amount, category, tolov_turi)
        )
        await db.commit()

    await state.clear()

    icon = "💵" if tolov_turi == "naqd" else "💳"
    tolov_nomi = "Naqd" if tolov_turi == "naqd" else "Karta"

    await call.message.edit_text(
        f"✅ <b>Saqlandi!</b>\n\n"
        f"{icon} <b>{amount:,} so'm</b>\n"
        f"📂 {category}\n"
        f"💳 To'lov: {tolov_nomi}",
        parse_mode="HTML"
    )
    await call.answer("✅ Saqlandi!")

# === MAIN ===
async def main():
    await init_db()
    print("✅ Bot ishga tushdi!")
    await dp.start_polling(bot)

asyncio.run(main())
