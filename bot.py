import asyncio
import re
import os
import csv
import io
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# === SOZLAMALAR ===
TOKEN = "8712095885:AAG0-JyZ8IKsrRUOdn3UkVEENpL-F5ger2A"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# === HOLATLAR (FSM) ===
class TolovHolat(StatesGroup):
    tolov_turi = State()

class KirimHolat(StatesGroup):
    tolov_turi = State()

class ByudjetHolat(StatesGroup):
    miqdor = State()

class EslatmaHolat(StatesGroup):
    vaqt = State()
    xabar = State()

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
            tur TEXT DEFAULT 'chiqim',
            izoh TEXT,
            sana DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS byudjet (
            user_id INTEGER PRIMARY KEY,
            miqdor INTEGER,
            oy TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS eslatmalar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            vaqt TEXT,
            xabar TEXT,
            sent INTEGER DEFAULT 0
        )
        """)
        # Migrate: izoh ustunini qo'shish (agar yo'q bo'lsa)
        try:
            await db.execute("ALTER TABLE transactions ADD COLUMN izoh TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE transactions ADD COLUMN tur TEXT DEFAULT 'chiqim'")
        except:
            pass
        await db.commit()

# === YORDAMCHI FUNKSIYALAR ===
def get_category(text):
    text = text.lower()
    if any(w in text for w in ["taksi", "yandex", "uber", "transport" "WB taxi"]):
        return "🚖 Transport"
    elif any(w in text for w in ["ovqat", "tushlik", "nonushta", "kechki", "restoran", "cafe", "kafe", "doner", "pizza", "burger"]):
        return "🍽 Ovqat"
    elif any(w in text for w in ["metro", "avtobus", "aftobus", "marshrutka"]):
        return "🚌 Jamoat transport"
    elif any(w in text for w in ["kino", "o'yin", "oyun", "kontsert", "o'yin"]):
        return "🎬 Ko'ngil ochar"
    elif any(w in text for w in ["dori", "apteka", "shifokor", "klinika"]):
        return "💊 Sog'liq"
    elif any(w in text for w in ["kiyim", "oyoq kiyim", "ko'ylak", "shim", "bozor"]):
        return "👗 Kiyim"
    elif any(w in text for w in ["kommunal", "gaz", "suv", "elektr", "internet", "telefon"]):
        return "🏠 Kommunal"
    elif any(w in text for w in ["o'quv", "kitob", "kurs", "ta'lim", "maktab", "universitet"]):
        return "📚 Ta'lim"
    else:
        return "📦 Boshqa"

def get_amount(text):
    """
    Raqamni to'g'ri parse qilish.
    '17 ming' → 17000
    '1.5 mln' → 1500000
    '20000' → 20000
    """
    text = text.lower().strip()
    text = text.replace(",", ".")

    # MING: "17 ming", "17ming", "17k", "17min"
    ming_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ming|k\b)", text)
    if ming_match:
        return int(float(ming_match.group(1)) * 1000)

    # MILLION: "1.5 mln", "2 million", "3 mlrd" — lekin "ming" so'zini ushlaMASLIK uchun
    # regex: "mln" yoki "million" yoki "mlrd" — "m" yolg'iz emas
    mln_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mln|million|mlrd|milliard)", text)
    if mln_match:
        val = float(mln_match.group(1))
        if "mlrd" in text or "milliard" in text:
            return int(val * 1_000_000_000)
        return int(val * 1_000_000)

    # Oddiy raqam: "20000"
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None

def format_sum(amount):
    return f"{amount:,}".replace(",", " ")

def get_oy():
    return datetime.now().strftime("%Y-%m")

# === MENU TUGMALARI ===
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Hisob"), KeyboardButton(text="📊 Statistika")],
            [KeyboardButton(text="📥 Kirim"), KeyboardButton(text="📤 Chiqim")],
            [KeyboardButton(text="🎯 Byudjet"), KeyboardButton(text="📁 Eksport")],
            [KeyboardButton(text="🔔 Eslatma"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True
    )

def tolov_menu(prefix="t"):
    import time
    uid = str(int(time.time()))[-4:]
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💵 Naqd", callback_data=f"tolov_naqd_{uid}_{prefix}"),
            InlineKeyboardButton(text="💳 Karta", callback_data=f"tolov_karta_{uid}_{prefix}"),
        ]]
    )

def kirim_tolov_menu(prefix="k"):
    import time
    uid = str(int(time.time()))[-4:]
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💵 Naqd", callback_data=f"kirim_naqd_{uid}_{prefix}"),
            InlineKeyboardButton(text="💳 Karta", callback_data=f"kirim_karta_{uid}_{prefix}"),
        ]]
    )

def hisobot_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Bugun", callback_data="stat_bugun"),
                InlineKeyboardButton(text="📆 Bu hafta", callback_data="stat_hafta"),
            ],
            [
                InlineKeyboardButton(text="🗓 Bu oy", callback_data="stat_oy"),
                InlineKeyboardButton(text="📊 Jami", callback_data="stat_jami"),
            ],
        ]
    )

# === /start ===
@dp.message(Command("start"))
async def start(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        f"👋 Salom, {msg.from_user.first_name}!\n\n"
        "💸 <b>PulMind</b> — aqlli xarajat hisoblovchi\n\n"
        "📝 <b>Misol:</b>\n"
        "• <code>20000 taksi</code>\n"
        "• <code>20 ming tushlik</code>\n"
        "• <code>1.5 mln maosh</code> (kirim)\n"
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
        "✏️ <b>Chiqim yozish:</b>\n"
        "<code>20000 taksi</code>\n"
        "<code>20 ming tushlik</code>\n"
        "<code>5 ming metro</code>\n\n"
        "📥 <b>Kirim yozish:</b>\n"
        "<code>📥 Kirim</code> tugmasini bosing\n"
        "yoki: <code>2 mln maosh</code>\n\n"
        "🎤 <b>Ovozli xabar</b> ham qabul qilinadi\n\n"
        "📊 <b>Raqam yozish usullari:</b>\n"
        "<code>17 ming</code> → 17,000 so'm\n"
        "<code>1.5 mln</code> → 1,500,000 so'm\n"
        "<code>50000</code> → 50,000 so'm\n\n"
        "📋 <b>Buyruqlar:</b>\n"
        "/hisob — Balans\n"
        "/statistika — Hisobotlar\n"
        "/byudjet — Byudjet belgilash\n"
        "/eksport — CSV yuklash\n"
        "/tozala — Ma'lumotlarni o'chirish\n"
        "/start — Qayta boshlash",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === HISOB (BALANS) ===
@dp.message(Command("hisob"))
@dp.message(F.text == "💰 Hisob")
async def hisob(msg: types.Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    async with aiosqlite.connect("data.db") as db:
        # Jami chiqim
        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim'", (uid,))
        jami_chiqim = (await cur.fetchone())[0] or 0

        # Jami kirim
        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='kirim'", (uid,))
        jami_kirim = (await cur.fetchone())[0] or 0

        # Naqd/Karta chiqim
        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND tolov_turi='naqd'", (uid,))
        naqd_sum = (await cur.fetchone())[0] or 0

        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND tolov_turi='karta'", (uid,))
        karta_sum = (await cur.fetchone())[0] or 0

        # Bu oylik
        oy = get_oy()
        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND strftime('%Y-%m', sana)=?",
            (uid, oy))
        oy_chiqim = (await cur.fetchone())[0] or 0

        # Byudjet
        cur = await db.execute("SELECT miqdor FROM byudjet WHERE user_id=? AND oy=?", (uid, oy))
        byudjet_row = await cur.fetchone()
        byudjet = byudjet_row[0] if byudjet_row else None

        # Oxirgi 5
        cur = await db.execute(
            "SELECT amount, category, tolov_turi, tur FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (uid,))
        oxirgi = await cur.fetchall()

    balans = jami_kirim - jami_chiqim
    balans_icon = "📈" if balans >= 0 else "📉"

    byudjet_text = ""
    if byudjet:
        qolgan = byudjet - oy_chiqim
        foiz = min(int(oy_chiqim / byudjet * 100), 100)
        bar = "🟩" * (foiz // 10) + "⬜" * (10 - foiz // 10)
        byudjet_text = (
            f"\n🎯 <b>Bu oylik byudjet:</b>\n"
            f"{bar} {foiz}%\n"
            f"  Sarflandi: {format_sum(oy_chiqim)} so'm\n"
            f"  Qoldi: {format_sum(max(qolgan,0))} so'm\n"
        )

    oxirgi_text = ""
    for amt, cat, t, tur in oxirgi:
        icon = "📥" if tur == "kirim" else ("💵" if t == "naqd" else "💳")
        oxirgi_text += f"  {icon} {format_sum(amt)} so'm — {cat}\n"

    await msg.answer(
        f"💼 <b>Balans:</b> {balans_icon} {format_sum(balans)} so'm\n\n"
        f"📥 Jami kirim: <b>{format_sum(jami_kirim)} so'm</b>\n"
        f"📤 Jami chiqim: <b>{format_sum(jami_chiqim)} so'm</b>\n\n"
        f"💵 Naqd chiqim: {format_sum(naqd_sum)} so'm\n"
        f"💳 Karta chiqim: {format_sum(karta_sum)} so'm\n"
        f"{byudjet_text}\n"
        f"🕐 <b>Oxirgi 5 ta:</b>\n{oxirgi_text}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === STATISTIKA ===
@dp.message(Command("statistika"))
@dp.message(F.text == "📊 Statistika")
async def statistika(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer("📊 Qaysi davr uchun statistika?", reply_markup=hisobot_menu())

async def send_stat(msg_or_call, uid, sana_filter, davr_nomi):
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND {sana_filter}",
            (uid,))
        jami = (await cur.fetchone())[0] or 0

        cur = await db.execute(
            f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='kirim' AND {sana_filter}",
            (uid,))
        kirim = (await cur.fetchone())[0] or 0

        cur = await db.execute(
            f"SELECT category, SUM(amount), COUNT(*) FROM transactions WHERE user_id=? AND tur='chiqim' AND {sana_filter} GROUP BY category ORDER BY SUM(amount) DESC",
            (uid,))
        cats = await cursor_rows(cur)

        cur = await db.execute(
            f"SELECT tolov_turi, SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND {sana_filter} GROUP BY tolov_turi",
            (uid,))
        tolovlar = await cursor_rows(cur)

    if jami == 0 and kirim == 0:
        text = f"📭 {davr_nomi} uchun ma'lumot yo'q."
    else:
        cat_text = ""
        for cat, amt, count in cats:
            foiz = int(amt / jami * 100) if jami else 0
            bar = "█" * (foiz // 10) + "░" * (10 - foiz // 10)
            cat_text += f"{cat}\n  {bar} {foiz}% — {format_sum(amt)} so'm ({count}x)\n"

        tolov_text = ""
        for t, amt in tolovlar:
            icon = "💵" if t == "naqd" else "💳"
            tolov_text += f"  {icon} {t.capitalize()}: {format_sum(amt)} so'm\n"

        text = (
            f"📊 <b>{davr_nomi} statistika:</b>\n\n"
            f"📤 Chiqim: <b>{format_sum(jami)} so'm</b>\n"
            f"📥 Kirim: <b>{format_sum(kirim)} so'm</b>\n"
            f"💰 Balans: <b>{format_sum(kirim - jami)} so'm</b>\n\n"
            f"📂 <b>Kategoriyalar:</b>\n{cat_text}\n"
            f"💳 <b>To'lov turlari:</b>\n{tolov_text}"
        )

    if hasattr(msg_or_call, 'message'):
        await msg_or_call.message.edit_text(text, parse_mode="HTML")
        await msg_or_call.answer()
    else:
        await msg_or_call.answer(text, parse_mode="HTML", reply_markup=main_menu())

async def cursor_rows(cur):
    return await cur.fetchall()

@dp.callback_query(F.data == "stat_bugun")
async def stat_bugun(call: types.CallbackQuery):
    bugun = datetime.now().strftime("%Y-%m-%d")
    await send_stat(call, call.from_user.id, f"date(sana)='{bugun}'", "Bugungi")

@dp.callback_query(F.data == "stat_hafta")
async def stat_hafta(call: types.CallbackQuery):
    hafta_boshi = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    await send_stat(call, call.from_user.id, f"date(sana)>='{hafta_boshi}'", "Bu haftagi")

@dp.callback_query(F.data == "stat_oy")
async def stat_oy(call: types.CallbackQuery):
    oy = get_oy()
    await send_stat(call, call.from_user.id, f"strftime('%Y-%m', sana)='{oy}'", "Bu oylik")

@dp.callback_query(F.data == "stat_jami")
async def stat_jami(call: types.CallbackQuery):
    await send_stat(call, call.from_user.id, "1=1", "Jami")

# === KIRIM ===
@dp.message(F.text == "📥 Kirim")
async def kirim_boshlash(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "📥 <b>Kirim miqdorini yozing:</b>\n\n"
        "Misol: <code>2 mln maosh</code>\n"
        "yoki: <code>500 ming freelance</code>",
        parse_mode="HTML"
    )
    await state.set_state(KirimHolat.tolov_turi)

@dp.message(KirimHolat.tolov_turi)
async def kirim_qabul(msg: types.Message, state: FSMContext):
    text = msg.text
    amount = get_amount(text)
    if not amount:
        await msg.answer("❌ Summani topa olmadim. Masalan: <code>500 ming maosh</code>", parse_mode="HTML")
        return

    category = get_kirim_category(text)
    await state.update_data(amount=amount, category=category)

    await msg.answer(
        f"📥 <b>{format_sum(amount)} so'm</b> — {category}\n\nTo'lov turini tanlang:",
        parse_mode="HTML",
        reply_markup=kirim_tolov_menu()
    )

def get_kirim_category(text):
    text = text.lower()
    if any(w in text for w in ["maosh", "ish haqi", "oylik"]):
        return "💼 Maosh"
    elif any(w in text for w in ["freelance", "loyiha", "project"]):
        return "💻 Freelance"
    elif any(w in text for w in ["sovg'a", "hadya", "gift"]):
        return "🎁 Sovg'a"
    elif any(w in text for w in ["ijara", "rent"]):
        return "🏠 Ijara"
    else:
        return "📥 Boshqa kirim"

@dp.callback_query(KirimHolat.tolov_turi, F.data.startswith("kirim_"))
async def kirim_tolov_tanlandi(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    tolov_turi = parts[1]

    data = await state.get_data()
    amount = data.get("amount")
    category = data.get("category")

    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT INTO transactions (user_id, amount, category, tolov_turi, tur) VALUES (?, ?, ?, ?, 'kirim')",
            (call.from_user.id, amount, category, tolov_turi)
        )
        await db.commit()

    await state.clear()

    icon = "💵" if tolov_turi == "naqd" else "💳"
    await call.message.edit_text(
        f"✅ <b>Kirim saqlandi!</b>\n\n"
        f"📥 {icon} <b>{format_sum(amount)} so'm</b>\n"
        f"📂 {category}",
        parse_mode="HTML"
    )
    await call.answer("✅ Kirim saqlandi!")

# === CHIQIM (tugma orqali) ===
@dp.message(F.text == "📤 Chiqim")
async def chiqim_boshlash(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "📤 <b>Chiqim miqdorini yozing:</b>\n\n"
        "Misol: <code>20 ming taksi</code>\n"
        "yoki: <code>150000 oziq-ovqat</code>",
        parse_mode="HTML"
    )

# === BYUDJET ===
@dp.message(Command("byudjet"))
@dp.message(F.text == "🎯 Byudjet")
async def byudjet_boshlash(msg: types.Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    oy = get_oy()

    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT miqdor FROM byudjet WHERE user_id=? AND oy=?", (uid, oy))
        row = await cur.fetchone()

    if row:
        cur_chiqim = await get_oy_chiqim(uid, oy)
        qolgan = row[0] - cur_chiqim
        foiz = min(int(cur_chiqim / row[0] * 100), 100)
        bar = "🟩" * (foiz // 10) + "⬜" * (10 - foiz // 10)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="byudjet_ozgartir"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data="byudjet_ochir"),
        ]])
        await msg.answer(
            f"🎯 <b>Bu oylik byudjet:</b>\n\n"
            f"💰 Belgilangan: {format_sum(row[0])} so'm\n"
            f"📤 Sarflandi: {format_sum(cur_chiqim)} so'm\n"
            f"💚 Qoldi: {format_sum(max(qolgan,0))} so'm\n\n"
            f"{bar} {foiz}%",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await msg.answer(
            "🎯 <b>Bu oy uchun byudjet belgilanmagan.</b>\n\n"
            "Byudjet miqdorini yozing (so'mda):\n"
            "Masalan: <code>3 mln</code> yoki <code>2000000</code>",
            parse_mode="HTML"
        )
        await state.set_state(ByudjetHolat.miqdor)

async def get_oy_chiqim(uid, oy):
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND tur='chiqim' AND strftime('%Y-%m', sana)=?",
            (uid, oy))
        val = (await cur.fetchone())[0] or 0
    return val

@dp.callback_query(F.data == "byudjet_ozgartir")
async def byudjet_ozgartir(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("✏️ Yangi byudjet miqdorini yozing:")
    await state.set_state(ByudjetHolat.miqdor)
    await call.answer()

@dp.callback_query(F.data == "byudjet_ochir")
async def byudjet_ochir(call: types.CallbackQuery):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("DELETE FROM byudjet WHERE user_id=? AND oy=?", (call.from_user.id, get_oy()))
        await db.commit()
    await call.message.edit_text("✅ Byudjet o'chirildi.")
    await call.answer()

@dp.message(ByudjetHolat.miqdor)
async def byudjet_saqlash(msg: types.Message, state: FSMContext):
    amount = get_amount(msg.text)
    if not amount:
        await msg.answer("❌ Summani topa olmadim. Masalan: <code>3 mln</code>", parse_mode="HTML")
        return

    oy = get_oy()
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO byudjet (user_id, miqdor, oy) VALUES (?, ?, ?)",
            (msg.from_user.id, amount, oy)
        )
        await db.commit()

    await state.clear()
    await msg.answer(
        f"✅ <b>Byudjet belgilandi:</b> {format_sum(amount)} so'm\n\n"
        "Bu oy xarajatingiz belgilangan byudjetdan oshsa ogohlantiraman! 🔔",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === EKSPORT ===
@dp.message(Command("eksport"))
@dp.message(F.text == "📁 Eksport")
async def eksport(msg: types.Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id

    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT sana, tur, amount, category, tolov_turi FROM transactions WHERE user_id=? ORDER BY sana DESC",
            (uid,))
        rows = await cur.fetchall()

    if not rows:
        await msg.answer("📭 Hali xarajat yo'q.", reply_markup=main_menu())
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sana", "Tur", "Miqdor (so'm)", "Kategoriya", "To'lov turi"])
    for sana, tur, amount, category, tolov in rows:
        writer.writerow([sana, tur, amount, category, tolov])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    file = BufferedInputFile(csv_bytes, filename=f"pulmind_{datetime.now().strftime('%Y%m%d')}.csv")

    await msg.answer_document(
        file,
        caption=f"📁 <b>PulMind eksport</b>\nJami {len(rows)} ta yozuv",
        parse_mode="HTML"
    )

# === ESLATMA ===
@dp.message(F.text == "🔔 Eslatma")
async def eslatma_boshlash(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🔔 <b>Eslatma vaqtini yozing:</b>\n\n"
        "Format: <code>HH:MM</code>\n"
        "Masalan: <code>20:00</code> (har kuni kechki 8da)",
        parse_mode="HTML"
    )
    await state.set_state(EslatmaHolat.vaqt)

@dp.message(EslatmaHolat.vaqt)
async def eslatma_vaqt(msg: types.Message, state: FSMContext):
    vaqt = msg.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", vaqt):
        await msg.answer("❌ Format xato. Masalan: <code>20:00</code>", parse_mode="HTML")
        return
    await state.update_data(vaqt=vaqt)
    await msg.answer("📝 Eslatma matni yozing:")
    await state.set_state(EslatmaHolat.xabar)

@dp.message(EslatmaHolat.xabar)
async def eslatma_xabar(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    vaqt = data.get("vaqt")
    xabar = msg.text

    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT INTO eslatmalar (user_id, vaqt, xabar) VALUES (?, ?, ?)",
            (msg.from_user.id, vaqt, xabar)
        )
        await db.commit()

    await state.clear()
    await msg.answer(
        f"✅ <b>Eslatma saqlandi!</b>\n\n"
        f"⏰ Vaqt: {vaqt}\n"
        f"📝 Xabar: {xabar}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# === ESLATMA YUBORUVCHI ===
async def eslatma_checker():
    while True:
        try:
            now = datetime.now().strftime("%H:%M")
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute(
                    "SELECT id, user_id, xabar FROM eslatmalar WHERE vaqt=? AND sent=0", (now,))
                rows = await cur.fetchall()
                for row_id, uid, xabar in rows:
                    try:
                        await bot.send_message(uid, f"🔔 <b>Eslatma:</b>\n{xabar}", parse_mode="HTML")
                        await db.execute("UPDATE eslatmalar SET sent=1 WHERE id=?", (row_id,))
                    except:
                        pass
                await db.commit()
        except:
            pass
        await asyncio.sleep(60)

# === TOZALASH ===
@dp.message(Command("tozala"))
@dp.message(F.text == "🗑 Tozalash")
async def tozala_confirm(msg: types.Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data="tozala_ha"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data="tozala_yoq"),
    ]])
    await msg.answer("⚠️ Barcha ma'lumotlarni o'chirishni istaysizmi?", reply_markup=keyboard)

@dp.callback_query(F.data == "tozala_ha")
async def tozala_ha(call: types.CallbackQuery):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("DELETE FROM transactions WHERE user_id=?", (call.from_user.id,))
        await db.execute("DELETE FROM byudjet WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.message.edit_text("✅ Barcha ma'lumotlar o'chirildi.")
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
            "Matn ko'rinishida yozing: <code>20 ming taksi</code>",
            parse_mode="HTML"
        )
        return

    await msg.answer(f"📝 Tanildi: <b>{text}</b>", parse_mode="HTML")

    amount = get_amount(text)
    if not amount:
        await msg.answer("❌ Summani topa olmadim.", parse_mode="HTML")
        return

    category = get_category(text)
    await state.update_data(amount=amount, category=category)
    await state.set_state(TolovHolat.tolov_turi)

    await msg.answer(
        f"💰 <b>{format_sum(amount)} so'm</b> — {category}\n\nTo'lov turini tanlang:",
        parse_mode="HTML",
        reply_markup=tolov_menu("v")
    )

# === MATN XARAJAT (asosiy handler) ===
MENU_BUTTONS = [
    "💰 Hisob", "📊 Statistika", "📥 Kirim", "📤 Chiqim",
    "🎯 Byudjet", "📁 Eksport", "🔔 Eslatma", "ℹ️ Yordam", "🗑 Tozalash"
]

@dp.message(F.text)
async def save(msg: types.Message, state: FSMContext):
    if msg.text in MENU_BUTTONS:
        return

    current_state = await state.get_state()
    if current_state is not None:
        return

    text = msg.text
    amount = get_amount(text)
    if not amount:
        await msg.answer(
            "❌ Summani topa olmadim.\n"
            "Masalan: <code>20 ming taksi</code> yoki <code>150000 ovqat</code>",
            parse_mode="HTML"
        )
        return

    category = get_category(text)
    await state.update_data(amount=amount, category=category)
    await state.set_state(TolovHolat.tolov_turi)

    # Byudjet tekshiruvi
    uid = msg.from_user.id
    oy = get_oy()
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT miqdor FROM byudjet WHERE user_id=? AND oy=?", (uid, oy))
        brow = await cur.fetchone()

    byudjet_ogohlantirish = ""
    if brow:
        cur_chiqim = await get_oy_chiqim(uid, oy)
        yangi_jami = cur_chiqim + amount
        if yangi_jami > brow[0]:
            ortiq = yangi_jami - brow[0]
            byudjet_ogohlantirish = f"\n\n⚠️ <b>Byudjetdan {format_sum(ortiq)} so'm oshadi!</b>"

    await msg.answer(
        f"💰 <b>{format_sum(amount)} so'm</b> — {category}{byudjet_ogohlantirish}\n\nTo'lov turini tanlang:",
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
            "INSERT INTO transactions (user_id, amount, category, tolov_turi, tur) VALUES (?, ?, ?, ?, 'chiqim')",
            (call.from_user.id, amount, category, tolov_turi)
        )
        await db.commit()

    await state.clear()

    icon = "💵" if tolov_turi == "naqd" else "💳"
    tolov_nomi = "Naqd" if tolov_turi == "naqd" else "Karta"

    await call.message.edit_text(
        f"✅ <b>Saqlandi!</b>\n\n"
        f"{icon} <b>{format_sum(amount)} so'm</b>\n"
        f"📂 {category}\n"
        f"💳 To'lov: {tolov_nomi}",
        parse_mode="HTML"
    )
    await call.answer("✅ Saqlandi!")

# === MAIN ===
async def main():
    await init_db()
    print("✅ PulMind Bot ishga tushdi!")
    asyncio.create_task(eslatma_checker())
    await dp.start_polling(bot)

asyncio.run(main())

