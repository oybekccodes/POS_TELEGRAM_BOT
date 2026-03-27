from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from zxing import BarCodeReader
import cv2
import sqlite3
from datetime import datetime

TOKEN = "8525651941:AAFHVd89ZP6jL6VdytMXMbreVoO86p93IEs"

# 🔐 PIN SYSTEM
PIN, AUTHORIZED = range(2)
PIN_CODE = "010203"
attempts = {}

# 🔥 DATABASE
conn = sqlite3.connect("shop.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode TEXT UNIQUE,
    name TEXT,
    price INTEGER,
    date_added TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    price INTEGER,
    date TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
)
""")
conn.commit()

reader = BarCodeReader()

# 🔹 STATES for Add Product
BARCODE, NAME, PRICE = range(3)

# 🔹 Helper decorator to check authorization
def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get("authorized"):
            await update.message.reply_text("❌ Iltimos, avval PIN kiriting /start")
            return
        return await func(update, context)
    return wrapper

# 🔹 PIN HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    attempts.setdefault(user_id, 0)
    await update.message.reply_text("🔐 PIN kodni kiriting:")
    return PIN

async def pin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if attempts[user_id] >= 3:
        await update.message.reply_text("🚫 Juda ko‘p noto‘g‘ri urinish. Kirish bloklandi.")
        return ConversationHandler.END

    if text == PIN_CODE:
        context.user_data["authorized"] = True
        await update.message.reply_text(
            "✅ To‘g‘ri! Xush kelibsiz 🎉\n"
            "Buyruqlar:\n/scan\n/search\n/add\n/today\n/report\n/products\n/storage\n/delete\n/cancel\n"
        )
        return AUTHORIZED
    else:
        attempts[user_id] += 1
        await update.message.reply_text(f"❌ Noto‘g‘ri PIN. Qolgan urinishlar: {3 - attempts[user_id]}")
        return PIN

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_add"] = False
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

# 🔹 SCAN FUNCTION
@authorized
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["scan_mode"] = True
    await update.message.reply_text("Scan mode ON ✅\nBarcode yuboring")

# 🔹 TODAY SALES
@authorized
async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT SUM(price) FROM sales WHERE date=?", (today_str,))
    total = cursor.fetchone()[0] or 0
    await update.message.reply_text(f"Bugungi savdo: {total} so‘m 💰")

# 🔹 PRODUCTS SOLD
@authorized
async def products_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("""
    SELECT p.name, COUNT(*) 
    FROM sales s
    JOIN products p ON s.product_id = p.id
    GROUP BY p.name
    """)
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("Hali sotuv yo‘q ❌")
        return
    text = "Sotilgan mahsulotlar:\n" + "\n".join([f"{name} - {count} dona" for name, count in rows])
    await update.message.reply_text(text)

# 🔹 STORAGE
@authorized
async def storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT id, barcode, name, price FROM products ORDER BY id ASC")
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("Ombor bo‘sh ❌")
        return
    text = "📦 Mahsulotlar:\n\n" + "\n\n".join([f"ID: {pid}\nBarcode: {barcode}\nName: {name}\nPrice: {price} so‘m" for pid, barcode, name, price in rows])
    await update.message.reply_text(text)

# 🔹 REPORT (monthly)
@authorized
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_month = datetime.now().strftime("%Y-%m")
    cursor.execute("""
    SELECT date, SUM(price) 
    FROM sales 
    WHERE date LIKE ? 
    GROUP BY date
    ORDER BY date ASC
    """, (f"{current_month}%",))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("Bu oyda savdo yo‘q ❌")
        return
    text = f"📊 Oylik hisobot ({current_month}):\n\n"
    total = 0
    for date, amount in rows:
        text += f"📅 {date} → {amount} so‘m\n"
        total += amount
    text += f"\n💰 Jami: {total} so‘m"
    await update.message.reply_text(text)

# 🔹 ADD PRODUCT CONVERSATION
@authorized
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_add"] = True
    await update.message.reply_text("Barcode yuboring:")
    return BARCODE

@authorized
async def add_barcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        code = update.message.text.strip()
    else:
        await update.message.reply_text("Barcode yuboring ❌")
        return BARCODE
    context.user_data["barcode"] = code
    cursor.execute("SELECT * FROM products WHERE barcode=?", (code,))
    if cursor.fetchone():
        await update.message.reply_text("Bu barcode allaqachon mavjud ⚠️")
    await update.message.reply_text(f"Barcode: {code}\nMahsulot nomi:")
    return NAME

@authorized
async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Narxi:")
    return PRICE

@authorized
async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        barcode = context.user_data["barcode"]
        name = context.user_data["name"]
        date_added = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT OR REPLACE INTO products (barcode, name, price, date_added)
            VALUES (?, ?, ?, ?)
        """, (barcode, name, price, date_added))
        conn.commit()
        context.user_data["in_add"] = False
        context.user_data["scan_mode"] = False
        await update.message.reply_text(f"{name} qo‘shildi ✅")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Narx noto‘g‘ri ❌")
        return PRICE

