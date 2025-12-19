import json, random, string, base64, os, logging
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

# ================= KEEP ALIVE =================

app_server = Flask('')

@app_server.route('/')
def home():
    return "Bot Running"

def keep_alive():
    Thread(target=lambda: app_server.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )).start()

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")
OWNER, REPO = os.getenv("GITHUB_REPO").split("/")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_USER_IDS").split(",")))

main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"],
     ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True
)

def is_admin(uid): return uid in ADMIN_IDS

# ================= HELPERS =================

def generate_password():
    return "".join(random.choices(string.digits, k=6))

def calculate_expiry(duration):
    days = {
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365
    }
    if duration == "Lifetime":
        return ""
    return (datetime.now() + timedelta(days=days[duration])).strftime("%Y-%m-%d")

def is_expired(exp):
    if not exp: return False
    return datetime.strptime(exp, "%Y-%m-%d") < datetime.now()

# ================= GITHUB =================

def get_github_file():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
    r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code == 404:
        return [], None
    data = r.json()
    return json.loads(base64.b64decode(data["content"])), data["sha"]

def update_github_file(data, sha, msg):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
    payload = {
        "message": msg,
        "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        "sha": sha
    }
    r = requests.put(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=payload)
    return r.status_code in (200, 201)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("👋 Admin Panel", reply_markup=main_keyboard)

# ================= MESSAGE =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    txt = update.message.text

    if txt == "➕ Add User":
        context.user_data["mode"] = "add"
        await update.message.reply_text("📱 Send Device ID:")

    elif txt == "📋 User List":
        users, _ = get_github_file()
        kb = [[InlineKeyboardButton(
            f"{'⛔' if is_expired(u['expiry']) else '✅'} {u['Device Id']}",
            callback_data=f"idx:{i}")]
            for i, u in enumerate(users)]
        await update.message.reply_text("Users:", reply_markup=InlineKeyboardMarkup(kb))

    elif txt == "🔍 Search User":
        context.user_data["mode"] = "search"
        await update.message.reply_text("🔍 Send Device ID:")

    elif txt == "📊 Statistics":
        users, _ = get_github_file()
        await update.message.reply_text(f"Total Users: {len(users)}")

    elif context.user_data.get("mode") == "add":
        context.user_data["device"] = txt
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data="dur:1 Month"),
             InlineKeyboardButton("3 Months", callback_data="dur:3 Months")],
            [InlineKeyboardButton("6 Months", callback_data="dur:6 Months"),
             InlineKeyboardButton("1 Year", callback_data="dur:1 Year")],
            [InlineKeyboardButton("Lifetime", callback_data="dur:Lifetime")]
        ])
        await update.message.reply_text("Select Duration:", reply_markup=kb)
        context.user_data.pop("mode")

    elif context.user_data.get("mode") == "search":
        users, _ = get_github_file()
        for i, u in enumerate(users):
            if txt in u["Device Id"]:
                await show_user(update.message, i, u)
                break
        else:
            await update.message.reply_text("❌ Not found")
        context.user_data.pop("mode")

    elif "change_pass" in context.user_data:
        idx = context.user_data.pop("change_pass")
        if not txt.isdigit() or len(txt) != 6:
            await update.message.reply_text("❌ 6 digit number only")
            return
        users, sha = get_github_file()
        users[idx]["password"] = txt
        update_github_file(users, sha, "Password changed")
        await update.message.reply_text("✅ Password updated")

# ================= USER DETAILS =================

async def show_user(msg, idx, u):
    exp = u["expiry"] or "Unlimited"
    status = "⛔ EXPIRED" if is_expired(u["expiry"]) else "✅ ACTIVE"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Renew", callback_data=f"renew:{idx}"),
         InlineKeyboardButton("🔑 Change Pass", callback_data=f"pass:{idx}")],
        [InlineKeyboardButton("❌ Delete", callback_data=f"del:{idx}")]
    ])

    await msg.reply_text(
        f"📱 <b>{u['Device Id']}</b>\n"
        f"🔑 <code>{u['password']}</code>\n"
        f"📅 {exp}\n"
        f"📌 {status}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

# ================= CALLBACK =================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("dur:"):
        users, sha = get_github_file()
        dev = context.user_data["device"]

        if any(u["Device Id"] == dev for u in users):
            await q.edit_message_text("❌ Device already exists")
            return

        new_user = {
            "Device Id": dev,
            "password": generate_password(),
            "expiry": calculate_expiry(q.data.split(":")[1]),
            "chat_id": q.from_user.id
        }

        users.append(new_user)
        update_github_file(users, sha, "Add user")

        await q.edit_message_text(
            f"✅ Account Created\n\n"
            f"📱 <code>{dev}</code>\n"
            f"🔑 <code>{new_user['password']}</code>",
            parse_mode=ParseMode.HTML
        )

        await context.bot.send_message(
            new_user["chat_id"],
            f"🎉 Your account\n\n"
            f"Device: {dev}\n"
            f"Password: {new_user['password']}"
        )

    elif q.data.startswith("idx:"):
        idx = int(q.data.split(":")[1])
        users, _ = get_github_file()
        await show_user(q.message, idx, users[idx])

    elif q.data.startswith("renew:"):
        idx = int(q.data.split(":")[1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data=f"setexp:{idx}:1 Month"),
             InlineKeyboardButton("3 Months", callback_data=f"setexp:{idx}:3 Months")],
            [InlineKeyboardButton("6 Months", callback_data=f"setexp:{idx}:6 Months"),
             InlineKeyboardButton("1 Year", callback_data=f"setexp:{idx}:1 Year")],
            [InlineKeyboardButton("Lifetime", callback_data=f"setexp:{idx}:Lifetime")]
        ])
        await q.edit_message_text("Select Renewal:", reply_markup=kb)

    elif q.data.startswith("setexp:"):
        _, idx, dur = q.data.split(":")
        idx = int(idx)
        users, sha = get_github_file()
        users[idx]["expiry"] = calculate_expiry(dur)
        update_github_file(users, sha, "Renew user")

        exp = users[idx]["expiry"] or "Unlimited"

        await q.edit_message_text(
            f"✅ Renewed\n📅 {exp}",
            parse_mode=ParseMode.HTML
        )

        await context.bot.send_message(
            users[idx]["chat_id"],
            f"✅ Subscription Renewed\nNew Expiry: {exp}"
        )

    elif q.data.startswith("pass:"):
        context.user_data["change_pass"] = int(q.data.split(":")[1])
        await q.message.reply_text("🔑 Send new 6-digit password:")

    elif q.data.startswith("del:"):
        idx = int(q.data.split(":")[1])
        users, sha = get_github_file()
        users.pop(idx)
        update_github_file(users, sha, "Delete user")
        await q.edit_message_text("✅ User deleted")

# ================= MAIN =================

if __name__ == "__main__":
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
