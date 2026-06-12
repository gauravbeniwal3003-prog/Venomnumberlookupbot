import os
import json
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters, CallbackContext
from supabase import create_client, Client

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= HARDCODED CONFIGURATION =============
BOT_TOKEN = "7752472424:AAH8xWkDMP08fD_DEC98_kwtovPczpI9-so"
ADMIN_USER_ID = 8981634835

# Supabase Configuration
SUPABASE_URL = "https://gclwzfkxneiwzagbkwkx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbHd6Zmt4bmVpd3phZ2Jrd2t4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjY3MzEsImV4cCI6MjA4OTUwMjczMX0.N586sznUms88IaYKUBQ5LzKmrj0HYYupN3Pifojw4Ls"

# API Configuration
LOOKUP_API = "https://tracexdata-api.onrender.com/api/lookup?key=Cybersecurity&numquery={}"
CHANNEL_USERNAME = "@Venom_Intelligence"

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============= HELPER FUNCTIONS =============
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def remove_branding(text: str) -> str:
    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        if not any(brand in line.lower() for brand in ['branding', 'developer', '@gaurav', 'tracexdata', 'api_buy_link', 'website_link']):
            filtered_lines.append(line)
    return '\n'.join(filtered_lines)

async def get_user_plan(user_id: int) -> Dict:
    try:
        response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            user_data = response.data[0]
            if user_data.get("plan_expiry"):
                expiry_date = datetime.fromisoformat(user_data["plan_expiry"].replace('Z', '+00:00'))
                if expiry_date > datetime.now(expiry_date.tzinfo):
                    return {"active": True, "expiry": expiry_date, "plan_type": user_data.get("plan_type", "unlimited")}
                else:
                    supabase.table("users").update({"plan_active": False}).eq("telegram_id", user_id).execute()
            return {"active": False, "expiry": None, "plan_type": None}
        else:
            supabase.table("users").insert({"telegram_id": user_id, "username": None, "plan_active": False, "plan_expiry": None, "plan_type": None}).execute()
            return {"active": False, "expiry": None, "plan_type": None}
    except Exception as e:
        logger.error(f"Error getting user plan: {e}")
        return {"active": False, "expiry": None, "plan_type": None}

async def check_maintenance() -> bool:
    try:
        response = supabase.table("settings").select("value").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            return response.data[0].get("value", False)
        return False
    except:
        return False

def activate_plan_sync(user_id: int, username: str, days: int) -> bool:
    try:
        expiry_date = datetime.now() + timedelta(days=days)
        if user_id:
            supabase.table("users").update({"plan_active": True, "plan_expiry": expiry_date.isoformat(), "plan_type": "unlimited"}).eq("telegram_id", user_id).execute()
        else:
            supabase.table("users").update({"plan_active": True, "plan_expiry": expiry_date.isoformat(), "plan_type": "unlimited"}).eq("username", username).execute()
        return True
    except Exception as e:
        logger.error(f"Error activating plan: {e}")
        return False

