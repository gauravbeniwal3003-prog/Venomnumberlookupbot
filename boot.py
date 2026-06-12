import os
import json
import logging
import requests
import http.server
import socketserver
import threading
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
ADMIN_USER_ID = 7850023357  

# Supabase Configuration
SUPABASE_URL = "https://gclwzfkxneiwzagbkwkx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbHd6Zmt4bmVpd3phZ2Jrd2t4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjY3MzEsImV4cCI6MjA4OTUwMjczMX0.N586sznUms88IaYKUBQ5LzKmrj0HYYupN3Pifojw4Ls"

# API Configuration
LOOKUP_API = "https://tracexdata-api.onrender.com/api/lookup?key=Cybersecurity&numquery={}"
ADMIN_USERNAME = "@Venom_Intelligence"

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============= RENDER PORT BINDING FIX =============
def start_health_server():
    """Starts a simple HTTP server to satisfy Render's port binding requirement"""
    class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is running smoothly!")

    port = int(os.environ.get("PORT", 8080))
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", port), HealthCheckHandler) as httpd:
        logger.info(f"Health check server started on port {port}")
        httpd.serve_forever()

# ============= HELPER FUNCTIONS =============
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def escape_username(username: Optional[str]) -> str:
    """Escapes underscores in usernames with a backslash for Telegram Markdown stability"""
    if not username:
        return "N/A"
    return username.replace("_", "\\_")

def remove_branding(text: str) -> str:
    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        if not any(brand in line.lower() for brand in ['branding', 'developer', '@gaurav', 'tracexdata', 'api_buy_link', 'website_link']):
            filtered_lines.append(line)
    return '\n'.join(filtered_lines)

def get_user_plan(user_id: int, username: str = None) -> Dict:
    try:
        if username and username.startswith('@'):
            username = username[1:]
            
        response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            user_data = response.data[0]
            if username and user_data.get("username") != username:
                supabase.table("users").update({"username": username}).eq("telegram_id", user_id).execute()
                
            if user_data.get("plan_expiry"):
                expiry_date = datetime.fromisoformat(user_data["plan_expiry"].replace('Z', '+00:00'))
                if expiry_date > datetime.now(expiry_date.tzinfo):
                    return {"active": True, "expiry": expiry_date, "plan_type": "unlimited"}
                else:
                    supabase.table("users").update({"plan_active": False}).eq("telegram_id", user_id).execute()
            return {"active": False, "expiry": None, "plan_type": None}
        else:
            supabase.table("users").insert({
                "telegram_id": user_id, 
                "username": username, 
                "plan_active": False, 
                "plan_expiry": None, 
                "plan_type": None
            }).execute()
            return {"active": False, "expiry": None, "plan_type": None}
    except Exception as e:
        logger.error(f"Error getting user plan: {e}")
        return {"active": False, "expiry": None, "plan_type": None}

def check_maintenance() -> bool:
    try:
        response = supabase.table("settings").select("value").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            val = response.data[0].get("value")
            if isinstance(val, str):
                return val.lower() == 'true'
            return bool(val)
        return False
    except Exception as e:
        logger.error(f"Maintenance check error: {e}")
        return False

def activate_plan(user_id: int, username: str, days: int) -> bool:
    try:
        expiry_date = datetime.now() + timedelta(days=days)
        if user_id:
            supabase.table("users").upsert({
                "telegram_id": user_id,
                "plan_active": True, 
                "plan_expiry": expiry_date.isoformat(), 
                "plan_type": "unlimited"
            }).execute()
            return True
        elif username:
            if username.startswith('@'):
                username = username[1:]
            response = supabase.table("users").select("telegram_id").eq("username", username).execute()
            if response.data:
                target_id = response.data[0]['telegram_id']
                supabase.table("users").update({
                    "plan_active": True, 
                    "plan_expiry": expiry_date.isoformat(), 
                    "plan_type": "unlimited"
                }).eq("telegram_id", target_id).execute()
                return True
        return False
    except Exception as e:
        logger.error(f"Error activating plan: {e}")
        return False

