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
    return "Bot Running"

def keep_alive():
    Thread(target=lambda: app_server.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )).start()

# ---------------- CONFIG ----------------
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
FILE_PATH = os.getenv("GITHUB_PATH")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_USER_IDS").split(",")))

OWNER, REPO = GITHUB_REPO.split("/")

main_kb = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"]],
    resize_keyboard=True
)

def is_admin(uid: int) -> bool:
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
def get_users():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None
    data = r.json()
    return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]

def save_users(users, sha, msg):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    content = base64.b64encode(json.dumps(users, indent=2).encode()).decode()
    payload = {"message": msg, "content": content, "sha": sha}
    return requests.put(url, headers=headers, json=payload).status_code in (200, 201)

# ---------------- BOT ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text("Admin Panel", reply_markup=main_kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if update.message.text == "➕ Add User":
        context.user_data["step"] = "device"
        await update.message.reply_text("📱 Send Device ID:")

    elif context.user_data.get("step") == "device":
        device_id = update.message.text.strip()
        context.user_data.clear()

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1 Month", callback_data=f"dur|{device_id}|1 Month"),
                InlineKeyboardButton("3 Months", callback_data=f"dur|{device_id}|3 Months")
            ],
            [
                InlineKeyboardButton("6 Months", callback_data=f"dur|{device_id}|6 Months"),
                InlineKeyboardButton("1 Year", callback_data=f"dur|{device_id}|1 Year")
            ],
            [InlineKeyboardButton("Lifetime", callback_data=f"dur|{device_id}|Lifetime")]
        ])

        await update.message.reply_text(
            f"Device ID saved:\n<code>{device_id}</code>\n\nSelect Duration:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur|"):
        _, device_id, duration = q.data.split("|", 2)

        users, sha = get_users()

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

        if save_users(users, sha, "Add user"):
            await q.edit_message_text(
                f"✅ <b>KEY CREATED</b>\n\n"
                f"🔑 <code>{key}</code>\n"
                f"📅 Expiry: {expiry if expiry else 'Unlimited'}",
                parse_mode=ParseMode.HTML
            )
        else:
            await q.edit_message_text("❌ GitHub save failed")

# ---------------- RUN ----------------
if __name__ == "__main__":
    keep_alive()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
