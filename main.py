import json, random, string, base64, os, logging
from datetime import datetime, timedelta
from threading import Thread
from typing import List, Dict, Tuple, Optional

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
app_server = Flask('')

@app_server.route('/')
def home():
    return "Bot is running!"

def keep_alive():
    Thread(target=lambda: app_server.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )).start()

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")
REPO = os.getenv("GITHUB_REPO")

OWNER, REPO_NAME = REPO.split("/") if REPO else (None, None)
ADMIN_IDS = list(map(int, os.getenv("ADMIN_USER_IDS", "").split(",")))

main_kb = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True
)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ---------------- HELPERS ----------------
def generate_key(existing: set) -> str:
    while True:
        key = "KEY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        if key not in existing:
            return key

def calculate_expiry(duration: str) -> str:
    if duration == "Lifetime":
        return ""
    days = {
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365
    }
    return (datetime.now() + timedelta(days=days[duration])).strftime("%Y-%m-%d")

def is_expired(expiry: str) -> bool:
    if not expiry:
        return False
    return datetime.strptime(expiry, "%Y-%m-%d") < datetime.now()

# ---------------- GITHUB ----------------
def get_github_file() -> Tuple[List[Dict], Optional[str]]:
    url = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return [], None
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]

def update_github_file(data: List[Dict], sha: str, msg: str) -> bool:
    url = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": msg, "content": encoded, "sha": sha}
    return requests.put(url, headers=headers, json=payload).status_code in (200, 201)

# ---------------- BOT ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text("👋 Management Panel", reply_markup=main_kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text

    if text == "➕ Add User":
        context.user_data["step"] = "device"
        await update.message.reply_text("📱 Send Device ID:")

    elif text == "📋 User List":
        users, _ = get_github_file()
        if not users:
            await update.message.reply_text("Empty list")
            return

        kb = []
        for i, u in enumerate(users):
            icon = "⛔" if is_expired(u["expiry"]) else "✅"
            kb.append([InlineKeyboardButton(
                f"{icon} {u['key']}", callback_data=f"idx:{i}"
            )])

        await update.message.reply_text(
            "📋 Users", reply_markup=InlineKeyboardMarkup(kb)
        )

    elif text == "🔍 Search User":
        context.user_data["step"] = "search"
        await update.message.reply_text("Send Device ID or KEY:")

    elif text == "📊 Statistics":
        users, _ = get_github_file()
        active = sum(1 for u in users if not is_expired(u["expiry"]))
        await update.message.reply_text(
            f"📊 Total: {len(users)}\n✅ Active: {active}"
        )

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

    elif context.user_data.get("step") == "search":
        users, _ = get_github_file()
        u = next((x for x in users if text in x["Device Id"] or text in x["key"]), None)
        if not u:
            await update.message.reply_text("❌ Not found")
            return
        await show_user(update.message, users.index(u), u)
        context.user_data.clear()

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

    # ----- CREATE USER -----
    if q.data.startswith("dur:"):
        duration = q.data.split(":", 1)[1]
        device_id = context.user_data.get("device_id")

        if not device_id:
            await q.edit_message_text("❌ Device ID missing. Add again.")
            return

        users, sha = get_github_file()

        if any(u["Device Id"] == device_id for u in users):
            await q.edit_message_text("❌ Device already exists")
            return

        existing_keys = {u["key"] for u in users}
        key = generate_key(existing_keys)
        expiry = calculate_expiry(duration)

        users.append({
            "Device Id": device_id,
            "key": key,
            "expiry": expiry
        })

        update_github_file(users, sha, "Add user")

        # DM KEY TO ADMIN
        await q.message.reply_text(
            f"✅ <b>KEY CREATED</b>\n\n🔑 <code>{key}</code>",
            parse_mode=ParseMode.HTML
        )

        context.user_data.clear()

    # ----- VIEW USER -----
    elif q.data.startswith("idx:"):
        users, _ = get_github_file()
        idx = int(q.data.split(":")[1])
        await show_user(q.message, idx, users[idx])

    # ----- DELETE -----
    elif q.data.startswith("del:"):
        users, sha = get_github_file()
        idx = int(q.data.split(":")[1])
        users.pop(idx)
        update_github_file(users, sha, "Delete user")
        await q.edit_message_text("✅ Deleted")

    # ----- RENEW -----
    elif q.data.startswith("renew:"):
        idx = int(q.data.split(":")[1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data=f"set:{idx}:1 Month"),
             InlineKeyboardButton("1 Year", callback_data=f"set:{idx}:1 Year")]
        ])
        await q.edit_message_text("Select Renewal:", reply_markup=kb)

    elif q.data.startswith("set:"):
        _, idx, dur = q.data.split(":")
        idx = int(idx)
        users, sha = get_github_file()
        users[idx]["expiry"] = calculate_expiry(dur)
        update_github_file(users, sha, "Renew user")
        await q.edit_message_text("✅ Renewed Successfully")

# ---------------- RUN ----------------
if __name__ == "__main__":
    keep_alive()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
