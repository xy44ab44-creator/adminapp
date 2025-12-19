import json, random, string, base64, os
from datetime import datetime, timedelta
from threading import Thread

import requests
from dotenv import load_dotenv
from flask import Flask

from telegram import (
    Update, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------------- SERVER ----------------
app_server = Flask(__name__)

@app_server.route("/")
def home():
    return "Bot is running"

def keep_alive():
    Thread(target=lambda: app_server.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )).start()

# ---------------- CONFIG ----------------
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")
REPO = os.getenv("GITHUB_REPO")

OWNER, REPO_NAME = REPO.split("/")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

main_kb = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True
)

def is_admin(uid):
    return uid in ADMIN_IDS

# ---------------- HELPERS ----------------
def generate_key():
    return "KEY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

def calculate_expiry(duration):
    if duration == "Lifetime":
        return ""
    days = {
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365
    }
    return (datetime.now() + timedelta(days=days[duration])).strftime("%Y-%m-%d")

# ---------------- GITHUB ----------------
def get_github_file():
    url = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None
    data = r.json()
    return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]

def update_github_file(data, sha, msg):
    url = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": msg, "content": content, "sha": sha}
    return requests.put(url, headers=headers, json=payload).status_code in (200, 201)

# ---------------- BOT ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🔑 Send your KEY")
        return

    context.user_data.clear()
    await update.message.reply_text("👋 Admin Panel", reply_markup=main_kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["step"] = "device"
        await update.message.reply_text("📱 Send Device ID:")

    elif context.user_data.get("step") == "device":
        context.user_data["device_id"] = text

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data="dur:1 Month"),
             InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
            [InlineKeyboardButton("6 Months", callback_data="dur:6 Months"),
             InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
            [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")]
        ])

        await update.message.reply_text("Select Duration:", reply_markup=kb)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur:"):
        duration = q.data.split(":", 1)[1]
        device_id = context.user_data.get("device_id")

        if not device_id:
            await q.edit_message_text("❌ Device ID missing. Start again.")
            return

        users, sha = get_github_file()
        if any(u["Device Id"] == device_id for u in users):
            await q.edit_message_text("❌ Device already exists")
            return

        key = generate_key()
        expiry = calculate_expiry(duration)

        users.append({
            "Device Id": device_id,
            "key": key,
            "expiry": expiry
        })

        update_github_file(users, sha, "Add user")

        await q.edit_message_text(
            f"✅ <b>KEY CREATED</b>\n\n"
            f"🔑 <code>{key}</code>\n"
            f"📅 Expiry: {expiry if expiry else 'Unlimited'}",
            parse_mode=ParseMode.HTML
        )

        context.user_data.clear()

# ---------------- RUN ----------------
async def main():
    keep_alive()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 🔥 THIS IS THE MOST IMPORTANT LINE (RENDER FIX)
    await application.bot.delete_webhook(drop_pending_updates=True)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