# 🔹 SEARCH PRODUCT BY ID
@authorized
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Mahsulot ID ni kiriting:")
    return 0  # temporary state for input

async def search_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip())
        cursor.execute("SELECT id, barcode, name, price, date_added FROM products WHERE id=?", (pid,))
        row = cursor.fetchone()
        if row:
            pid, barcode, name, price, date_added = row
            await update.message.reply_text(
                f"📦 Mahsulot topildi:\n\n"
                f"ID: {pid}\nBarcode: {barcode}\nName: {name}\nPrice: {price} so‘m\nAdded: {date_added}"
            )
        else:
            await update.message.reply_text(f"❌ Mahsulot topilmadi ID: {pid}")
    except ValueError:
        await update.message.reply_text("❌ Iltimos, faqat raqam kiriting.")
    return ConversationHandler.END

# 🔹 DELETE PRODUCT BY ID
@authorized
async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🗑 Mahsulot ID ni kiriting:")
    return 0  # temporary state for input

async def delete_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip())
        cursor.execute("SELECT name FROM products WHERE id=?", (pid,))
        row = cursor.fetchone()
        if row:
            name = row[0]
            cursor.execute("DELETE FROM products WHERE id=?", (pid,))
            cursor.execute("DELETE FROM sales WHERE product_id=?", (pid,))
            conn.commit()
            await update.message.reply_text(f"✅ {name} o‘chirildi ID: {pid}")
        else:
            await update.message.reply_text(f"❌ Mahsulot topilmadi ID: {pid}")
    except ValueError:
        await update.message.reply_text("❌ Iltimos, faqat raqam kiriting.")
    return ConversationHandler.END

# 🔹 Conversation handlers for search & delete
conv_handler_search = ConversationHandler(
    entry_points=[CommandHandler("search", search)],
    states={0: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_by_id)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)

conv_handler_delete = ConversationHandler(
    entry_points=[CommandHandler("delete", delete)],
    states={0: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_by_id)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)



# 🔹 TEXT & PHOTO HANDLERS (for scan)
@authorized
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("scan_mode"):
        code = update.message.text.strip()
        cursor.execute("SELECT id, name, price FROM products WHERE barcode=?", (code,))
        row = cursor.fetchone()
        if row:
            pid, name, price = row
            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("INSERT INTO sales (product_id, price, date) VALUES (?, ?, ?)", (pid, price, today_str))
            conn.commit()
            await update.message.reply_text(f"{name} sotildi ✅\nNarx: {price}")
        else:
            await update.message.reply_text(f"Topilmadi ❌\nCode: {code}")
        context.user_data["scan_mode"] = False

@authorized
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("scan_mode"):
        return
    photo = await update.message.photo[-1].get_file()
    file_path = f"scan_{update.message.message_id}.jpg"
    await photo.download_to_drive(file_path)
    result = reader.decode(file_path)
    if result:
        code = result.parsed
        cursor.execute("SELECT id, name, price FROM products WHERE barcode=?", (code,))
        row = cursor.fetchone()
        if row:
            pid, name, price = row
            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("INSERT INTO sales (product_id, price, date) VALUES (?, ?, ?)", (pid, price, today_str))
            conn.commit()
            await update.message.reply_text(f"{name} sotildi ✅\nNarx: {price}")
        else:
            await update.message.reply_text(f"Topilmadi ❌\nCode: {code}")
    else:
        await update.message.reply_text("Barcode topilmadi ❌")
    context.user_data["scan_mode"] = False

# 🔹 Conversation handler for add & PIN
conv_handler_pin = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, pin_check)],
        AUTHORIZED: []
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

conv_handler_add = ConversationHandler(
    entry_points=[CommandHandler("add", add_start)],
    states={
        BARCODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_barcode)],
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
        PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

# 🔹 APP
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(conv_handler_pin)
app.add_handler(conv_handler_add)

# Command handlers
app.add_handler(CommandHandler("scan", scan))
app.add_handler(CommandHandler("today", today))
app.add_handler(CommandHandler("products", products_list))
app.add_handler(CommandHandler("storage", storage))
app.add_handler(CommandHandler("report", report))
app.add_handler(conv_handler_search)
app.add_handler(conv_handler_delete)

# Message handlers
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

print("BOT IS RUNNING...")
app.run_polling()