# ============= KEYBOARD MENUS =============
def get_main_keyboard():
    keyboard = [
        ["📞 Number Lookup", "🚀 Get Unlimited Access"],
        ["📊 My Plan"]
    ]
    if is_admin(ADMIN_USER_ID):
        keyboard.append(["⚙️ Admin Panel"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Activate Plan", callback_data="admin_activate")],
        [InlineKeyboardButton("❌ Deactivate Plan", callback_data="admin_deactivate")],
        [InlineKeyboardButton("🔧 Toggle Maintenance Mode", callback_data="admin_maintenance")],
        [InlineKeyboardButton("📊 View All Users", callback_data="admin_users")],
        [InlineKeyboardButton("👤 Check User Info", callback_data="admin_check_user")],
        [InlineKeyboardButton("💾 Backup Data", callback_data="admin_backup")],
        [InlineKeyboardButton("🚫 Close", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    keyboard = [[InlineKeyboardButton("◀️ Back to Main Menu", callback_data="main_menu")]]
    return InlineKeyboardMarkup(keyboard)

# ============= COMMAND HANDLERS =============
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    # Run async function
    asyncio.create_task(async_get_user_plan(user.id))
    
    welcome_msg = f"""
🎉 *Welcome to Number Lookup Bot!* 🎉

🔍 *Features:*
• 📞 Lookup any Indian mobile number
• 🚀 Get unlimited access
• 📊 Track your plan status

💡 *How to use:*
Press the 📞 Number Lookup button and send a 10-digit number

⚡ *For unlimited access:* Click 🚀 Get Unlimited Access
    """
    update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_keyboard())

async def async_get_user_plan(user_id):
    await get_user_plan(user_id)

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text
    user_id = update.effective_user.id
    
    # Check if waiting for number
    if context.user_data.get('waiting_for_number') and text.isdigit() and len(text) == 10:
        # Process number lookup
        asyncio.create_task(process_number_lookup(update, context, text))
        return
    
    if text == "📞 Number Lookup":
        context.user_data['waiting_for_number'] = True
        update.message.reply_text("📱 *Please send a 10-digit mobile number*\n\nExample: 9876543210", parse_mode='Markdown', reply_markup=get_back_button())
        
    elif text == "🚀 Get Unlimited Access":
        user = update.effective_user
        username = user.username or "No username"
        user_link = f"tg://user?id={user.id}"
        admin_msg = f"""🔔 *New Request!*\n\n👤 *Username:* @{username}\n🆔 *User ID:* `{user.id}`\n📅 *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n[Contact]({user_link})"""
        context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode='Markdown', disable_web_page_preview=True)
        update.message.reply_text(f"✅ *Request Sent!*\n\nAdmin will verify and activate your plan soon!\n\nContact: {CHANNEL_USERNAME}", parse_mode='Markdown')
        
    elif text == "📊 My Plan":
        asyncio.create_task(show_my_plan(update, user_id))
        
    elif text == "⚙️ Admin Panel" and is_admin(user_id):
        update.message.reply_text("🔐 *Admin Panel*", parse_mode='Markdown', reply_markup=get_admin_keyboard())
    else:
        update.message.reply_text("❌ *Invalid option!* Use the buttons below.", parse_mode='Markdown', reply_markup=get_main_keyboard())

async def show_my_plan(update, user_id):
    plan_info = await get_user_plan(user_id)
    if plan_info['active']:
        expiry_str = plan_info['expiry'].strftime('%Y-%m-%d %H:%M:%S')
        remaining_days = (plan_info['expiry'] - datetime.now(plan_info['expiry'].tzinfo)).days
        plan_msg = f"""⭐ *Your Plan* ⭐\n━━━━━━━━━━━━━━━━━\n✅ *Status:* Active\n📋 *Type:* {plan_info['plan_type'].upper()}\n📅 *Expiry:* {expiry_str}\n⏰ *Days Left:* {remaining_days}"""
    else:
        plan_msg = """⚠️ *No Active Plan*\n━━━━━━━━━━━━━━━━━\n❌ *Status:* Inactive\n\nClick 🚀 Get Unlimited Access to request a plan!"""
    update.message.reply_text(plan_msg, parse_mode='Markdown')

async def process_number_lookup(update, context, number):
    user_id = update.effective_user.id
    plan_info = await get_user_plan(user_id)
    
    if not plan_info['active']:
        update.message.reply_text("⚠️ *No Active Plan!*\n\nClick 🚀 Get Unlimited Access to request a plan.", parse_mode='Markdown')
        context.user_data['waiting_for_number'] = False
        return
    
    processing_msg = update.message.reply_text("🔍 *Processing...*", parse_mode='Markdown')
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LOOKUP_API.format(number), timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('status') == 'success' and data.get('success'):
                        results = data.get('results', {})
                        results_found = data.get('results_found', 0)
                        
                        if results_found > 0:
                            result_text = f"📱 *Results for {number}*\n━━━━━━━━━━━━━━━━━\n📊 *Found:* {results_found}\n━━━━━━━━━━━━━━━━━\n\n"
                            for i in range(1, min(results_found + 1, 14)):
                                result_key = f"Result {i}"
                                if result_key in results:
                                    res = results[result_key]
                                    result_text += f"*Result {i}:*\n"
                                    result_text += f"👤 *Name:* {res.get('name', 'N/A')}\n"
                                    result_text += f"👨 *Father:* {res.get('father_name', 'N/A')}\n"
                                    result_text += f"📱 *Mobile:* {res.get('mobile', 'N/A')}\n"
                                    if res.get('alt_mobile') != 'n/a':
                                        result_text += f"📞 *Alt:* {res.get('alt_mobile')}\n"
                                    if res.get('aadhar_number') != 'n/a':
                                        result_text += f"🆔 *Aadhar:* {res.get('aadhar_number')}\n"
                                    result_text += f"📡 *Operator:* {res.get('operator', 'N/A')}\n"
                                    result_text += f"📍 *Circle:* {res.get('state_circle', 'N/A')}\n"
                                    result_text += f"🏠 *Address:* {res.get('address', 'N/A')}\n─────────────────\n"
                            
                            result_text = remove_branding(result_text)
                            if len(result_text) > 4000:
                                for i in range(0, len(result_text), 4000):
                                    update.message.reply_text(result_text[i:i+4000], parse_mode='Markdown')
                            else:
                                update.message.reply_text(result_text, parse_mode='Markdown')
                        else:
                            update.message.reply_text(f"❌ *No Data Found*\n\nNo information registered with *{number}*", parse_mode='Markdown')
                    else:
                        update.message.reply_text("❌ *Lookup Failed*", parse_mode='Markdown')
                else:
                    update.message.reply_text("❌ *API Error*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Lookup error: {e}")
        update.message.reply_text("❌ *Error* Try again later.", parse_mode='Markdown')
    
    # Delete processing message
    try:
        processing_msg.delete()
    except:
        pass
    context.user_data['waiting_for_number'] = False

def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == "main_menu":
        query.message.delete()
        query.message.reply_text("Main Menu:", reply_markup=get_main_keyboard())
        
    elif query.data == "admin_activate" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'activate'
        query.message.reply_text("📝 *Activate Plan*\n\nFormat:\n`username 30` or `user_id 30`\n\nExample: `@john 30` or `123456789 30`", parse_mode='Markdown')
        
    elif query.data == "admin_deactivate" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'deactivate'
        query.message.reply_text("❌ *Deactivate Plan*\n\nSend username or user_id\n\nFormat:\n`@username` or `user_id`", parse_mode='Markdown')
        
    elif query.data == "admin_maintenance" and is_admin(update.effective_user.id):
        current = asyncio.run(check_maintenance())
        new_status = not current
        supabase.table("settings").upsert({"key": "maintenance_mode", "value": new_status}).execute()
        status_text = "ENABLED 🟡" if new_status else "DISABLED 🟢"
        query.message.reply_text(f"🔧 *Maintenance Mode:* {status_text}", parse_mode='Markdown')
        
    elif query.data == "admin_users" and is_admin(update.effective_user.id):
        response = supabase.table("users").select("*").execute()
        users = response.data
        if users:
            user_list = "📊 *Users*\n━━━━━━━━━━━━━━━━━\n"
            for user in users[-20:]:
                status = "✅" if user.get('plan_active') else "❌"
                user_list += f"\n🆔 `{user['telegram_id']}`\n👤 @{user.get('username', 'N/A')}\n📋 {user.get('plan_type', 'None').upper()} {status}\n─────────────────\n"
            query.message.reply_text(user_list[:4000], parse_mode='Markdown')
        else:
            query.message.reply_text("📊 No users found.")
            
    elif query.data == "admin_check_user" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'check_user'
        query.message.reply_text("👤 *Check User*\n\nSend @username or user_id", parse_mode='Markdown')
        
    elif query.data == "admin_backup" and is_admin(update.effective_user.id):
        response = supabase.table("users").select("*").execute()
        backup_file = json.dumps(response.data, indent=2, default=str)
        query.message.reply_document(document=backup_file.encode(), filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", caption="📦 Database Backup")
        
    elif query.data == "admin_close":
        query.message.delete()

def handle_admin_input(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    
    text = update.message.text
    action = context.user_data.get('admin_action')
    
    if action == 'activate':
        parts = text.split()
        if len(parts) == 2:
            identifier = parts[0]
            days = int(parts[1])
            if identifier.startswith('@'):
                username = identifier[1:]
                if activate_plan_sync(None, username, days):
                    update.message.reply_text(f"✅ Activated @{username} for {days} days!")
                    response = supabase.table("users").select("telegram_id").eq("username", username).execute()
                    if response.data:
                        try:
                            context.bot.send_message(response.data[0]['telegram_id'], f"🎉 *Plan Activated!* {days} days unlimited access!", parse_mode='Markdown')
                        except:
                            pass
                else:
                    update.message.reply_text("❌ User not found")
            else:
                user_id = int(identifier)
                if activate_plan_sync(user_id, None, days):
                    update.message.reply_text(f"✅ Activated user {user_id} for {days} days!")
                    try:
                        context.bot.send_message(user_id, f"🎉 *Plan Activated!* {days} days unlimited access!", parse_mode='Markdown')
                    except:
                        pass
                else:
                    update.message.reply_text("❌ User not found")
        else:
            update.message.reply_text("❌ Use: `username 30` or `user_id 30`", parse_mode='Markdown')
        context.user_data['admin_action'] = None
        
    elif action == 'deactivate':
        identifier = text
        if identifier.startswith('@'):
            username = identifier[1:]
            supabase.table("users").update({"plan_active": False, "plan_type": None}).eq("username", username).execute()
            update.message.reply_text(f"❌ Deactivated @{username}")
        else:
            user_id = int(identifier)
            supabase.table("users").update({"plan_active": False, "plan_type": None}).eq("telegram_id", user_id).execute()
            update.message.reply_text(f"❌ Deactivated user {user_id}")
        context.user_data['admin_action'] = None
        
    elif action == 'check_user':
        identifier = text
        if identifier.startswith('@'):
            username = identifier[1:]
            response = supabase.table("users").select("*").eq("username", username).execute()
        else:
            user_id = int(identifier)
            response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if response.data:
            user = response.data[0]
            info = f"👤 *User Info*\n━━━━━━━━━━━━━━━━━\n🆔 `{user['telegram_id']}`\n👤 @{user.get('username', 'N/A')}\n📋 {user.get('plan_type', 'None').upper()}\n✅ Active: {user.get('plan_active')}\n📅 Expiry: {user.get('plan_expiry', 'N/A')}"
            update.message.reply_text(info, parse_mode='Markdown')
        else:
            update.message.reply_text("❌ User not found")
        context.user_data['admin_action'] = None

def forward_handler(update: Update, context: CallbackContext):
    if update.message.forward_from or update.message.forward_sender_name:
        user_id = update.message.forward_from.id if update.message.forward_from else None
        username = update.message.forward_from.username if update.message.forward_from else None
        name = update.message.forward_from.full_name if update.message.forward_from else update.message.forward_sender_name
        info_msg = f"📨 *Forwarded Account*\n\n👤 *Name:* {name}\n🆔 *ID:* `{user_id}`\n👤 *Username:* @{username if username else 'N/A'}"
        update.message.reply_text(info_msg, parse_mode='Markdown')

def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.forwarded, forward_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
    dp.add_handler(CallbackQueryHandler(handle_callback_query))
    dp.add_error_handler(error_handler)
    
    print("🤖 Bot is starting with python-telegram-bot v13.15...")
    print(f"✅ Bot Token: {BOT_TOKEN[:10]}...")
    print(f"✅ Supabase URL: {SUPABASE_URL}")
    print(f"✅ Admin ID: {ADMIN_USER_ID}")
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
