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

# ================= KEEP ALIVE SERVER =================

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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================= ENV =================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")

full_repo = os.getenv("GITHUB_REPO")
GITHUB_OWNER, REPO_NAME = full_repo.split("/", 1)

ADMIN_USER_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

# ================= KEYBOARD =================

main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True,
)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS

# ================= PASSWORD (NUMERIC ONLY) =================

def generate_password(length=6) -> str:
    return "".join(random.choices(string.digits, k=length))

def calculate_expiry(duration: str) -> str:
    now = datetime.now()
    days = {
        "1 Month": 30,
        "2 Months": 60,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365,
    }
    if duration == "Lifetime":
        return ""
    return (now + timedelta(days=days[duration])).strftime("%Y-%m-%d")

# ================= CLEANUP =================

async def cleanup_messages(context, chat_id):
    for msg_id in context.user_data.get("messages_to_delete", []):
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass
    context.user_data["messages_to_delete"] = []

# ================= GITHUB =================

def get_github_file():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]

def update_github_file(data, sha, msg):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {
        "message": msg,
        "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        "sha": sha,
    }
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in [200, 201]

# ================= START =================

async def start(update: Update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 Management Panel",
        reply_markup=main_keyboard
    )

# ================= MESSAGE HANDLER =================

async def handle_message(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["action"] = "device"
        msg = await update.message.reply_text("📱 Send Device ID:")
        context.user_data["messages_to_delete"] = [msg.message_id]

    elif text == "📋 User List":
        await show_users(update)

    elif text == "🔍 Search User":
        context.user_data["action"] = "search"
        msg = await update.message.reply_text("🔍 Send Device ID:")
        context.user_data["messages_to_delete"] = [msg.message_id]

    elif text == "📊 Statistics":
        users, _ = get_github_file()
        await update.message.reply_text(f"Total Users: {len(users)}")

    elif context.user_data.get("action") == "device":
        context.user_data["device"] = text
        await show_duration(update)
        del context.user_data["action"]

    elif context.user_data.get("action") == "search":
        await search_user(update, context, text)
        del context.user_data["action"]

# ================= DURATION =================

async def show_duration(update):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month", callback_data="dur:1 Month"),
         InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
        [InlineKeyboardButton("6 Months", callback_data="dur:6 Months"),
         InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
        [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")]
    ])
    await update.message.reply_text("Select Duration:", reply_markup=kb)

# ================= USER LIST =================

async def show_users(update):
    users, _ = get_github_file()
    if not users:
        await update.message.reply_text("No users found.")
        return

    kb = []
    for i, u in enumerate(users):
        kb.append([InlineKeyboardButton(u["Device Id"], callback_data=f"idx:{i}")])

    await update.message.reply_text(
        "📋 Users:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= SEARCH =================

async def search_user(update, context, query):
    users, _ = get_github_file()
    for i, u in enumerate(users):
        if query in u["Device Id"]:
            await show_user_detail(update.message, i, u)
            await cleanup_messages(context, update.effective_chat.id)
            return
    await update.message.reply_text("❌ Not found")

# ================= DETAILS =================

async def show_user_detail(msg, idx, u):
    exp = u["expiry"] if u["expiry"] else "Unlimited"
    text = (
        f"📱 <b>Device ID:</b> <code>{u['Device Id']}</code>\n"
        f"🔑 <b>Password:</b> <code>{u['password']}</code>\n"
        f"📅 <b>Expiry:</b> {exp}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Renew", callback_data=f"renew:{idx}"),
         InlineKeyboardButton("Delete", callback_data=f"del:{idx}")]
    ])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

# ================= CALLBACK =================

async def handle_callback(update: Update, context):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur:"):
        await create_user(q, context, q.data.split(":")[1])

    elif q.data.startswith("idx:"):
        idx = int(q.data.split(":")[1])
        users, _ = get_github_file()
        await show_user_detail(q.message, idx, users[idx])

    elif q.data.startswith("del:"):
        idx = int(q.data.split(":")[1])
        users, sha = get_github_file()
        users.pop(idx)
        update_github_file(users, sha, "Delete user")
        await q.edit_message_text("✅ User deleted")

# ================= CREATE USER =================

async def create_user(q, context, duration):
    users, sha = get_github_file()
    dev = context.user_data["device"]

    if any(u["Device Id"] == dev for u in users):
        await q.edit_message_text("❌ Device already exists")
        return

    new_user = {
        "Device Id": dev,
        "password": generate_password(),
        "expiry": calculate_expiry(duration),
    }

    users.append(new_user)
    update_github_file(users, sha, "Add user")

    exp = new_user["expiry"] if new_user["expiry"] else "Unlimited"
    await q.edit_message_text(
        f"✅ <b>Account Created</b>\n\n"
        f"📱 <code>{dev}</code>\n"
        f"🔑 <code>{new_user['password']}</code>\n"
        f"📅 {exp}",
        parse_mode=ParseMode.HTML,
    )

# ================= MAIN =================

if __name__ == "__main__":
    keep_alive()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
