import os
import json
import logging
import requests
import http.server
import socketserver
import threading
import re
from datetime import datetime, timedelta
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters, CallbackContext
from supabase import create_client, Client

# Enable system logging framework
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= ENVIRONMENT SECURED CONFIGURATION =============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7526906483:AAG7KGrVqSxkGjP7FJf-uvCEfzbHE5qkYHs")
ADMIN_USER_ID = 8981634835  

# Supabase Storage Core Configurations
SUPABASE_URL = "https://gclwzfkxneiwzagbkwkx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbHd6Zmt4bmVpd3phZ2Jrd2t4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjY3MzEsImV4cCI6MjA4OTUwMjczMX0.N586sznUms88IaYKUBQ5LzKmrj0HYYupN3Pifojw4Ls"

# Third-Party Registry Target Endpoint
LOOKUP_API = "https://tracexdata-api.onrender.com/api/lookup?key=Cybersecurity&numquery={}"
VEHICLE_LOOKUP_API = "https://tracexdata-api.onrender.com/api/vehicle?key=Venomcybervcle&query={}"

# Initialize Database Pipeline Connection 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cost Analysis Metrics
CREDIT_COST_PER_LOOKUP = 10
CREDIT_COST_PER_VEHICLE = 2
FREE_LOOKUP_CREDITS = 10

# Credit-based plans
CREDIT_PLANS = {
    "plan_19": {"price": 19, "credits": 30, "label": "💰 ₹19 → 30 Credits"},
    "plan_39": {"price": 39, "credits": 70, "label": "💰 ₹39 → 70 Credits"},
    "plan_69": {"price": 69, "credits": 150, "label": "💰 ₹69 → 150 Credits"},
    "plan_129": {"price": 129, "credits": 350, "label": "💰 ₹129 → 350 Credits"},
    "plan_199": {"price": 199, "credits": 700, "label": "💰 ₹199 → 700 Credits"},
    "plan_399": {"price": 399, "credits": 1800, "label": "💰 ₹399 → 1800 Credits"},
}

# Unlimited plan duration options (in hours/days)
UNLIMITED_PLANS = {
    "2h": {"duration_hours": 2, "price": 39, "label": "🏅 ₹39 → 2 Hours Unlimited", "duration_text": "2 hours"},
    "6h": {"duration_hours": 6, "price": 69, "label": "🏅 ₹69 → 6 Hours Unlimited", "duration_text": "6 hours"},
    "12h": {"duration_hours": 12, "price": 129, "label": "🏅 ₹129 → 12 Hours Unlimited", "duration_text": "12 hours"},
    "1d": {"duration_hours": 24, "price": 199, "label": "🏅 ₹199 → 1 Day Unlimited", "duration_text": "1 day"},
    "3d": {"duration_hours": 72, "price": 399, "label": "🏅 ₹399 → 3 Days Unlimited", "duration_text": "3 days"},
    "7d": {"duration_hours": 168, "price": 799, "label": "🏅 ₹799 → 7 Days Unlimited", "duration_text": "7 days"},
    "15d": {"duration_hours": 360, "price": 1499, "label": "🏅 ₹1499 → 15 Days Unlimited", "duration_text": "15 days"},
}

pending_sessions: Dict[str, Dict] = {}

# ============= RENDER PLATFORM PORT BINDINGS =============
def start_health_server():
    class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot Active")

    port = int(os.environ.get("PORT", 8080))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), HealthCheckHandler) as httpd:
            logger.info(f"Port active: {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Server error: {e}")

# ============= CORE FUNCTIONS =============
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def is_banned(user_id: int) -> bool:
    try:
        response = supabase.table("users").select("is_banned").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0].get("is_banned", False)
        return False
    except:
        return False

