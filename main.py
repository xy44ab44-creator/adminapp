import json
import random
import string
import base64
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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
    return "Bot is running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app_server.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_server).start()

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= ENV =================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")

full_repo = os.getenv("GITHUB_REPO")
GITHUB_OWNER, REPO_NAME = full_repo.split("/") if full_repo else (None, None)

ADMIN_USER_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

# ================= KEYBOARD =================
main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True,
)

# ================= HELPERS =================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS

def generate_password(length=8) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))

def calculate_expiry(duration: str) -> str:
    if duration == "Lifetime":
        return ""
    days_map = {
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365
    }
    return (datetime.now() + timedelta(days=days_map.get(duration, 0))).strftime("%Y-%m-%d")

async def cleanup_messages(context, chat_id):
    for msg_id in context.user_data.get("messages_to_delete", []):
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass
    context.user_data["messages_to_delete"] = []

# ================= GITHUB =================
def get_github_file() -> Tuple[List[Dict], Optional[str]]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None

    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]

def update_github_file(data: List[Dict], sha: str, msg: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
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
    context.user_data.clear()
    await update.message.reply_text(
        "🔐 Management Panel",
        reply_markup=main_keyboard
    )

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["messages_to_delete"] = [update.message.message_id]
        msg = await update.message.reply_text("📱 Send Device ID:")
        context.user_data["messages_to_delete"].append(msg.message_id)
        context.user_data["action"] = "device"

    elif text == "📋 User List":
        users, _ = get_github_file()
        await update.message.reply_text(json.dumps(users, indent=2))

    elif text == "📊 Statistics":
        users, _ = get_github_file()
        await update.message.reply_text(f"Total Users: {len(users)}")

    elif context.user_data.get("action") == "device":
        context.user_data["device"] = text
        del context.user_data["action"]

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data="dur:1 Month")],
            [InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
            [InlineKeyboardButton("6 Months", callback_data="dur:6 Months")],
            [InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
            [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")],
        ])
        msg = await update.message.reply_text("⏳ Select Duration:", reply_markup=kb)
        context.user_data["messages_to_delete"].append(msg.message_id)

# ================= CALLBACK =================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    duration = q.data.split(":")[1]
    device_id = context.user_data.get("device")

    users, sha = get_github_file()

    new_user = {
        "password": generate_password(),
        "Device Id": device_id,
        "expiry": calculate_expiry(duration)
    }

    users.append(new_user)
    update_github_file(users, sha, "Add user")

    await cleanup_messages(context, q.message.chat_id)
    await q.message.reply_text(
        f"<b>✅ USER ADDED</b>\n\n"
        f"📱 Device ID: <code>{device_id}</code>\n"
        f"🔑 Password: <code>{new_user['password']}</code>\n"
        f"📅 Expiry: {new_user['expiry'] or 'Unlimited'}",
        parse_mode=ParseMode.HTML
    )

# ================= MAIN =================
if __name__ == "__main__":
    keep_alive()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