def number_lookup(number: str):
    try:
        response = requests.get(LOOKUP_API.format(number), timeout=12)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Lookup error: {e}")
        return None

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
        [InlineKeyboardButton("📊 View Recent Users", callback_data="admin_users")],
        [InlineKeyboardButton("👤 Check User Info", callback_data="admin_check_user")],
        [InlineKeyboardButton("🚫 Close Menu", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    keyboard = [[InlineKeyboardButton("◀️ Back to Main Menu", callback_data="main_menu")]]
    return InlineKeyboardMarkup(keyboard)

# ============= COMMAND HANDLERS =============
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_plan(user.id, user.username)
    
    welcome_msg = f"""
⚡ *Welcome to Premium Number Lookup Bot!* ⚡

✨ *Features:*
• 📞 *Number Lookup:* Pull registered data securely.
• 🚀 *Get Unlimited Access:* Request administrative access validation.
• 📊 *My Plan:* Check real-time plan info instantly.

💡 *Instructions:*
Press the **📞 Number Lookup** button and provide any 10-digit mobile number!
    """
    update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_keyboard(), disable_web_page_preview=True)

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text
    user_id = update.effective_user.id
    
    # Intercept administrative custom entries securely
    if is_admin(user_id) and context.user_data.get('admin_action'):
        handle_admin_input(update, context)
        return

    # Global Maintenance Mode Interception
    if check_maintenance() and not is_admin(user_id):
        update.message.reply_text("🔧 *System Maintenance:* The bot is currently undergoing structural maintenance. Please check back later.", parse_mode='Markdown')
        return
    
    # One-Time Validation Loop to avoid multi-lookup glitch
    if context.user_data.get('waiting_for_number'):
        if text.isdigit() and len(text) == 10:
            context.user_data['waiting_for_number'] = False  
            process_number_lookup(update, context, text)
        else:
            update.message.reply_text("❌ *Invalid Number Format!* Please provide a valid 10-digit number.", parse_mode='Markdown', reply_markup=get_back_button())
        return
    
    if text == "📞 Number Lookup":
        context.user_data['waiting_for_number'] = True
        update.message.reply_text("📱 *Please send the 10-digit mobile number you want to look up:*", parse_mode='Markdown', reply_markup=get_back_button())
        
    elif text == "🚀 Get Unlimited Access":
        user = update.effective_user
        escaped_user = escape_username(user.username)
        username_str = f"@{escaped_user}" if user.username else "No Username"
        user_link = f"tg://user?id={user.id}"
        
        admin_msg = f"🔔 *New Access Plan Request!*\n\n👤 *User:* {username_str}\n🆔 *User ID:* `{user.id}`\n[Direct User Link]({user_link})"
        context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode='Markdown', disable_web_page_preview=True)
        
        escaped_admin = escape_username(ADMIN_USERNAME)
        update.message.reply_text(f"🚀 *Contact Owner:* {escaped_admin}\n\nThe owner has been notified and will verify and activate your plan manually!", parse_mode='Markdown', disable_web_page_preview=True)
        
    elif text == "📊 My Plan":
        plan_info = get_user_plan(user_id, update.effective_user.username)
        if plan_info['active']:
            expiry_str = plan_info['expiry'].strftime('%Y-%m-%d %H:%M:%S UTC')
            remaining = plan_info['expiry'] - datetime.now(plan_info['expiry'].tzinfo)
            plan_msg = f"⭐ *Your Premium Subscription* ⭐\n━━━━━━━━━━━━━━━━━\n✅ *Status:* Active\n📋 *Plan Type:* {plan_info['plan_type'].upper()}\n📅 *Expires:* {expiry_str}\n⏳ *Remaining:* {remaining.days} Days"
        else:
            escaped_admin = escape_username(ADMIN_USERNAME)
            plan_msg = f"⚠️ *No Active Subscription!*\n━━━━━━━━━━━━━━━━━\n❌ *Status:* Inactive\n\nClick **🚀 Get Unlimited Access** to upgrade your permissions via {escaped_admin}."
        update.message.reply_text(plan_msg, parse_mode='Markdown', disable_web_page_preview=True)
        
    elif text == "⚙️ Admin Panel" and is_admin(user_id):
        update.message.reply_text("🔐 *Administrative Management Panel*", parse_mode='Markdown', reply_markup=get_admin_keyboard())

