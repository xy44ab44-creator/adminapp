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

if full_repo and "/" in full_repo:
    GITHUB_OWNER, REPO_NAME = full_repo.split("/", 1)
else:
    GITHUB_OWNER = REPO_NAME = None

admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = list(map(int, admin_ids_str.split(","))) if admin_ids_str else []

# ================= KEYBOARD =================
main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True,
)

# ================= HELPERS =================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS

def generate_key() -> str:
    chars = string.ascii_uppercase + string.digits
    return "-".join("".join(random.choices(chars, k=6)) for _ in range(4))

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
    return (now + timedelta(days=days.get(duration, 0))).strftime("%Y-%m-%d")

async def cleanup_messages(context, chat_id):
    for msg_id in context.user_data.get("messages_to_delete", []):
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass
    context.user_data["messages_to_delete"] = []

# ================= GITHUB =================
def get_github_file() -> Tuple[Optional[List[Dict]], Optional[str]]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 404:
            return [], None
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]
    except Exception as e:
        logger.error(e)
        return None, None

def update_github_file(data: List[Dict], sha: str, msg: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()

    payload = {"message": msg, "content": content}
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in (200, 201)

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text(
        "👋 <b>Key Management Panel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard,
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
        await show_users(update)

    elif text == "🔍 Search User":
        context.user_data["action"] = "search"
        msg = await update.message.reply_text("🔍 Send Device ID:")
        context.user_data["messages_to_delete"] = [msg.message_id]

    elif text == "📊 Statistics":
        users, _ = get_github_file()
        await update.message.reply_text(f"📊 Total Keys: {len(users or [])}")

    elif context.user_data.get("action") == "device":
        context.user_data["device"] = text
        del context.user_data["action"]
        await show_duration(update, context)

    elif context.user_data.get("action") == "search":
        await search_user(update, context, text)
        del context.user_data["action"]

# ================= UI =================
async def show_duration(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month", callback_data="dur:1 Month"),
         InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
        [InlineKeyboardButton("6 Months", callback_data="dur:6 Months"),
         InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
        [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")]
    ])
    msg = await update.message.reply_text("⏳ Select Duration:", reply_markup=kb)
    context.user_data["messages_to_delete"].append(msg.message_id)

async def show_users(update):
    users, _ = get_github_file()
    if not users:
        await update.message.reply_text("No users found.")
        return

    kb = []
    for i, u in enumerate(users):
        kb.append([InlineKeyboardButton(
            f"🔑 {u.get('Device Id')}",
            callback_data=f"idx:{i}"
        )])

    await update.message.reply_text(
        "📋 <b>Users</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def search_user(update, context, q):
    users, _ = get_github_file()
    user = next((u for u in users if q in u.get("Device Id", "")), None)
    if user:
        idx = users.index(user)
        await show_user_detail(update.message, idx, user)
    else:
        await update.message.reply_text("❌ Not found")

# ================= CALLBACK =================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur:"):
        await create_user(q, context, q.data.split(":")[1])

    elif q.data.startswith("idx:"):
        users, _ = get_github_file()
        idx = int(q.data.split(":")[1])
        await show_user_detail(q.message, idx, users[idx])

    elif q.data.startswith("del:"):
        users, sha = get_github_file()
        idx = int(q.data.split(":")[1])
        deleted = users.pop(idx)
        update_github_file(users, sha, "Delete key")
        await q.edit_message_text("✅ Deleted")

# ================= CREATE USER =================
async def create_user(q, context, duration):
    dev = context.user_data.get("device")
    users, sha = get_github_file()
    if any(u["Device Id"] == dev for u in users):
        await q.edit_message_text("❌ Device already exists")
        return

    new = {
        "Device Id": dev,
        "key": generate_key(),
        "expiry": calculate_expiry(duration),
    }
    users.append(new)
    update_github_file(users, sha, "Add key")

    await cleanup_messages(context, q.message.chat_id)
    await q.message.reply_text(
        f"<b>✅ KEY GENERATED</b>\n\n"
        f"📱 Device: <code>{dev}</code>\n"
        f"🔐 Key:\n<code>{new['key']}</code>\n"
        f"📅 Expiry: {new['expiry'] or 'Unlimited'}",
        parse_mode=ParseMode.HTML,
    )

# ================= USER DETAIL =================
async def show_user_detail(msg, idx, u):
    await msg.reply_text(
        f"📱 <b>Device ID:</b> <code>{u['Device Id']}</code>\n"
        f"🔐 <b>Key:</b>\n<code>{u['key']}</code>\n"
        f"📅 <b>Expiry:</b> {u['expiry'] or 'Unlimited'}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Delete", callback_data=f"del:{idx}")]
        ]),
    )

# ================= MAIN =================
if __name__ == "__main__":
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM TOKEN MISSING")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