def ban_user(user_id: int) -> bool:
    try:
        res = supabase.table("users").update({"is_banned": True}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except:
        return False

def unban_user(user_id: int) -> bool:
    try:
        res = supabase.table("users").update({"is_banned": False}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except:
        return False

def escape_md(text: str) -> str:
    if not text:
        return "N/A"
    return str(text).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")

def check_maintenance() -> bool:
    try:
        response = supabase.table("settings").select("value").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            val = response.data[0].get("value")
            return val.lower() == 'true' if isinstance(val, str) else bool(val)
        return False
    except:
        return False

def get_mode() -> str:
    """Get current mode from database"""
    try:
        response = supabase.table("settings").select("mode").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            mode = response.data[0].get("mode")
            if mode in ['free', 'paid']:
                return mode
        set_mode('paid')
        return 'paid'
    except Exception as e:
        logger.error(f"Get mode error: {e}")
        return 'paid'

def set_mode(mode: str) -> bool:
    """Set mode in database"""
    try:
        if mode not in ['free', 'paid']:
            return False
        check = supabase.table("settings").select("key").eq("key", "maintenance_mode").execute()
        if check.data and len(check.data) > 0:
            supabase.table("settings").update({"mode": mode}).eq("key", "maintenance_mode").execute()
        else:
            supabase.table("settings").insert({"key": "maintenance_mode", "value": "false", "mode": mode}).execute()
        logger.info(f"Mode set to: {mode}")
        return True
    except Exception as e:
        logger.error(f"Set mode error: {e}")
        return False

def is_unlimited_active(user_id: int) -> tuple:
    try:
        response = supabase.table("users").select("unlimited_expiry").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            expiry_str = response.data[0].get("unlimited_expiry")
            if expiry_str:
                expiry_date = datetime.fromisoformat(expiry_str)
                if expiry_date > datetime.now():
                    remaining_hours = int((expiry_date - datetime.now()).total_seconds() / 3600)
                    return True, expiry_date, remaining_hours
        return False, None, 0
    except Exception as e:
        logger.error(f"Check unlimited error: {e}")
        return False, None, 0

def get_user_identifier(user_id: int, username: str = None) -> str:
    if username:
        return f"@{username} (ID: {user_id})"
    return f"ID: {user_id}"

def sync_account(user_id: int, username: str = None) -> Dict:
    try:
        if username and username.startswith('@'):
            username = username[1:]
        
        response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            user_info = response.data[0]
            if username and user_info.get("username") != username:
                supabase.table("users").update({"username": username}).eq("telegram_id", user_id).execute()
            return user_info
        else:
            new_profile = {
                "telegram_id": user_id,
                "username": username,
                "credits": FREE_LOOKUP_CREDITS,
                "total_lookups_done": 0,
                "unlimited_expiry": None,
                "is_banned": False
            }
            supabase.table("users").insert(new_profile).execute()
            return new_profile
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return {"telegram_id": user_id, "username": username, "credits": FREE_LOOKUP_CREDITS, "total_lookups_done": 0, "unlimited_expiry": None, "is_banned": False}

def modify_credits(user_id: int, volume: int) -> bool:
    if is_admin(user_id):
        return True
    try:
        profile = sync_account(user_id)
        target_bal = max(0, profile.get("credits", 0) + volume)
        res = supabase.table("users").update({"credits": target_bal}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Modify credits error: {e}")
        return False

def activate_unlimited_plan(user_id: int, duration_hours: int) -> bool:
    try:
        expiry_date = datetime.now() + timedelta(hours=duration_hours)
        expiry_iso = expiry_date.isoformat()
        logger.info(f"Activating unlimited for user {user_id}: {duration_hours} hours, expires at {expiry_iso}")
        
        res = supabase.table("users").update({"unlimited_expiry": expiry_iso}).eq("telegram_id", user_id).execute()
        
        if res.data and len(res.data) > 0:
            logger.info(f"Unlimited plan activated successfully for user {user_id}")
            return True
        else:
            logger.error(f"Failed to activate unlimited for user {user_id}: No data returned")
            return False
    except Exception as e:
        logger.error(f"Activate unlimited error: {e}")
        return False

def deactivate_unlimited_plan(user_id: int) -> bool:
    try:
        res = supabase.table("users").update({"unlimited_expiry": None}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Deactivate unlimited error: {e}")
        return False

def giveaway_to_all_users(credits_amount: int) -> tuple:
    try:
        response = supabase.table("users").select("telegram_id").eq("is_banned", False).execute()
        if not response.data:
            return 0, 0, 0
        total_users = len(response.data)
        success_count = 0
        for user in response.data:
            if modify_credits(user['telegram_id'], credits_amount):
                success_count += 1
        return success_count, total_users - success_count, total_users
    except Exception as e:
        logger.error(f"Giveaway error: {e}")
        return 0, 0, 0

def broadcast_to_all_users(message: str, context: CallbackContext) -> tuple:
    try:
        response = supabase.table("users").select("telegram_id").eq("is_banned", False).execute()
        if not response.data:
            return 0, 0, 0
        total_users = len(response.data)
        success_count = 0
        for user in response.data:
            try:
                context.bot.send_message(chat_id=user['telegram_id'], text=message, parse_mode='Markdown')
                success_count += 1
            except:
                pass
        return success_count, total_users - success_count, total_users
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        return 0, 0, 0

def send_qr_with_payment_info(chat_id, plan, plan_type, session_id, context, callback_msg=None):
    qr_path = os.path.join(os.getcwd(), "qr.png")
    
    text = f"""
💳 *PAYMENT DETAILS*
━━━━━━━━━━━━━━━━━━━━━
🆔 ID: `{session_id}`
📦 Plan: {plan['label']}
💰 Amount: ₹{plan['price']}
━━━━━━━━━━━━━━━━━━━━━

📲 *Scan QR to Pay*

After payment, send screenshot here.
"""
    
    if os.path.exists(qr_path):
        try:
            with open(qr_path, 'rb') as qr_file:
                if callback_msg:
                    callback_msg.reply_photo(photo=InputFile(qr_file), caption=text, parse_mode='Markdown')
                else:
                    context.bot.send_photo(chat_id=chat_id, photo=InputFile(qr_file), caption=text, parse_mode='Markdown')
            return True
        except Exception as e:
            logger.error(f"QR send error: {e}")
            if callback_msg:
                callback_msg.reply_text(f"{text}\n\n⚠️ QR temporarily unavailable. Contact admin.", parse_mode='Markdown')
            else:
                context.bot.send_message(chat_id=chat_id, text=f"{text}\n\n⚠️ QR unavailable. Contact admin.", parse_mode='Markdown')
            return False
    else:
        if callback_msg:
            callback_msg.reply_text(text, parse_mode='Markdown')
        else:
            context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        return False

# ============= KEYBOARDS =============
def get_main_keyboard():
    menu = [
        ["📞 Number Lookup", "🚗 Vehicle Lookup"],
        ["💳 Buy Credits", "🌟 Buy Unlimited"],
        ["📊 My Plan", "🆘 Support"],
        ["⚙️ Admin Panel"]
    ]
    return ReplyKeyboardMarkup(menu, resize_keyboard=True)

def get_purchase_keyboard():
    buttons = [
        [InlineKeyboardButton("💳 Credit Plans", callback_data="show_credit_plans")],
        [InlineKeyboardButton("🌟 Unlimited Plans", callback_data="show_unlimited_plans")],
        [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_credit_plans_keyboard():
    buttons = []
    for key, data in CREDIT_PLANS.items():
        buttons.append([InlineKeyboardButton(data['label'], callback_data=f"credit_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="back_to_purchase")])
    return InlineKeyboardMarkup(buttons)

def get_unlimited_plans_keyboard():
    buttons = []
    for key, data in UNLIMITED_PLANS.items():
        buttons.append([InlineKeyboardButton(data['label'], callback_data=f"unlimited_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="back_to_purchase")])
    return InlineKeyboardMarkup(buttons)

def get_admin_keyboard():
    # Get current status for display
    current_mode = get_mode()
    mode_emoji = "🔓" if current_mode == 'free' else "🔒"
    mode_text = "FREE" if current_mode == 'free' else "PAID"
    
    maint_status = "ON" if check_maintenance() else "OFF"
    maint_emoji = "🔴" if check_maintenance() else "🟢"
    
    layout = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
        [InlineKeyboardButton("👤 Search User", callback_data="adm_search_user")],
        [InlineKeyboardButton("💳 Add/Remove Credits", callback_data="adm_modify_credits")],
        [InlineKeyboardButton("🌟 Activate Unlimited", callback_data="adm_activate_unlimited")],
        [InlineKeyboardButton("❌ Deactivate Unlimited", callback_data="adm_deactivate_unlimited")],
        [InlineKeyboardButton("🚫 Ban/Unban User", callback_data="adm_ban_unban")],
        [InlineKeyboardButton("🎁 Giveaway (All Users)", callback_data="adm_giveaway_all")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")],
        [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(layout)

def get_settings_keyboard():
    current_mode = get_mode()
    mode_emoji = "🔓" if current_mode == 'free' else "🔒"
    mode_text = "FREE" if current_mode == 'free' else "PAID"
    
    maint_status = "ON" if check_maintenance() else "OFF"
    maint_emoji = "🔴" if check_maintenance() else "🟢"
    
    layout = [
        [InlineKeyboardButton(f"🔄 Mode: {mode_emoji} {mode_text}", callback_data="adm_toggle_mode")],
        [InlineKeyboardButton(f"🔧 Maintenance: {maint_emoji} {maint_status}", callback_data="adm_toggle_maint")],
        [InlineKeyboardButton("◀️ Back to Admin", callback_data="adm_back")]
    ]
    return InlineKeyboardMarkup(layout)

def get_ban_unban_keyboard():
    layout = [
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_user")],
        [InlineKeyboardButton("✅ Unban User", callback_data="adm_unban_user")],
        [InlineKeyboardButton("◀️ Back to Admin", callback_data="adm_back")]
    ]
    return InlineKeyboardMarkup(layout)

def get_unlimited_duration_keyboard():
    buttons = []
    for key, data in UNLIMITED_PLANS.items():
        buttons.append([InlineKeyboardButton(data['label'], callback_data=f"unlimited_duration_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data="admin_close")])
    return InlineKeyboardMarkup(buttons)

def get_support_reply_keyboard(user_id, msg_id):
    keyboard = [[InlineKeyboardButton("📝 Reply", callback_data=f"reply_{user_id}_{msg_id}")]]
    return InlineKeyboardMarkup(keyboard)

# ============= HANDLERS =============
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    profile = sync_account(user.id, user.username)
    
    if profile.get('is_banned', False):
        update.message.reply_text("❌ You are banned from using this bot. Contact admin for support.")
        return
    
    mode = get_mode()
    if mode == 'free':
        welcome = f"""
✅ *Welcome to FREE Mode!* 🎉

🎯 All features are FREE!
📞 Unlimited Number Lookups
🚗 Unlimited Vehicle Lookups
📊 No credits needed

Enjoy! 🚀
    """
    else:
        welcome = f"""
✅ *Welcome!*

🎁 New users get 1 FREE lookup!

📞 Number Lookup - Find details
🚗 Vehicle Lookup - Find vehicle registration metrics
💳 Buy Credits - Purchase credits
🌟 Buy Unlimited - Time-based plans
📊 My Plan - Check balance

1 number lookup = {CREDIT_COST_PER_LOOKUP} credits
1 vehicle lookup = {CREDIT_COST_PER_VEHICLE} credits
    """
    update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=get_main_keyboard())

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if is_banned(user_id) and not is_admin(user_id):
        update.message.reply_text("❌ You are banned. Contact admin for support.")
        return
    
    if is_admin(user_id) and context.user_data.get('admin_state'):
        process_admin_input(update, context)
        return
    
    if context.user_data.get('support_reply_to'):
        forward_support_reply(update, context)
        return
    
    if check_maintenance() and not is_admin(user_id):
        update.message.reply_text("🔧 Under maintenance. Try later.")
        return
    
    mode = get_mode()
    
    if context.user_data.get('awaiting_lookup'):
        if text.isdigit() and len(text) == 10:
            context.user_data['awaiting_lookup'] = False
            execute_lookup(update, context, text)
        else:
            update.message.reply_text("❌ Send a valid 10-digit number.")
        return

    if context.user_data.get('awaiting_vehicle_lookup'):
        context.user_data['awaiting_vehicle_lookup'] = False
        execute_vehicle_lookup(update, context, text.upper())
        return
    
    if "Number Lookup" in text:
        if mode == 'free':
            context.user_data['awaiting_lookup'] = True
            update.message.reply_text("📱 Enter 10-digit number:")
        else:
            profile = sync_account(user_id)
            unlimited_active, _, remaining = is_unlimited_active(user_id)
            
            if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
                update.message.reply_text(f"⚠️ Need {CREDIT_COST_PER_LOOKUP} credits.\nBalance: {profile.get('credits', 0)}\n\nBuy credits or unlimited plan!")
                return
            context.user_data['awaiting_lookup'] = True
            update.message.reply_text("📱 Enter 10-digit number:")

    elif "Vehicle Lookup" in text:
        if mode == 'free':
            context.user_data['awaiting_vehicle_lookup'] = True
            update.message.reply_text("🚗 Enter Vehicle Registration Number (e.g. BR07PB6268):")
        else:
            profile = sync_account(user_id)
            unlimited_active, _, remaining = is_unlimited_active(user_id)
            
            if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_VEHICLE:
                update.message.reply_text(f"⚠️ Need {CREDIT_COST_PER_VEHICLE} credits.\nBalance: {profile.get('credits', 0)}\n\nBuy credits or unlimited plan!")
                return
            context.user_data['awaiting_vehicle_lookup'] = True
            update.message.reply_text("🚗 Enter Vehicle Registration Number (e.g. BR07PB6268):")
    
    elif "Buy Credits" in text:
        if mode == 'free':
            update.message.reply_text("🎉 *FREE MODE ACTIVE*\n\nYou don't need to buy credits!\nAll features are free to use.\n\nJust use 📞 Number Lookup!", parse_mode='Markdown')
        else:
            update.message.reply_text("Select plan type:", reply_markup=get_purchase_keyboard())
    
    elif "Buy Unlimited" in text:
        if mode == 'free':
            update.message.reply_text("🎉 *FREE MODE ACTIVE*\n\nYou don't need unlimited plans!\nAll features are free to use.\n\nJust use 📞 Number Lookup!", parse_mode='Markdown')
        else:
            update.message.reply_text("Select plan type:", reply_markup=get_purchase_keyboard())
    
    elif "My Plan" in text:
        profile = sync_account(user_id)
        unlimited_active, expiry, remaining = is_unlimited_active(user_id)
        mode = get_mode()
        
        if mode == 'free':
            msg = f"""
⭐ *FREE MODE* ⭐
━━━━━━━━━━━━━━━━━━━━━
🎉 All features are FREE!
📞 Unlimited Number Lookups
🚗 Unlimited Vehicle Lookups
💳 No credits needed
━━━━━━━━━━━━━━━━━━━━━
📊 Total lookups: {profile.get('total_lookups_done', 0)}
            """
        elif unlimited_active:
            expiry_str = expiry.strftime('%Y-%m-%d %H:%M')
            msg = f"""
⭐ *YOUR PLAN*
━━━━━━━━━━━━━━━━━━━━━
🌟 *Unlimited Active*
⏰ Expires: {expiry_str}
📅 Remaining: {remaining} hours
━━━━━━━━━━━━━━━━━━━━━
📊 Total lookups: {profile.get('total_lookups_done', 0)}
            """
        else:
            msg = f"""
⭐ *YOUR PLAN*
━━━━━━━━━━━━━━━━━━━━━
💳 *Credit Balance*
💰 Credits: {profile.get('credits', 0)}
━━━━━━━━━━━━━━━━━━━━━
📊 Total lookups: {profile.get('total_lookups_done', 0)}
💡 1 number lookup = {CREDIT_COST_PER_LOOKUP} credits
💡 1 vehicle lookup = {CREDIT_COST_PER_VEHICLE} credits
            """
        update.message.reply_text(msg, parse_mode='Markdown')
    
    elif "Support" in text or "🆘" in text:
        update.message.reply_text(
            "🆘 *SUPPORT*\n\nSend your message here. Admin will reply within 24 hours.\n\nType your question below:",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_support'] = True
    
    elif "Admin Panel" in text:
        if is_admin(user_id):
            update.message.reply_text("🔐 Admin Panel:", reply_markup=get_admin_keyboard())
        else:
            update.message.reply_text("❌ Access denied.")
    
    elif context.user_data.get('awaiting_support'):
        msg_text = text
        user = update.effective_user
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        support_id = f"SUP-{user_id}-{int(datetime.now().timestamp())}"
        user_identifier = get_user_identifier(user_id, user.username)
        
        admin_msg = f"""
open-ended request payload:
🆔 ID: `{support_id}`
👤 User: {user_identifier}
⏰ Time: {timestamp}
━━━━━━━━━━━━━━━━━━━━━
📝 *Message:*
{msg_text}
━━━━━━━━━━━━━━━━━━━━━
        """
        
        context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_msg,
            parse_mode='Markdown',
            reply_markup=get_support_reply_keyboard(user_id, int(datetime.now().timestamp()))
        )
        
        update.message.reply_text("✅ Message sent to support. You'll get reply soon!")
        context.user_data['awaiting_support'] = False
    
    elif context.user_data.get('payment_session'):
        handle_receipt_upload(update, context)
    
    else:
        update.message.reply_text("Use menu buttons below 👇", reply_markup=get_main_keyboard())

def forward_support_reply(update: Update, context: CallbackContext):
    reply_text = update.message.text
    target_user_id = context.user_data.get('support_reply_to')
    
    if target_user_id:
        try:
            context.bot.send_message(
                chat_id=target_user_id,
                text=f"🆘 *Support Reply:*\n\n{reply_text}\n\n━━━━━━━━━━━━━━━━━\nReply to continue chat.",
                parse_mode='Markdown'
            )
            update.message.reply_text("✅ Reply sent to user.")
        except Exception as e:
            logger.error(f"Reply error: {e}")
            update.message.reply_text("❌ Failed to send. User may have blocked bot.")
        context.user_data['support_reply_to'] = None

def execute_lookup(update: Update, context: CallbackContext, number: str):
    user_id = update.effective_user.id
    mode = get_mode()
    
    if mode == 'free':
        profile = sync_account(user_id)
        supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
        cost_msg = "0 Credits (FREE MODE)"
        unlimited_active = False
        remaining = 0
    else:
        profile = sync_account(user_id)
        unlimited_active, _, remaining = is_unlimited_active(user_id)
        
        if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
            update.message.reply_text("⚠️ Insufficient balance!")
            return
        
        if not is_admin(user_id) and not unlimited_active:
            modify_credits(user_id, -CREDIT_COST_PER_LOOKUP)
        
        supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
        
        if unlimited_active:
            cost_msg = f"0 Credits (Unlimited - {remaining}h left)"
        elif is_admin(user_id):
            cost_msg = "0 Credits (Admin)"
        else:
            cost_msg = f"{CREDIT_COST_PER_LOOKUP} Credits"
    
    msg = update.message.reply_text("🔍 Searching...")
    
    try:
        response = requests.get(LOOKUP_API.format(number), timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == 'failed' or data.get('results_found', 0) == 0:
                update.message.reply_text(f"❌ No data found for: {number}")
                return
            
            if data.get('success') and data.get('results_found', 0) > 0:
                records = data.get('results', {})
                total = data.get('results_found', 0)
                
                result = f"📱 *Number:* `{number}`\n📊 *Found:* {total}\n💸 *Cost:* {cost_msg}\n━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                for i in range(1, min(total + 1, 5)):
                    key = f"Result {i}"
                    if key in records:
                        item = records[key]
                        name = escape_md(str(item.get('name', 'N/A')))
                        fname = escape_md(str(item.get('father_name', 'N/A')))
                        addr = escape_md(str(item.get('address', 'N/A')))
                        
                        result += f"*#{i}*\n"
                        result += f"👤 Name: {name}\n"
                        result += f"👨 Father: {fname}\n"
                        result += f"📱 Mobile: {item.get('mobile', 'N/A')}\n"
                        if item.get('alt_mobile') and item.get('alt_mobile') != 'n/a':
                            result += f"📞 Alt: {item.get('alt_mobile')}\n"
                        result += f"🏠 Address: {addr}\n━━━━━━━━━━━━━━━━━━━━━\n"
                
                update.message.reply_text(result, parse_mode='Markdown')
            else:
                update.message.reply_text(f"❌ No data for: {number}")
        else:
            update.message.reply_text("❌ API error. Try later.")
    except Exception as e:
        logger.error(f"Lookup error: {e}")
        update.message.reply_text("❌ Error occurred.")
    finally:
        try:
            msg.delete()
        except:
            pass

def execute_vehicle_lookup(update: Update, context: CallbackContext, query_str: str):
    user_id = update.effective_user.id
    mode = get_mode()
    
    if mode == 'free':
        profile = sync_account(user_id)
        supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
        unlimited_active = False
    else:
        profile = sync_account(user_id)
        unlimited_active, _, remaining = is_unlimited_active(user_id)
        
        if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_VEHICLE:
            update.message.reply_text("⚠️ Insufficient balance!")
            return
        
        if not is_admin(user_id) and not unlimited_active:
            modify_credits(user_id, -CREDIT_COST_PER_VEHICLE)
        
        supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
    
    msg = update.message.reply_text("🔍 Fetching Vehicle Records...")
    
    try:
        response = requests.get(VEHICLE_LOOKUP_API.format(query_str), timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and 'results' in data and 'raw_data' in data['results']:
                raw_data = data['results']['raw_data']
                update.message.reply_text(raw_data)
            else:
                update.message.reply_text(f"❌ No data found for vehicle query: {query_str}")
        else:
            update.message.reply_text("❌ API error on remote engine. Try later.")
    except Exception as e:
        logger.error(f"Vehicle Lookup error: {e}")
        update.message.reply_text("❌ An execution error occurred.")
    finally:
        try:
            msg.delete()
        except:
            pass

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    action = query.data
    user_id = update.effective_user.id
    query.answer()
    
    # Reply to support message
    if action.startswith("reply_"):
        if is_admin(user_id):
            parts = action.split("_")
            target_user_id = int(parts[1])
            context.user_data['support_reply_to'] = target_user_id
            query.message.reply_text(f"💬 Replying to user {get_user_identifier(target_user_id)}\n\nSend your reply message:")
            query.message.delete()
        return
    
    # Payment approvals
    if action.startswith("approve_"):
        if is_admin(user_id):
            session_id = action.replace("approve_", "")
            process_payment_approval(update, context, session_id, True)
        return
    
    if action.startswith("decline_"):
        if is_admin(user_id):
            session_id = action.replace("decline_", "")
            process_payment_approval(update, context, session_id, False)
        return
    
    mode = get_mode()
    
    # Credit plans
    if action.startswith("credit_"):
        if mode == 'free':
            query.message.reply_text("🎉 *FREE MODE ACTIVE*\n\nYou don't need to buy credits!\nAll features are free.", parse_mode='Markdown')
            return
            
        plan_key = action.replace("credit_", "")
        if plan_key in CREDIT_PLANS:
            plan = CREDIT_PLANS[plan_key]
            session_id = f"TXN-{user_id}-{int(datetime.now().timestamp())}"
            pending_sessions[session_id] = {
                "user_id": user_id,
                "type": "credit",
                "plan": plan_key,
                "credits": plan['credits'],
                "price": plan['price'],
                "timestamp": datetime.now().isoformat(),
                "label": plan['label']
            }
            
            send_qr_with_payment_info(user_id, plan, "credit", session_id, context, query.message)
            
            user_identifier = get_user_identifier(user_id, update.effective_user.username)
            admin_msg = f"💰 *New Payment Request*\n━━━━━━━━━━━━━━━━━━━━━\n🆔 ID: `{session_id}`\n👤 User: {user_identifier}\n📦 Plan: {plan['label']}\n💵 Amount: ₹{plan['price']}"
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{session_id}"),
                 InlineKeyboardButton("❌ Decline", callback_data=f"decline_{session_id}")]
            ])
            context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode='Markdown', reply_markup=admin_keyboard)
            
            context.user_data['payment_session'] = session_id
        return
    
    # Unlimited plans
    if action.startswith("unlimited_"):
        if mode == 'free':
            query.message.reply_text("🎉 *FREE MODE ACTIVE*\n\nYou don't need unlimited plans!\nAll features are free.", parse_mode='Markdown')
            return
            
        plan_key = action.replace("unlimited_", "")
        if plan_key in UNLIMITED_PLANS:
            plan = UNLIMITED_PLANS[plan_key]
            session_id = f"UNL-{user_id}-{int(datetime.now().timestamp())}"
            pending_sessions[session_id] = {
                "user_id": user_id,
                "type": "unlimited",
                "plan": plan_key,
                "duration_hours": plan['duration_hours'],
                "duration_text": plan['duration_text'],
                "price": plan['price'],
                "timestamp": datetime.now().isoformat(),
                "label": plan['label']
            }
            
            send_qr_with_payment_info(user_id, plan, "unlimited", session_id, context, query.message)
            
            user_identifier = get_user_identifier(user_id, update.effective_user.username)
            admin_msg = f"🌟 *Unlimited Plan Request*\n━━━━━━━━━━━━━━━━━━━━━\n🆔 ID: `{session_id}`\n👤 User: {user_identifier}\n📦 Plan: {plan['label']}\n💵 Amount: ₹{plan['price']}"
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{session_id}"),
                 InlineKeyboardButton("❌ Decline", callback_data=f"decline_{session_id}")]
            ])
            context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode='Markdown', reply_markup=admin_keyboard)
            
            context.user_data['payment_session'] = session_id
        return
    
    # Unlimited duration selection for admin activation
    if action.startswith("unlimited_duration_"):
        if is_admin(user_id):
            duration_key = action.replace("unlimited_duration_", "")
            if duration_key in UNLIMITED_PLANS:
                context.user_data['temp_unlimited_duration'] = duration_key
                query.message.reply_text(f"✅ Selected: {UNLIMITED_PLANS[duration_key]['label']}\n\nNow send the username or user ID to activate:\n\nFormat: `@username` or `123456789`\nType `cancel` to abort.", parse_mode='Markdown')
                context.user_data['admin_state'] = 'activate_unlimited_confirm'
                query.message.delete()
        return
    
    # Navigation
    if action == "show_credit_plans":
        if mode == 'free':
            query.message.edit_text("🎉 *FREE MODE ACTIVE*\n\nNo credits needed! All features are free.", parse_mode='Markdown')
            return
        query.message.edit_text("💳 *Credit Plans:*", parse_mode='Markdown', reply_markup=get_credit_plans_keyboard())
        return
    
    if action == "show_unlimited_plans":
        if mode == 'free':
            query.message.edit_text("🎉 *FREE MODE ACTIVE*\n\nNo unlimited plans needed! All features are free.", parse_mode='Markdown')
            return
        query.message.edit_text("🌟 *Unlimited Plans:*", parse_mode='Markdown', reply_markup=get_unlimited_plans_keyboard())
        return
    
    if action == "back_to_purchase":
        query.message.edit_text("Select plan type:", reply_markup=get_purchase_keyboard())
        return
    
    if action == "admin_close":
        query.message.delete()
        return
    
    # Admin navigation
    if is_admin(user_id):
        if action == "adm_settings":
            query.message.edit_text("⚙️ *Settings Menu*\n\nCurrent Status:", parse_mode='Markdown', reply_markup=get_settings_keyboard())
            return
        
        if action == "adm_back":
            query.message.edit_text("🔐 Admin Panel:", reply_markup=get_admin_keyboard())
            return
        
        if action == "adm_ban_unban":
            query.message.edit_text("🚫 *Ban/Unban User*\n\nSelect option:", parse_mode='Markdown', reply_markup=get_ban_unban_keyboard())
            return
        
        if action == "adm_toggle_mode":
            current = get_mode()
            new_mode = 'free' if current == 'paid' else 'paid'
            
            success = set_mode(new_mode)
            
            if success:
                mode_emoji = "🔓" if new_mode == 'free' else "🔒"
                mode_text = "FREE" if new_mode == 'free' else "PAID"
                
                if new_mode == 'free':
                    notification = f"🔄 *Mode Changed to FREE Mode* {mode_emoji}\n\n✅ All features are now FREE for all users!\n❌ No credits or unlimited plans required.\n💰 All payment options are disabled."
                else:
                    notification = f"🔄 *Mode Changed to PAID Mode* {mode_emoji}\n\n✅ Credit and Unlimited plans are now ACTIVE!\n💰 Users can buy credits and unlimited plans.\n📊 Normal credit deduction system is running."
                
                query.message.reply_text(notification, parse_mode='Markdown')
                
                broadcast_msg = f"📢 *System Update*\n\n{notification}"
                try:
                    broadcast_to_all_users(broadcast_msg, context)
                except:
                    pass
                
                # Update settings menu
                query.message.reply_text("⚙️ *Settings Menu (Updated)*\n\nCurrent Status:", parse_mode='Markdown', reply_markup=get_settings_keyboard())
            else:
                query.message.reply_text("❌ Failed to change mode. Please try again.")
            return
        
        if action == "adm_toggle_maint":
            current = check_maintenance()
            new_state = not current
            supabase.table("settings").update({"value": str(new_state).lower()}).eq("key", "maintenance_mode").execute()
            
            maint_status = "ON" if new_state else "OFF"
            maint_emoji = "🔴" if new_state else "🟢"
            query.message.reply_text(f"✅ Maintenance mode changed to: {new_state}\nStatus: {maint_emoji} {maint_status}")
            
            # Update settings menu
            query.message.reply_text("⚙️ *Settings Menu (Updated)*\n\nCurrent Status:", parse_mode='Markdown', reply_markup=get_settings_keyboard())
            return
        
        if action == "adm_search_user":
            context.user_data['admin_state'] = 'search_user'
            query.message.reply_text("Send user ID or @username:")
            return
        
        if action == "adm_modify_credits":
            context.user_data['admin_state'] = 'modify_credits'
            query.message.reply_text("Format: `USER_ID AMOUNT`\nExample: `123456789 100`\nUse negative to deduct: `123456789 -50`", parse_mode='Markdown')
            return
        
        if action == "adm_activate_unlimited":
            query.message.reply_text("🌟 *Select Unlimited Plan Duration:*", parse_mode='Markdown', reply_markup=get_unlimited_duration_keyboard())
            return
        
        if action == "adm_deactivate_unlimited":
            context.user_data['admin_state'] = 'deactivate_unlimited'
            query.message.reply_text("Send username or user ID to DEACTIVATE unlimited plan:\n\nFormat: `@username` or `123456789`", parse_mode='Markdown')
            return
        
        if action == "adm_ban_user":
            context.user_data['admin_state'] = 'ban_user'
            query.message.reply_text("🚫 *Ban User*\n\nSend username or user ID to ban:\n\nFormat: `@username` or `123456789`", parse_mode='Markdown')
            return
        
        if action == "adm_unban_user":
            context.user_data['admin_state'] = 'unban_user'
            query.message.reply_text("✅ *Unban User*\n\nSend username or user ID to unban:\n\nFormat: `@username` or `123456789`", parse_mode='Markdown')
            return
        
        if action == "adm_giveaway_all":
            context.user_data['admin_state'] = 'giveaway_all'
            query.message.reply_text("🎁 Send credit amount for ALL users:\nExample: `50`\n(Only non-banned users will receive)", parse_mode='Markdown')
            return
        
        if action == "adm_broadcast":
            context.user_data['admin_state'] = 'broadcast'
            query.message.reply_text("📢 Send message to broadcast to ALL users:\n(Only non-banned users will receive)", parse_mode='Markdown')
            return

def handle_receipt_upload(update: Update, context: CallbackContext):
    session_id = context.user_data.get('payment_session')
    
    if not session_id or session_id not in pending_sessions:
        update.message.reply_text("❌ No active payment session. Start new purchase.")
        return
    
    session = pending_sessions[session_id]
    photo = update.message.photo[-1].file_id
    user = update.effective_user
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_identifier = get_user_identifier(user.id, user.username)
    
    admin_msg = f"""
📸 *Payment Receipt Received*
━━━━━━━━━━━━━━━━━━━━━
🆔 Session: `{session_id}`
👤 User: {user_identifier}
⏰ Time: {timestamp}
📦 Plan: {session.get('label', 'N/A')}
💰 Amount: ₹{session.get('price', 0)}
━━━━━━━━━━━━━━━━━━━━━
    """
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{session_id}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"decline_{session_id}")]
    ])
    
    context.bot.send_photo(ADMIN_USER_ID, photo, caption=admin_msg, parse_mode='Markdown', reply_markup=admin_keyboard)
    update.message.reply_text("✅ Receipt sent! Admin will verify soon.")
    context.user_data['payment_session'] = None

def process_payment_approval(update: Update, context: CallbackContext, session_id: str, approved: bool):
    query = update.callback_query
    
    if session_id not in pending_sessions:
        query.message.reply_text("⚠️ Session not found. The user may have already been processed.")
        return
    
    session = pending_sessions[session_id]
    target_user = session['user_id']
    
    if approved:
        if session['type'] == 'credit':
            credits_to_add = session['credits']
            if modify_credits(target_user, credits_to_add):
                try:
                    context.bot.send_message(
                        target_user,
                        f"✅ *Payment Approved!*\n\n🎉 {credits_to_add} credits added to your account!\n💰 New balance: {sync_account(target_user).get('credits', 0)} credits\n\nUse 📞 Number Lookup to start."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
                
                query.message.edit_text(f"✅ Approved! {credits_to_add} credits added to user {target_user}")
            else:
                query.message.edit_text(f"❌ Database error. Failed to add credits to user {target_user}")
                pending_sessions.pop(session_id, None)
                return
        else:
            duration_hours = session['duration_hours']
            duration_text = session.get('duration_text', f"{duration_hours} hours")
            
            days = duration_hours // 24 if duration_hours >= 24 else 0
            if days > 0:
                display_text = f"{days} days" if days > 1 else f"{days} day"
            else:
                display_text = duration_text
            
            success = activate_unlimited_plan(target_user, duration_hours)
            
            if success:
                expiry_date = datetime.now() + timedelta(hours=duration_hours)
                expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"Unlimited plan activated for user {target_user}: {duration_hours} hours, expires at {expiry_str}")
                
                try:
                    context.bot.send_message(
                        target_user,
                        f"✅ *Unlimited Plan Activated!* 🌟\n\n"
                        f"📦 Plan: {display_text} Unlimited\n"
                        f"⏰ Activated: Now\n"
                        f"📅 Expires: {expiry_str}\n\n"
                        f"🎯 You can now use 📞 Number Lookup without any credit deductions!\n\n"
                        f"Enjoy unlimited access! 🚀"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
                
                query.message.edit_text(f"✅ Unlimited plan activated for user {target_user} for {display_text}!\n⏰ Expires: {expiry_str}")
            else:
                logger.error(f"Failed to activate unlimited plan for user {target_user}")
                query.message.edit_text(f"❌ Database error. Failed to activate unlimited plan for user {target_user}")
                pending_sessions.pop(session_id, None)
                return
    else:
        try:
            context.bot.send_message(target_user, "❌ Payment declined. Please contact support for assistance.")
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        query.message.edit_text(f"❌ Payment declined for user {target_user}")
    
    pending_sessions.pop(session_id, None)

def process_admin_input(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    state = context.user_data.get('admin_state')
    
    if text.lower() == 'cancel':
        context.user_data['admin_state'] = None
        context.user_data.pop('temp_unlimited_duration', None)
        update.message.reply_text("❌ Cancelled.")
        return
    
    if state == 'search_user':
        context.user_data['admin_state'] = None
        try:
            if text.startswith('@'):
                username = text[1:]
                res = supabase.table("users").select("*").eq("username", username).execute()
            else:
                user_id = int(text)
                res = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
            
            if res.data:
                user = res.data[0]
                unlimited_active, expiry, remaining = is_unlimited_active(user['telegram_id'])
                banned_status = "✅ BANNED" if user.get('is_banned', False) else "❌ Not Banned"
                user_identifier = get_user_identifier(user['telegram_id'], user.get('username'))
                
                if unlimited_active and expiry:
                    unlimited_status = f"Active (expires {expiry.strftime('%Y-%m-%d %H:%M')}, {remaining}h left)"
                else:
                    unlimited_status = "Inactive"
                
                msg = f"""
👤 *USER DETAILS*
━━━━━━━━━━━━━━━━━━━━━
👤 User: {user_identifier}
💰 Credits: {user.get('credits', 0)}
📊 Lookups: {user.get('total_lookups_done', 0)}
🌟 Unlimited: {unlimited_status}
🚫 Banned: {banned_status}
                """
                update.message.reply_text(msg, parse_mode='Markdown')
            else:
                update.message.reply_text("❌ User not found.")
        except Exception as e:
            update.message.reply_text(f"❌ Error: {e}")
    
    elif state == 'modify_credits':
        context.user_data['admin_state'] = None
        try:
            parts = text.split()
            user_id = int(parts[0])
            amount = int(parts[1])
            if modify_credits(user_id, amount):
                update.message.reply_text(f"✅ {'Added' if amount > 0 else 'Deducted'} {abs(amount)} credits for user {user_id}")
                try:
                    if amount > 0:
                        context.bot.send_message(user_id, f"🎁 {amount} credits added to your account!")
                    else:
                        context.bot.send_message(user_id, f"📝 {abs(amount)} credits deducted from your account.")
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed.")
        except:
            update.message.reply_text("❌ Use: `USER_ID AMOUNT`")
    
    elif state == 'activate_unlimited_confirm':
        duration_key = context.user_data.get('temp_unlimited_duration')
        if not duration_key or duration_key not in UNLIMITED_PLANS:
            context.user_data['admin_state'] = None
            update.message.reply_text("❌ Session expired. Please try again.")
            return
        
        try:
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            hours = UNLIMITED_PLANS[duration_key]['duration_hours']
            days = hours // 24 if hours >= 24 else 0
            duration_text = f"{days} days" if days > 0 else f"{hours} hours"
            
            if activate_unlimited_plan(target_id, hours):
                expiry_date = datetime.now() + timedelta(hours=hours)
                expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M')
                
                update.message.reply_text(
                    f"✅ *Unlimited Plan Activated*\n━━━━━━━━━━━━━━━━━━━━━\n👤 User ID: `{target_id}`\n📅 Duration: {duration_text}\n⏰ Expires: {expiry_str}\n━━━━━━━━━━━━━━━━━━━━━",
                    parse_mode='Markdown'
                )
                try:
                    context.bot.send_message(
                        target_id,
                        f"🌟 *Unlimited Plan Activated!* 🌟\n\n"
                        f"📅 Duration: {duration_text}\n"
                        f"⏰ Expires: {expiry_str}\n\n"
                        f"Use 📞 Number Lookup anytime without credit deduction!"
                    )
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed to activate.")
            
            context.user_data['admin_state'] = None
            context.user_data.pop('temp_unlimited_duration', None)
        except Exception as e:
            update.message.reply_text(f"❌ Invalid input: {e}")
    
    elif state == 'deactivate_unlimited':
        context.user_data['admin_state'] = None
        try:
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            if deactivate_unlimited_plan(target_id):
                update.message.reply_text(f"✅ Unlimited plan deactivated for user {target_id}")
                try:
                    context.bot.send_message(target_id, "📋 Your unlimited plan has been deactivated.")
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed or user had no active plan.")
        except:
            update.message.reply_text("❌ Invalid input.")
    
    elif state == 'ban_user':
        context.user_data['admin_state'] = None
        try:
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            if ban_user(target_id):
                update.message.reply_text(f"🚫 User {target_id} has been BANNED!")
                try:
                    context.bot.send_message(target_id, "🚫 You have been banned from using this bot. Contact admin for support.")
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed to ban user.")
        except:
            update.message.reply_text("❌ Invalid input.")
    
    elif state == 'unban_user':
        context.user_data['admin_state'] = None
        try:
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            if unban_user(target_id):
                update.message.reply_text(f"✅ User {target_id} has been UNBANNED!")
                try:
                    context.bot.send_message(target_id, "✅ You have been unbanned! You can now use the bot again.")
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed to unban user.")
        except:
            update.message.reply_text("❌ Invalid input.")
    
    elif state == 'giveaway_all':
        context.user_data['admin_state'] = None
        try:
            amount = int(text)
            msg = update.message.reply_text(f"⏳ Giving {amount} credits to all non-banned users...")
            success, fail, total = giveaway_to_all_users(amount)
            msg.edit_text(f"✅ Giveaway complete!\n━━━━━━━━━━━━━━━━━━━━━\n👥 Total: {total}\n✅ Success: {success}\n❌ Failed: {fail}\n🎁 Total given: {amount * success}")
        except:
            update.message.reply_text("❌ Send valid number.")
    
    elif state == 'broadcast':
        context.user_data['admin_state'] = None
        msg = update.message.reply_text(f"⏳ Broadcasting to all non-banned users...")
        success, fail, total = broadcast_to_all_users(text, context)
        msg.edit_text(f"✅ Broadcast complete!\n━━━━━━━━━━━━━━━━━━━━━\n👥 Total: {total}\n✅ Sent: {success}\n❌ Failed: {fail}")

def main():
    server_thread = threading.Thread(target=start_health_server, daemon=True)
    server_thread.start()
    
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    except:
        pass
    
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.photo, handle_receipt_upload))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    
    print("✅ Bot Started!")
    print(f"✅ Admin ID: {ADMIN_USER_ID}")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()