def process_number_lookup(update: Update, context: CallbackContext, number: str):
    user_id = update.effective_user.id
    plan_info = get_user_plan(user_id)
    
    if not plan_info['active']:
        update.message.reply_text("⚠️ *Access Denied!* An active plan is required to look up records. Please purchase a plan.", parse_mode='Markdown')
        return
    
    processing_msg = update.message.reply_text("⚡ *Processing Database Search...*", parse_mode='Markdown')
    data = number_lookup(number)
    
    if data and data.get('status') == 'success' and data.get('success'):
        results = data.get('results', {})
        results_found = data.get('results_found', 0)
        
        if results_found > 0:
            result_text = f"📱 *Lookup Results for:* `{number}`\n━━━━━━━━━━━━━━━━━\n📊 *Total Records Found:* {results_found}\n━━━━━━━━━━━━━━━━━\n\n"
            for i in range(1, results_found + 1):
                result_key = f"Result {i}"
                if result_key in results:
                    res = results[result_key]
                    result_text += f"*Record #{i}:*\n"
                    result_text += f"👤 *Name:* {res.get('name', 'N/A')}\n"
                    result_text += f"👨 *Father Name:* {res.get('father_name', 'N/A')}\n"
                    result_text += f"📱 *Mobile:* {res.get('mobile', 'N/A')}\n"
                    if res.get('alt_mobile') and res.get('alt_mobile') != 'n/a':
                        result_text += f"📞 *Alt Mobile:* {res.get('alt_mobile')}\n"
                    if res.get('aadhar_number') and res.get('aadhar_number') != 'n/a':
                        result_text += f"🆔 *Aadhar:* `{res.get('aadhar_number')}`\n"
                    result_text += f"📡 *Operator:* {res.get('operator', 'N/A')} ({res.get('state_circle', 'N/A')})\n"
                    result_text += f"🏠 *Address:* {res.get('address', 'N/A')}\n─────────────────\n"
            
            clean_text = remove_branding(result_text)
            
            if len(clean_text) > 4000:
                for chunk in [clean_text[i:i+4000] for i in range(0, len(clean_text), 4000)]:
                    update.message.reply_text(chunk, parse_mode='Markdown', disable_web_page_preview=True)
            else:
                update.message.reply_text(clean_text, parse_mode='Markdown', disable_web_page_preview=True)
        else:
            update.message.reply_text(f"❌ *No Data Found*\n\nNo information is registered with this number: *{number}*", parse_mode='Markdown')
    else:
        update.message.reply_text("❌ *System Error:* Unable to complete data fetch. API might be experiencing downtime.", parse_mode='Markdown')
    
    try:
        processing_msg.delete()
    except:
        pass

