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

app_server = Flask('')

@app_server.route('/')
def home():
    return "Bot is running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app_server.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.start()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_PATH = os.getenv("GITHUB_PATH")

full_repo = os.getenv("GITHUB_REPO")
if full_repo and "/" in full_repo:
    GITHUB_OWNER, REPO_NAME = full_repo.split("/", 1)
else:
    GITHUB_OWNER = None
    REPO_NAME = None

admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = list(map(int, admin_ids_str.split(","))) if admin_ids_str else []

main_keyboard = ReplyKeyboardMarkup(
    [["➕ Add User", "📋 User List"], ["🔍 Search User", "📊 Statistics"]],
    resize_keyboard=True,
)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS

def generate_username() -> str:
    return "user" + "".join(random.choices(string.digits, k=4))

def generate_password(length=10) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.choices(chars, k=length))

def calculate_expiry(duration: str) -> str:
    now = datetime.now()
    days_map = {
        "1 Month": 30, "2 Months": 60, "3 Months": 90,
        "6 Months": 180, "1 Year": 365
    }
    if duration == "Lifetime": return "" # Empty string for unlimited as per his JSON
    return (now + timedelta(days=days_map.get(duration, 0))).strftime("%Y-%m-%d")

async def cleanup_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    msgs = context.user_data.get('messages_to_delete', [])
    for msg_id in msgs:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except: pass
    context.user_data['messages_to_delete'] = []

def get_github_file() -> Tuple[Optional[List[Dict]], Optional[str]]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 404: return [], None
        response.raise_for_status()
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha = data["sha"]
        try: return json.loads(content), sha
        except: return [], sha
    except Exception as e:
        logger.error(f"GitHub Error: {e}")
        return None, None

