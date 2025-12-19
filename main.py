import json, random, string, base64, os, logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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

# ----------------- SERVER -----------------
app_server = Flask('')

@app_server.route('/')
def home():
    return "Bot is running!"

def keep_alive():
    Thread(target=lambda: app_server.run(
        host='0.0.0.0',
        port=int(os.environ.get("PORT", 8080))
    )).start()

# ----------------- CONFIG -----------------
logging.basicConfig(level=logging.INFO)
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")

repo = os.getenv("GITHUB_REPO")
GITHUB_OWNER, REPO_NAME = repo.split("/") if repo else (None, None)

ADMIN_USER_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True
)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_USER_IDS

# ----------------- HELPERS -----------------
def generate_key() -> str:
    return "KEY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def calculate_expiry(duration: str) -> str:
    if duration == "Lifetime":
        return ""
    days = {
        "1 Month": 30, "2 Months": 60,
        "3 Months": 90, "6 Months": 180,
        "1 Year": 365
    }
    return (datetime.now() + timedelta(days=days[duration])).strftime("%Y-%m-%d")

# ----------------- GITHUB -----------------
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
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": msg, "content": content, "sha": sha}
    return requests.put(url, headers=headers, json=payload).status_code in (200, 201)

# ----------------- BOT -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text("👋 Management Panel", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["action"] = "device"
        await update.message.reply_text("📱 Send Device ID:")

    elif text == "📋 User List":
        users, _ = get_github_file()
        if not users:
            await update.message.reply_text("Empty list")
            return
        kb = [[InlineKeyboardButton(
            ("⛔" if u["expiry"] and datetime.strptime(u["expiry"], "%Y-%m-%d") < datetime.now() else "✅")
            + " " + u["key"], callback_data=f"idx:{i}"
        )] for i, u in enumerate(users)]
        await update.message.reply_text("📋 Users", reply_markup=InlineKeyboardMarkup(kb))

    elif text == "🔍 Search User":
        context.user_data["action"] = "search"
        await update.message.reply_text("Send Device ID or Key:")

    elif text == "📊 Statistics":
        users, _ = get_github_file()
        await update.message.reply_text(f"Total Users: {len(users)}")

    elif context.user_data.get("action") == "device":
        context.user_data["device_id"] = text
        context.user_data.pop("action")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data="dur:1 Month"),
             InlineKeyboardButton("6 Months", callback_data="dur:6 Months")],
            [InlineKeyboardButton("1 Year", callback_data="dur:1 Year"),
             InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")]
        ])
        await update.message.reply_text("Select Duration:", reply_markup=kb)

    elif context.user_data.get("action") == "search":
        users, _ = get_github_file()
        u = next((x for x in users if text in x["Device Id"] or text in x["key"]), None)
        if not u:
            await update.message.reply_text("❌ Not found")
            return
        await show_user(update.message, users.index(u), u)
        context.user_data.pop("action")

async def show_user(msg, idx, u):
    exp = u["expiry"] if u["expiry"] else "Unlimited"
    txt = (
        f"🔑 <b>Key:</b> <code>{u['key']}</code>\n"
        f"📱 <b>Device:</b> <code>{u['Device Id']}</code>\n"
        f"📅 <b>Expiry:</b> {exp}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Renew", callback_data=f"renew:{idx}"),
         InlineKeyboardButton("Delete", callback_data=f"del:{idx}")]
    ])
    await msg.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur:"):
        users, sha = get_github_file()
        dev = context.user_data["device_id"]
        if any(u["Device Id"] == dev for u in users):
            await q.edit_message_text("❌ Device already exists")
            return
        key = generate_key()
        expiry = calculate_expiry(q.data.split(":")[1])
        users.append({"Device Id": dev, "key": key, "expiry": expiry})
        update_github_file(users, sha, "Add user")
        await q.edit_message_text(
            f"✅ <b>KEY CREATED</b>\n\n🔑 <code>{key}</code>",
            parse_mode=ParseMode.HTML
        )

    elif q.data.startswith("idx:"):
        users, _ = get_github_file()
        idx = int(q.data.split(":")[1])
        await show_user(q.message, idx, users[idx])

    elif q.data.startswith("del:"):
        users, sha = get_github_file()
        idx = int(q.data.split(":")[1])
        users.pop(idx)
        update_github_file(users, sha, "Delete user")
        await q.edit_message_text("✅ Deleted")

    elif q.data.startswith("renew:"):
        idx = int(q.data.split(":")[1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data=f"set:{idx}:1 Month"),
             InlineKeyboardButton("1 Year", callback_data=f"set:{idx}:1 Year")]
        ])
        await q.edit_message_text("Renew Duration:", reply_markup=kb)

    elif q.data.startswith("set:"):
        _, idx, dur = q.data.split(":")
        idx = int(idx)
        users, sha = get_github_file()
        users[idx]["expiry"] = calculate_expiry(dur)
        update_github_file(users, sha, "Renew user")
        await q.edit_message_text("✅ Renewed")

# ----------------- RUN -----------------
if __name__ == "__main__":
    keep_alive()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