def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == "main_menu":
        context.user_data['waiting_for_number'] = False
        query.message.delete()
        query.message.reply_text("📋 *Main Interactive Menu:*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        
    elif query.data == "admin_activate" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'activate'
        query.message.reply_text("📝 *Provide Activation Data:*\n\nFormat:\n`@username days` or `userid days` \n\n*Example:* `@John_Doe 30` or `7850023357 30`", parse_mode='Markdown')
        
    elif query.data == "admin_deactivate" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'deactivate'
        query.message.reply_text("❌ *Provide Account Deactivation Info:*\n\nSend Target `@username` or raw `user_id` directly.", parse_mode='Markdown')
        
    elif query.data == "admin_maintenance" and is_admin(update.effective_user.id):
        current = check_maintenance()
        new_status = not current
        supabase.table("settings").upsert({"key": "maintenance_mode", "value": new_status}).execute()
        status_txt = "ENABLED 🟡" if new_status else "DISABLED 🟢"
        query.message.reply_text(f"🔧 *Maintenance Mode updated successfully:* {status_txt}", parse_mode='Markdown')
        
    elif query.data == "admin_users" and is_admin(update.effective_user.id):
        response = supabase.table("users").select("*").execute()
        users = response.data or []
        if users:
            msg = "📊 *Recent Database Entries:*\n━━━━━━━━━━━━━━━━━\n"
            for u in users[-15:]:
                status = "✅ Premium" if u.get('plan_active') else "❌ Inactive"
                escaped_u = escape_username(u.get('username', 'N/A'))
                msg += f"🆔 ID: `{u['telegram_id']}` | User: @{escaped_u}\n📈 Status: {status}\n─────────────────\n"
            query.message.reply_text(msg[:4000], parse_mode='Markdown', disable_web_page_preview=True)
        else:
            query.message.reply_text("No recorded system entry indexes inside the database.", parse_mode='Markdown')
            
    elif query.data == "admin_check_user" and is_admin(update.effective_user.id):
        context.user_data['admin_action'] = 'check_user'
        query.message.reply_text("👤 Send the User ID or Username profile to crawl data logs:", parse_mode='Markdown')
        
    elif query.data == "admin_close":
        query.message.delete()

def handle_admin_input(update: Update, context: CallbackContext):
    text = update.message.text
    action = context.user_data.get('admin_action')
    context.user_data['admin_action'] = None  
    
    if action == 'activate':
        parts = text.split()
        if len(parts) == 2:
            target, days_str = parts[0], parts[1]
            if not days_str.isdigit():
                update.message.reply_text("❌ Activation Error: Day criteria value must be an integer.")
                return
            days = int(days_str)
            
            success = False
            if target.startswith('@'):
                success = activate_plan(None, target, days)
            else:
                try:
                    success = activate_plan(int(target), None, days)
                except: pass
                
            if success:
                escaped_target = escape_username(target)
                update.message.reply_text(f"✅ *Plan Activated Successfully:* {escaped_target} for {days} days.", parse_mode='Markdown', disable_web_page_preview=True)
            else:
                update.message.reply_text("❌ Sync Error: Profile target identity not found inside database indexes.")
        else:
            update.message.reply_text("❌ Input Syntax Validation Failed.")
            
    elif action == 'deactivate':
        if text.startswith('@'):
            supabase.table("users").update({"plan_active": False, "plan_expiry": None}).eq("username", text[1:]).execute()
        else:
            try: supabase.table("users").update({"plan_active": False, "plan_expiry": None}).eq("telegram_id", int(text)).execute()
            except: pass
        escaped_text = escape_username(text)
        update.message.reply_text(f"❌ *Plan Deactivated:* {escaped_text}", parse_mode='Markdown', disable_web_page_preview=True)
        
    elif action == 'check_user':
        if text.startswith('@'):
            res = supabase.table("users").select("*").eq("username", text[1:]).execute()
        else:
            try: res = supabase.table("users").select("*").eq("telegram_id", int(text)).execute()
            except: res = None
            
        if res and res.data:
            u = res.data[0]
            escaped_u = escape_username(u.get('username', 'N/A'))
            update.message.reply_text(f"👤 *Database User Profile Info:*\n\n🆔 ID: `{u['telegram_id']}`\n👤 Name: @{escaped_u}\n✅ Plan Active: {u.get('plan_active')}\n📅 Expiration: {u.get('plan_expiry')}", parse_mode='Markdown', disable_web_page_preview=True)
        else:
            update.message.reply_text("❌ User profiling extraction lookup target missing.")

def forward_handler(update: Update, context: CallbackContext):
    if is_admin(update.effective_user.id):
        msg = update.message
        target_user = msg.forward_from
        if target_user:
            escaped_username = escape_username(target_user.username)
            info = f"📨 *Forwarded Profile Extraction:*\n\n👤 *Full Name:* {target_user.full_name}\n🆔 *User ID:* `{target_user.id}`\n👤 *Username:* @{escaped_username if target_user.username else 'None'}"
            msg.reply_text(info, parse_mode='Markdown', disable_web_page_preview=True)
        elif msg.forward_sender_name:
            msg.reply_text(f"📨 *Forwarded Profile (Privacy Lock Active):*\n\n👤 *Name:* {msg.forward_sender_name}\n⚠️ User restricted forward data exposure.")
        else:
            msg.reply_text("❌ Metadata parsing on forward pack failed.")

def error_handler(update, context):
    logger.error(f"Telegram processing pipeline error caught: {context.error}")

def main():
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.forwarded, forward_handler))
    dp.add_handler(CallbackQueryHandler(handle_callback_query))
    dp.add_error_handler(error_handler)
    
    print("🤖 Live Deployment Status: Active...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()