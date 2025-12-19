import json
import random
import string
import base64
import os
import logging
from datetime import datetime, timedelta
from threading import Thread

import requests
from dotenv import load_dotenv
from flask import Flask

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= KEEP ALIVE =================
app_server = Flask('')

@app_server.route('/')
def home():
    return "Bot is running"

def keep_alive():
    Thread(target=lambda: app_server.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))).start()

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_PATH = os.getenv("GITHUB_PATH")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

OWNER, REPO = GITHUB_REPO.split("/")

# ================= KEYBOARD =================
main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"], ["📊 Statistics"]],
    resize_keyboard=True
)

# ================= HELPERS =================
def is_admin(uid):
    return uid in ADMIN_IDS

def generate_password():
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=8))

def calculate_expiry(plan):
    if plan == "Lifetime":
        return ""
    days = {
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365,
    }
    return (datetime.now() + timedelta(days=days[plan])).strftime("%Y-%m-%d")

# ================= GITHUB =================
def get_file():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]

def save_file(data, sha, msg):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {
        "message": msg,
        "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        "sha": sha,
    }
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in (200, 201)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🔐 Password Management Panel", reply_markup=main_keyboard)

# ================= MESSAGE =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["step"] = "device"
        await update.message.reply_text("📱 Send Device ID")

    elif text == "📋 User List":
        users, _ = get_file()
        msg = "\n".join([f"📱 {u['Device Id']} | 🔑 {u['password']}" for u in users])
        await update.message.reply_text(msg or "Empty")

    elif text == "📊 Statistics":
        users, _ = get_file()
        await update.message.reply_text(f"Total Users: {len(users)}")

    elif context.user_data.get("step") == "device":
        context.user_data["device"] = text
        context.user_data["step"] = None

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data="dur:1 Month")],
            [InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
            [InlineKeyboardButton("6 Months", callback_data="dur:6 Months")],
            [InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
            [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")],
        ])
        await update.message.reply_text("Select Plan:", reply_markup=kb)

# ================= CALLBACK =================
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    duration = q.data.split(":")[1]
    device = context.user_data.get("device")

    users, sha = get_file()

    new_user = {
        "password": generate_password(),
        "Device Id": device,
        "expiry": calculate_expiry(duration)
    }

    users.append(new_user)
    save_file(users, sha, "Add user")

    await q.message.reply_text(
        f"<b>✅ USER ADDED</b>\n\n"
        f"📱 Device: <code>{device}</code>\n"
        f"🔑 Password: <code>{new_user['password']}</code>\n"
        f"📅 Expiry: {new_user['expiry'] or 'Unlimited'}",
        parse_mode=ParseMode.HTML
    )

# ================= MAIN =================
if __name__ == "__main__":
    keep_alive()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()