def update_github_file(new_data: List[Dict], sha: str, message: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    if sha is None:
        _, current_sha = get_github_file()
        sha = current_sha

    content_str = json.dumps(new_data, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    
    payload = {"message": message, "content": content_b64}
    if sha: payload["sha"] = sha
        
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code in [200, 201]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    context.user_data.clear()
    await update.message.reply_text("👋 Welcome to the Management Panel:", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = update.message.text
    
    if text == "➕ Add User":
        context.user_data['messages_to_delete'] = [update.message.message_id]
        msg = await update.message.reply_text("📱 Send Device ID:")
        context.user_data['messages_to_delete'].append(msg.message_id)
        context.user_data['action'] = 'awaiting_device_id'
    
    elif text == "📋 User List":
        await show_users_list(update)
    
    elif text == "🔍 Search User":
        context.user_data['messages_to_delete'] = [update.message.message_id]
        msg = await update.message.reply_text("🔍 Send Device ID or Username:")
        context.user_data['messages_to_delete'].append(msg.message_id)
        context.user_data['action'] = 'awaiting_search'

    elif text == "📊 Statistics":
        await show_stats(update)

    elif context.user_data.get('action') == 'awaiting_device_id':
        context.user_data['messages_to_delete'].append(update.message.message_id)
        context.user_data['device_id'] = text
        await show_duration_keyboard(update, context)
        del context.user_data['action']
        
    elif context.user_data.get('action') == 'awaiting_search':
        context.user_data['messages_to_delete'].append(update.message.message_id)
        await perform_search(update, context, text)
        del context.user_data['action']

async def show_duration_keyboard(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month", callback_data='dur:1 Month'), InlineKeyboardButton("2 Months", callback_data='dur:2 Months')],
        [InlineKeyboardButton("3 Months", callback_data='dur:3 Months'), InlineKeyboardButton("6 Months", callback_data='dur:6 Months')],
        [InlineKeyboardButton("1 Year", callback_data='dur:1 Year'), InlineKeyboardButton("Lifetime", callback_data='dur:Lifetime')]
    ])
    msg = await update.message.reply_text("Select Duration:", reply_markup=kb)
    context.user_data['messages_to_delete'].append(msg.message_id)

async def show_users_list(update):
    users, _ = get_github_file()
    if not users:
        await update.message.reply_text("List is empty.")
        return
    
    kb_list = []
    for i, u in enumerate(users):
        icon = "✅"
        expiry_val = u.get('expiry', "")
        if expiry_val != "":
             try:
                 if datetime.strptime(expiry_val, "%Y-%m-%d") < datetime.now(): 
                     icon = "⛔"
             except: pass
        
        button_text = f"{icon} {u.get('username', 'Unknown')}"
        kb_list.append([InlineKeyboardButton(button_text, callback_data=f'idx:{i}')])
    
    await update.message.reply_text("📋 <b>Current Users:</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb_list))

async def perform_search(update, context, query):
    users, _ = get_github_file()
    found = next((u for u in users if query.lower() in str(u.get('Device Id', '')).lower() or query.lower() in u.get('username', '').lower()), None)
    if found:
        idx = users.index(found)
        await show_user_details_by_index(update.message, idx, found)
    else:
        await update.message.reply_text("❌ User not found.")
    await cleanup_messages(context, update.effective_chat.id)

async def show_user_details_by_index(message_obj, index, user_data):
    exp_display = user_data.get('expiry') if user_data.get('expiry') else "Unlimited"
    txt = (f"👤 <b>{user_data.get('username')}</b>\n"
           f"📱 ID: <code>{user_data.get('Device Id')}</code>\n"
           f"🔑 Pass: <code>{user_data.get('password')}</code>\n"
           f"📅 Exp: {exp_display}")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Renew", callback_data=f'renew:{index}'), InlineKeyboardButton("Delete", callback_data=f'del:{index}')],
        [InlineKeyboardButton("Back", callback_data='home')]
    ])
    if hasattr(message_obj, 'edit_message_text'):
        await message_obj.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message_obj.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_stats(update):
    users, _ = get_github_file()
    count = len(users) if users else 0
    await update.message.reply_text(f"Total Users in Database: {count}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    
    if data == 'home':
        await cleanup_messages(context, q.message.chat_id)
        await q.message.reply_text("Main Menu:", reply_markup=main_keyboard)
        return

    if data.startswith('dur:'):
        duration = data.split(':')[1]
        await create_user(q, context, duration)
    
    elif data.startswith('idx:'):
        idx = int(data.split(':')[1])
        users, _ = get_github_file()
        if users and idx < len(users):
            await show_user_details_by_index(q.message, idx, users[idx])
    
    elif data.startswith('del:'):
        idx = int(data.split(':')[1])
        users, sha = get_github_file()
        if users and idx < len(users):
            deleted = users.pop(idx)
            if update_github_file(users, sha, f"Deleted {deleted.get('username')}"):
                await q.edit_message_text(f"✅ User '{deleted.get('username')}' deleted.")
            else:
                await q.message.reply_text("Error: Deletion failed")
    
    elif data.startswith('renew:'):
        idx = int(data.split(':')[1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Month", callback_data=f'setexp:{idx}:1 Month'), InlineKeyboardButton("1 Year", callback_data=f'setexp:{idx}:1 Year')],
            [InlineKeyboardButton("Cancel", callback_data=f'idx:{idx}')]
        ])
        await q.edit_message_text("Select renewal period:", reply_markup=kb)

    elif data.startswith('setexp:'):
        parts = data.split(':')
        idx, dur = int(parts[1]), parts[2]
        users, sha = get_github_file()
        if users and idx < len(users):
            users[idx]['expiry'] = calculate_expiry(dur)
            if update_github_file(users, sha, f"Renew {users[idx]['username']}"):
                exp_text = users[idx]['expiry'] if users[idx]['expiry'] else "Unlimited"
                renewal_msg = (
                    f"<b>✅ Subscription Renewed!</b>\n\n"
                    f"👤 <b>User:</b> <code>{users[idx]['username']}</code>\n"
                    f"📅 <b>Expiry:</b> {exp_text}\n\n"
                    f"💐 <b>Thank you for staying with us!</b>"
                )
                await cleanup_messages(context, q.message.chat_id)
                await q.message.reply_text(renewal_msg, parse_mode=ParseMode.HTML)
            else:
                await q.message.reply_text("Error: Renewal failed")

async def create_user(q, context, duration):
    dev_id = context.user_data.get('device_id')
    if not dev_id: return
    
    users, sha = get_github_file()
    if users is None: users = []
    
    if any(u.get('Device Id') == dev_id for u in users):
        await q.edit_message_text("❌ This Device ID is already registered!")
        return

    new_u = {
        "Device Id": dev_id,
        "username": generate_username(),
        "password": generate_password(),
        "expiry": calculate_expiry(duration)
    }
    users.append(new_u)
    
    if update_github_file(users, sha, f"Add {new_u['username']}"):
        exp_text = new_u['expiry'] if new_u['expiry'] else "Unlimited"
        client_msg = (
            f"<b>🎉 Account Created!</b>\n\n"
            f"👤 <b>Username:</b> <code>{new_u['username']}</code>\n"
            f"🔑 <b>Password:</b> <code>{new_u['password']}</code>\n"
            f"⏳ <b>Plan:</b> {duration}\n"
            f"📅 <b>Expiry:</b> {exp_text}\n\n"
            f"🌹 <b>Thank you for your purchase!</b>"
        )
        await cleanup_messages(context, q.message.chat_id)
        await q.message.reply_text(client_msg, parse_mode=ParseMode.HTML)
    else:
        await q.edit_message_text("Error: Failed to update GitHub")

if __name__ == "__main__":
    keep_alive()
    if not TELEGRAM_BOT_TOKEN:
        print("CRITICAL: TELEGRAM_TOKEN not found in environment.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()

