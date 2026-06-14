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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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
ADMIN_USERNAME = "@Venom_Intelligence"

# Initialize Database Pipeline Connection 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cost Analysis Metrics
CREDIT_COST_PER_LOOKUP = 10
PLAN_METRICS = {
    "plan_50": {"price": 50, "credits": 50, "label": "₹50 for 50 Credits"},
    "plan_100": {"price": 100, "credits": 120, "label": "₹100 for 120 Credits"},
    "plan_200": {"price": 200, "credits": 260, "label": "₹200 for 260 Credits"},
    "plan_500": {"price": 500, "credits": 700, "label": "₹500 for 700 Credits"},
    "plan_1000": {"price": 1000, "credits": 1500, "label": "₹1000 for 1500 Credits"},
}

# Unlimited plan duration options (in days)
UNLIMITED_DURATIONS = {
    "1day": {"days": 1, "label": "🌟 1 Day Unlimited Plan"},
    "3days": {"days": 3, "label": "🌟 3 Days Unlimited Plan"},
    "7days": {"days": 7, "label": "🌟 1 Week Unlimited Plan"},
    "30days": {"days": 30, "label": "🌟 1 Month Unlimited Plan"},
    "90days": {"days": 90, "label": "🌟 3 Months Unlimited Plan"},
    "365days": {"days": 365, "label": "🌟 1 Year Unlimited Plan"},
}

pending_sessions: Dict[str, Dict] = {}

# ============= RENDER PLATFORM PORT BINDINGS =============
def start_health_server():
    class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot Engine Infrastructure Active.")

    port = int(os.environ.get("PORT", 8080))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), HealthCheckHandler) as httpd:
            logger.info(f"Port system active on container layer: {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Failed to launch live verification server: {e}")

# ============= CORE DATA SANITIZATION METHODS =============
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def escape_username(username: Optional[str]) -> str:
    if not username:
        return "N/A"
    return username.replace("_", "\\_")

def escape_markdown_v1(text: str) -> str:
    return text.replace("_", "\\_").replace("*", "\\*")

def force_block_links_and_ads(text: str) -> str:
    lines = text.split('\n')
    filtered_lines = []
    ads_blacklist = [
        'branding', 'developer', 'gaurav', 'tracexdata', 
        'api_buy_link', 'website_link', 'join our channel', 
        'must join', 'a_toolsx', 'view channel', 'license_info'
    ]
    for line in lines:
        if not any(bad_word in line.lower() for bad_word in ads_blacklist):
            filtered_lines.append(line)
    
    cleaned_text = '\n'.join(filtered_lines)
    cleaned_text = re.sub(r'https?://\S+', '', cleaned_text) 
    cleaned_text = re.sub(r'(t\.me|telegram\.me|telegram\.dog)/\S+', '', cleaned_text) 
    cleaned_text = re.sub(r'@[a-zA-Z0-9_]{3,}', '', cleaned_text) 
    
    return cleaned_text

def check_maintenance() -> bool:
    try:
        response = supabase.table("settings").select("value").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            val = response.data[0].get("value")
            return val.lower() == 'true' if isinstance(val, str) else bool(val)
        return False
    except:
        return False

def is_unlimited_active(user_id: int) -> tuple:
    """Check if user has active unlimited plan, returns (is_active, expiry_date, remaining_days)"""
    try:
        response = supabase.table("users").select("unlimited_expiry").eq("telegram_id", user_id).execute()
        if response.data and len(response.data) > 0:
            expiry_str = response.data[0].get("unlimited_expiry")
            if expiry_str:
                expiry_date = datetime.fromisoformat(expiry_str)
                if expiry_date > datetime.now():
                    remaining = (expiry_date - datetime.now()).days
                    return True, expiry_date, remaining
        return False, None, 0
    except Exception as e:
        logger.error(f"Error checking unlimited status: {e}")
        return False, None, 0

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
                "credits": 0,
                "total_lookups_done": 0,
                "unlimited_expiry": None
            }
            supabase.table("users").insert(new_profile).execute()
            return new_profile
    except Exception as e:
        logger.error(f"Critical error on user sync operation: {e}")
        return {"telegram_id": user_id, "username": username, "credits": 0, "total_lookups_done": 0, "unlimited_expiry": None}

def modify_credits(user_id: int, volume: int) -> bool:
    if is_admin(user_id):
        return True
        
    try:
        profile = sync_account(user_id)
        target_bal = max(0, profile.get("credits", 0) + volume)
        res = supabase.table("users").update({"credits": target_bal}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Database error balancing data index columns: {e}")
        return False

def activate_unlimited_plan(user_id: int, duration_days: int) -> bool:
    """Activate unlimited plan for a user for specified number of days"""
    try:
        expiry_date = datetime.now() + timedelta(days=duration_days)
        res = supabase.table("users").update({"unlimited_expiry": expiry_date.isoformat()}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Failed to activate unlimited plan: {e}")
        return False

def deactivate_unlimited_plan(user_id: int) -> bool:
    """Deactivate unlimited plan for a user"""
    try:
        res = supabase.table("users").update({"unlimited_expiry": None}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Failed to deactivate unlimited plan: {e}")
        return False

def get_unlimited_plan_keyboard():
    """Create inline keyboard for unlimited plan duration selection"""
    buttons = []
    for key, data in UNLIMITED_DURATIONS.items():
        buttons.append([InlineKeyboardButton(text=data['label'], callback_data=f"unlimited_{key}")])
    buttons.append([InlineKeyboardButton(text="◀️ Cancel", callback_data="admin_close")])
    return InlineKeyboardMarkup(buttons)

# ============= DESKTOP INTERACTIVE MARKUPS =============
def get_main_keyboard():
    menu = [
        ["📞 Number Lookup", "💳 Purchase Credits"],
        ["📊 My Plan", "⚙️ Admin Panel"]
    ]
    return ReplyKeyboardMarkup(menu, resize_keyboard=True)

def get_billing_keyboard():
    buttons = []
    for key, data in PLAN_METRICS.items():
        buttons.append([InlineKeyboardButton(text=f"💳 {data['label']}", callback_data=f"buy_{key}")])
    buttons.append([InlineKeyboardButton(text="◀️ Close Menu", callback_data="admin_close")])
    return InlineKeyboardMarkup(buttons)

def get_admin_inline_keyboard():
    layout = [
        [InlineKeyboardButton("🔧 Toggle Global Maintenance", callback_data="adm_toggle_maint")],
        [InlineKeyboardButton("👤 Search User Profile DB", callback_data="adm_search_user")],
        [InlineKeyboardButton("💳 Add/Remove Credits Manually", callback_data="adm_modify_credits")],
        [InlineKeyboardButton("🌟 Activate Unlimited Plan", callback_data="adm_unlimited_plan")],
        [InlineKeyboardButton("❌ Deactivate Unlimited Plan", callback_data="adm_deactivate_unlimited")],
        [InlineKeyboardButton("🚫 Dismiss Panel", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(layout)

# ============= CONSOLE LOGIC ROUTER PIPELINES =============
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    sync_account(user.id, user.username)
    context.user_data.clear() 
    
    welcome = f"""
⚡ *Welcome to Premium Lookup Console!* ⚡

✨ *Available Dynamic Metrics:*
• 📞 *Number Lookup:* Pull secure registered database information.
• 💳 *Purchase Credits:* Safely top up your currency allocation.
• 📊 *My Plan:* Review remaining credit points instantly.

🎯 *System Cost:* `1 Lookup = {CREDIT_COST_PER_LOOKUP} Credits`
    """
    update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=get_main_keyboard(), disable_web_page_preview=True)

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    core_buttons = ["Number Lookup", "📞", "Purchase Credits", "💳", "My Plan", "📊", "Admin Panel", "⚙️"]
    if any(btn in text for btn in core_buttons):
        context.user_data['payment_state_token'] = None

    if is_admin(user_id) and context.user_data.get('admin_action_state'):
        process_admin_text_inputs(update, context)
        return

    if check_maintenance() and not is_admin(user_id):
        update.message.reply_text("🔧 *System Under Maintenance:* Core frameworks are updating. Check back shortly.", parse_mode='Markdown')
        return

    if context.user_data.get('awaiting_lookup_target'):
        if text.isdigit() and len(text) == 10:
            context.user_data['awaiting_lookup_target'] = False
            execute_number_lookup(update, context, text)
        else:
            update.message.reply_text("❌ *Invalid Format:* Enter a valid 10-digit numerical value.", parse_mode='Markdown')
        return

    if "Number Lookup" in text or "📞" in text:
        profile = sync_account(user_id)
        unlimited_active, expiry, remaining = is_unlimited_active(user_id)
        
        if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
            update.message.reply_text(f"⚠️ *Insufficient Balance:* You require at least `{CREDIT_COST_PER_LOOKUP}` credits.\n🪙 Current Balance: `{profile.get('credits', 0)}`\n💡 *Tip:* Purchase credits or contact admin for unlimited plan.", parse_mode='Markdown')
            return
        context.user_data['awaiting_lookup_target'] = True
        update.message.reply_text("📱 *Please enter the 10-digit mobile number you want to look up:*", parse_mode='Markdown')

    elif "Purchase Credits" in text or "💳" in text:
        update.message.reply_text("💳 *Select a currency package from the menu options below:*", parse_mode='Markdown', reply_markup=get_billing_keyboard())

    elif "My Plan" in text or "📊" in text:
        profile = sync_account(user_id, update.effective_user.username)
        unlimited_active, expiry, remaining = is_unlimited_active(user_id)
        
        if unlimited_active:
            expiry_str = expiry.strftime('%Y-%m-%d')
            plan_status = f"🌟 *Unlimited Plan (Active)* 🌟\n⏰ Expires: `{expiry_str}`\n📅 Remaining: `{remaining} days`\n♾️ No credit limits!"
            credits_display = "♾️ Unlimited (Until Plan Expires)"
        elif is_admin(user_id):
            plan_status = "👑 *Administrator Account*"
            credits_display = "♾️ Unlimited (Root Administrator)"
        else:
            plan_status = "📋 *Standard Plan*"
            credits_display = f"`{profile['credits']}`"
            
        status_msg = f"""
⭐ *Account Balance Metrics* ⭐
━━━━━━━━━━━━━━━━━━━━━
👤 *User ID:* `{profile['telegram_id']}`
🪙 *Available Credits:* {credits_display}
📊 *Total Lookups Executed:* `{profile['total_lookups_done']}`
{plan_status}
━━━━━━━━━━━━━━━━━━━━━
💡 *Note:* Each query consumes exactly `{CREDIT_COST_PER_LOOKUP}` credits.
        """
        update.message.reply_text(status_msg, parse_mode='Markdown', disable_web_page_preview=True)

    elif "Admin Panel" in text or "⚙️" in text:
        if is_admin(user_id):
            update.message.reply_text("🔐 *Administrative Panel Access Secured*", parse_mode='Markdown', reply_markup=get_admin_inline_keyboard())
        else:
            update.message.reply_text("❌ *Access Denied:* You are not an admin!", parse_mode='Markdown')
            
    elif context.user_data.get('payment_state_token'):
        update.message.reply_text("⚠️ *Awaiting Payment Verification:* Please upload the transaction screenshot image directly here to proceed, or choose another action from the menu.", parse_mode='Markdown')

def send_safely_in_chunks(update: Update, text: str):
    clean_text = force_block_links_and_ads(text)
    if len(clean_text) <= 4000:
        update.message.reply_text(clean_text, parse_mode='Markdown', disable_web_page_preview=True)
        return

    lines = clean_text.split('\n')
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            update.message.reply_text(chunk, parse_mode='Markdown', disable_web_page_preview=True)
            chunk = line + '\n'
        else:
            chunk += line + '\n'
    if chunk.strip():
        update.message.reply_text(chunk, parse_mode='Markdown', disable_web_page_preview=True)

def execute_number_lookup(update: Update, context: CallbackContext, query_number: str):
    user_id = update.effective_user.id
    profile = sync_account(user_id)
    unlimited_active, expiry, remaining = is_unlimited_active(user_id)
    
    if not is_admin(user_id) and not unlimited_active and profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
        update.message.reply_text("⚠️ *Transaction Denied:* Insufficient runtime balances.", parse_mode='Markdown')
        return
        
    loader = update.message.reply_text("⚡ *Querying Central Data Registry...*", parse_mode='Markdown')
    
    try:
        response = requests.get(LOOKUP_API.format(query_number), timeout=15)
        if response.status_code == 200:
            payload = response.json()
            
            # Check if no data found
            if payload.get('status') == 'failed' or payload.get('results_found', 0) == 0:
                update.message.reply_text(f"❌ *Query Response:* No data registered under number: *{query_number}*", parse_mode='Markdown')
                return
            
            if payload.get('status') == 'success' and payload.get('success'):
                records = payload.get('results', {})
                total_found = payload.get('results_found', 0)
                
                if total_found > 0:
                    # Deduct credits only if not admin and not unlimited user
                    if not is_admin(user_id) and not unlimited_active:
                        modify_credits(user_id, -CREDIT_COST_PER_LOOKUP)
                    
                    supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
                    
                    if unlimited_active:
                        cost_msg = f"0 Credits (Unlimited Plan - {remaining} days left)"
                    elif is_admin(user_id):
                        cost_msg = "0 Credits (Admin Session)"
                    else:
                        cost_msg = f"{CREDIT_COST_PER_LOOKUP} Credits Deducted"
                    
                    response_payload = f"📱 *Lookup Records for:* `{query_number}`\n━━━━━━━━━━━━━━━━━━━━━\n📊 *Total Found:* {total_found}\n💸 *Cost:* {cost_msg}\n━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    for step in range(1, total_found + 1):
                        r_key = f"Result {step}"
                        if r_key in records:
                            item = records[r_key]
                            name = escape_markdown_v1(str(item.get('name', 'N/A')))
                            f_name = escape_markdown_v1(str(item.get('father_name', 'N/A')))
                            addr = escape_markdown_v1(str(item.get('address', 'N/A')))
                            
                            response_payload += f"*Record Sample #{step}:*\n"
                            response_payload += f"👤 *Name:* {name}\n"
                            response_payload += f"👨 *Father:* {f_name}\n"
                            response_payload += f"📱 *Mobile:* {item.get('mobile', 'N/A')}\n"
                            if item.get('alt_mobile') and item.get('alt_mobile') != 'n/a':
                                response_payload += f"📞 *Alt Contact:* {item.get('alt_mobile')}\n"
                            if item.get('aadhar_number') and item.get('aadhar_number') != 'n/a':
                                response_payload += f"🆔 *Aadhar Identity:* `{item.get('aadhar_number')}`\n"
                            response_payload += f"📡 *Carrier Details:* {item.get('operator', 'N/A')} ({item.get('state_circle', 'N/A')})\n"
                            response_payload += f"🏠 *Address Metric:* {addr}\n─────────────────────\n"
                    
                    send_safely_in_chunks(update, response_payload)
                else:
                    update.message.reply_text(f"❌ *Query Response:* No data registered under number: *{query_number}*", parse_mode='Markdown')
            else:
                update.message.reply_text(f"❌ *Query Response:* No data registered under number: *{query_number}*", parse_mode='Markdown')
        else:
            update.message.reply_text("❌ *API Connection Error:* Remote network connection failure.", parse_mode='Markdown')
    except Exception as error:
        logger.error(f"Lookup runtime system crash stack trace: {error}")
        update.message.reply_text("❌ *Execution Exception:* Internal core system mismatch error.", parse_mode='Markdown')
    finally:
        try: loader.delete()
        except: pass

def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    action = query.data
    user_id = update.effective_user.id
    query.answer()
    
    if action.startswith("buy_"):
        plan_id = action.replace("buy_", "")
        if plan_id in PLAN_METRICS:
            plan = PLAN_METRICS[plan_id]
            user = update.effective_user
            escaped_un = escape_username(user.username)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
            
            session_id = f"TXN-{user_id}-{int(datetime.now().timestamp())}"
            pending_sessions[session_id] = {
                "user_id": user_id,
                "username": user.username,
                "plan_id": plan_id,
                "credits": plan["credits"],
                "price": plan["price"],
                "timestamp": timestamp
            }
            
            admin_alert = f"🔔 *Payment Session Initiated*\n━━━━━━━━━━━━━━━━━━━━━\n🆔 *Transaction Reference:* `{session_id}`\n👤 *Client User:* @{escaped_un}\n🆔 *Client ID:* `{user_id}`\n🛒 *Selection:* {plan['label']}\n⏳ *Initiated At:* `{timestamp}`"
            
            admin_control_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Force Approve", callback_data=f"approve_{session_id}")],
                [InlineKeyboardButton("❌ Force Decline", callback_data=f"decline_{session_id}")]
            ])
            
            context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_alert, parse_mode='Markdown', reply_markup=admin_control_markup, disable_web_page_preview=True)
            
            context.user_data['payment_state_token'] = session_id
            invoice_text = f"💳 *Invoice Reference:* `{session_id}`\n━━━━━━━━━━━━━━━━━━━━━\n📦 *Selected Package:* {plan['label']}\n💵 *Total Cost Due:* ₹{plan['price']}\n\n👉 *Instructions:* Scan the QR code to finalize payment. Once done, upload the screenshot receipt image directly into this chat layout."
            
            qr_path = os.path.join(os.getcwd(), "qr.png")
            if os.path.exists(qr_path):
                try:
                    with open(qr_path, 'rb') as image:
                        query.message.reply_photo(photo=image, caption=invoice_text, parse_mode='Markdown')
                except Exception as img_err:
                    logger.error(f"Failed handling raw QR file pipeline: {img_err}")
                    query.message.reply_text(f"⚠️ *QR Engine Delayed:*\n\n{invoice_text}\n\n*Admin Contact:* {ADMIN_USERNAME}", parse_mode='Markdown', disable_web_page_preview=True)
            else:
                query.message.reply_text(f"⚠️ *QR Code Not Setup on Host:*\n\n{invoice_text}\n\n*Admin Contact:* {ADMIN_USERNAME}", parse_mode='Markdown', disable_web_page_preview=True)
    
    elif action.startswith("unlimited_"):
        # Handle unlimited plan activation from inline keyboard
        if is_admin(user_id):
            plan_key = action.replace("unlimited_", "")
            if plan_key in UNLIMITED_DURATIONS:
                plan = UNLIMITED_DURATIONS[plan_key]
                context.user_data['temp_unlimited_duration'] = plan_key
                query.message.reply_text(f"📝 *Selected Plan:* {plan['label']}\n\nNow send the username or user ID to activate this plan.\n\n*Format:*\n• `@username`\n• `123456789`\n\nType `cancel` to abort.", parse_mode='Markdown')
                context.user_data['admin_action_state'] = 'activate_unlimited'
        else:
            query.message.reply_text("❌ *Access Denied:* Only admins can activate unlimited plans!", parse_mode='Markdown')
                
    elif action.startswith("approve_"):
        session_id = action.replace("approve_", "")
        process_admin_payment_verdict(update, context, session_id, verified=True)
        
    elif action.startswith("decline_"):
        session_id = action.replace("decline_", "")
        process_admin_payment_verdict(update, context, session_id, verified=False)
        
    elif action == "admin_close":
        query.message.delete()
        
    elif is_admin(user_id):
        if action == "adm_toggle_maint":
            current_state = check_maintenance()
            new_state = not current_state
            supabase.table("settings").upsert({"key": "maintenance_mode", "value": str(new_state).lower()}).execute()
            query.message.reply_text(f"🔧 *System Status Updated:* Maintenance state set to **{new_state}**", parse_mode='Markdown')
        elif action == "adm_search_user":
            context.user_data['admin_action_state'] = 'search_user'
            query.message.reply_text("👤 Send the exact Username string or Telegram User ID to query user row entries:")
        elif action == "adm_modify_credits":
            context.user_data['admin_action_state'] = 'modify_credits'
            query.message.reply_text("📝 *Format:* `[TelegramUserID] [Amount]`\n\n*Example:* `7850023357 500`", parse_mode='Markdown')
        elif action == "adm_unlimited_plan":
            # Show unlimited plan duration options
            query.message.reply_text("🌟 *Select Unlimited Plan Duration:*", parse_mode='Markdown', reply_markup=get_unlimited_plan_keyboard())
        elif action == "adm_deactivate_unlimited":
            context.user_data['admin_action_state'] = 'deactivate_unlimited'
            query.message.reply_text("❌ *Deactivate Unlimited Plan*\n\nSend the username or user ID to deactivate their unlimited plan.\n\n*Format:*\n• `@username`\n• `123456789`\n\nType `cancel` to abort.", parse_mode='Markdown')

def handle_receipt_upload(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session_id = context.user_data.get('payment_state_token')
    
    if not session_id or session_id not in pending_sessions:
        update.message.reply_text("⚠️ *No Active Session:* No waiting payment operations linked with your ID profile right now.", parse_mode='Markdown')
        return
        
    session = pending_sessions[session_id]
    photo_file = update.message.photo[-1].file_id
    escaped_un = escape_username(update.effective_user.username)
    
    receipt_heading = f"📩 *Receipt Document Submitted*\n━━━━━━━━━━━━━━━━━━━━━\n🆔 *Ref:* `{session_id}`\n👤 *Sender:* @{escaped_un}\n🆔 *ID:* `{user_id}`\n🛒 *Plan Selected:* {PLAN_METRICS[session['plan_id']]['label']}\n💵 *Value Amount:* ₹{session['price']}"
    
    admin_verification_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept / Add Credits", callback_data=f"approve_{session_id}")],
        [InlineKeyboardButton("❌ Reject / Cancel", callback_data=f"decline_{session_id}")]
    ])
    
    context.bot.send_photo(chat_id=ADMIN_USER_ID, photo=photo_file, caption=receipt_heading, parse_mode='Markdown', reply_markup=admin_verification_markup)
    context.user_data['payment_state_token'] = None 
    update.message.reply_text("✅ *Receipt Received:* Sent to administration for validation.", parse_mode='Markdown')

def process_admin_payment_verdict(update: Update, context: CallbackContext, session_id: str, verified: bool):
    query = update.callback_query
    if session_id not in pending_sessions:
        if query:
            query.message.reply_text("❌ *Error Reference:* Transaction reference session expired or invalid state.", parse_mode='Markdown')
        return
        
    session = pending_sessions[session_id]
    target_client = session['user_id']
    credit_payload = session['credits']
    
    if verified:
        if modify_credits(target_client, credit_payload):
            try:
                context.bot.send_message(chat_id=target_client, text=f"🎉 *Payment Verified:* Your transaction has been approved! `{credit_payload}` credits have been added.", parse_mode='Markdown')
            except: pass
            if query:
                try: query.edit_message_caption(caption=f"{query.message.caption_markdown}\n\n✅ *Status Update: Approved*", parse_mode='Markdown')
                except: query.message.reply_text("✅ *Session Status:* Force Approved.")
        else:
            if query: query.message.reply_text("❌ *Database Fault:* Unable to save updated data indexes.")
    else:
        try:
            context.bot.send_message(chat_id=target_client, text="❌ *Payment Rejected:* Your receipt verification request was declined.", parse_mode='Markdown')
        except: pass
        if query:
            try: query.edit_message_caption(caption=f"{query.message.caption_markdown}\n\n❌ *Status Update: Rejected*", parse_mode='Markdown')
            except: query.message.reply_text("❌ *Session Status:* Force Declined.")
        
    pending_sessions.pop(session_id, None)

def process_admin_text_inputs(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    state = context.user_data.get('admin_action_state')
    
    if text.lower() == 'cancel':
        context.user_data['admin_action_state'] = None
        context.user_data.pop('temp_unlimited_duration', None)
        update.message.reply_text("❌ *Operation Cancelled*", parse_mode='Markdown')
        return
    
    if state == 'search_user':
        context.user_data['admin_action_state'] = None
        if text.startswith('@'):
            res = supabase.table("users").select("*").eq("username", text[1:]).execute()
        else:
            try: res = supabase.table("users").select("*").eq("telegram_id", int(text)).execute()
            except: res = None
            
        if res and res.data:
            match = res.data[0]
            escaped_un = escape_username(match.get('username'))
            unlimited_active, expiry, remaining = is_unlimited_active(match['telegram_id'])
            
            if unlimited_active and expiry:
                unlimited_status = f"✅ Active (Expires: {expiry.strftime('%Y-%m-%d')}, {remaining} days left)"
            else:
                unlimited_status = "❌ Inactive"
            
            update.message.reply_text(f"👤 *Database Record Detail:*\n\n🆔 ID: `{match['telegram_id']}`\n👤 Username: @{escaped_un}\n🪙 Balance: `{match.get('credits', 0)}`\n📊 Total Lookups: `{match.get('total_lookups_done', 0)}`\n🌟 Unlimited Plan: {unlimited_status}", parse_mode='Markdown')
        else:
            update.message.reply_text("❌ Target entry identity missing from active rows.")
            
    elif state == 'modify_credits':
        context.user_data['admin_action_state'] = None
        try:
            segments = text.split()
            if len(segments) == 2:
                target_id = int(segments[0])
                volume_offset = int(segments[1])
                
                if modify_credits(target_id, volume_offset):
                    update.message.reply_text(f"✅ Balance adjusted for profile `{target_id}` by `{volume_offset}` credits.")
                    try: context.bot.send_message(chat_id=target_id, text=f"🔔 *Balance Adjustment:* Account ledger modified by `{volume_offset}` credits.")
                    except: pass
                else:
                    update.message.reply_text("❌ Action aborted during execution update.")
            else:
                update.message.reply_text("❌ Format syntax validation mismatch.")
        except Exception as error:
            update.message.reply_text(f"❌ Input Parsing Crash Exception: {error}")
    
    elif state == 'activate_unlimited':
        duration_key = context.user_data.get('temp_unlimited_duration')
        if not duration_key or duration_key not in UNLIMITED_DURATIONS:
            context.user_data['admin_action_state'] = None
            update.message.reply_text("❌ Session expired. Please select a plan again.")
            return
            
        try:
            # Extract user ID from username or direct ID
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found in database.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            duration_days = UNLIMITED_DURATIONS[duration_key]['days']
            plan_label = UNLIMITED_DURATIONS[duration_key]['label']
            
            if activate_unlimited_plan(target_id, duration_days):
                expiry_date = datetime.now() + timedelta(days=duration_days)
                expiry_str = expiry_date.strftime('%Y-%m-%d')
                
                update.message.reply_text(
                    f"✅ *Unlimited Plan Activated* ✅\n\n"
                    f"👤 User ID: `{target_id}`\n"
                    f"📅 Duration: {plan_label}\n"
                    f"⏰ Expires on: `{expiry_str}`\n"
                    f"📆 Total days: `{duration_days}` days\n\n"
                    f"🎉 User can now perform unlimited lookups until expiry!",
                    parse_mode='Markdown'
                )
                
                try:
                    context.bot.send_message(
                        chat_id=target_id,
                        text=f"🌟 *Congratulations!* 🌟\n\n"
                        f"An *Unlimited Plan* has been activated for your account!\n\n"
                        f"📅 *Plan Details:*\n"
                        f"• Duration: {plan_label}\n"
                        f"• Expires on: `{expiry_str}`\n"
                        f"• Remaining: `{duration_days}` days\n\n"
                        f"🎯 You can now perform unlimited number lookups without any credit deductions.\n\n"
                        f"Enjoy the premium experience! 🚀",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed to activate unlimited plan. Please try again.")
            
            context.user_data['admin_action_state'] = None
            context.user_data.pop('temp_unlimited_duration', None)
            
        except Exception as error:
            update.message.reply_text(f"❌ Error: {error}")
            context.user_data['admin_action_state'] = None
            context.user_data.pop('temp_unlimited_duration', None)
    
    elif state == 'deactivate_unlimited':
        context.user_data['admin_action_state'] = None
        try:
            # Extract user ID from username or direct ID
            if text.startswith('@'):
                username = text[1:]
                user_res = supabase.table("users").select("telegram_id").eq("username", username).execute()
                if not user_res.data:
                    update.message.reply_text(f"❌ User @{username} not found in database.")
                    return
                target_id = user_res.data[0]['telegram_id']
            else:
                target_id = int(text)
            
            if deactivate_unlimited_plan(target_id):
                update.message.reply_text(
                    f"✅ *Unlimited Plan Deactivated* for user `{target_id}`.\n\n"
                    f"They will now use the standard credit system for lookups.",
                    parse_mode='Markdown'
                )
                
                try:
                    context.bot.send_message(
                        chat_id=target_id,
                        text=f"📋 *Plan Update*\n\n"
                        f"Your Unlimited Plan has been deactivated.\n\n"
                        f"You will now use the standard credit system for lookups.\n"
                        f"Purchase credits to continue using the service.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                update.message.reply_text("❌ Failed to deactivate unlimited plan. User may not have an active plan.")
                
        except Exception as error:
            update.message.reply_text(f"❌ Error: {error}")

def process_forwarded_profiles(update: Update, context: CallbackContext):
    if is_admin(update.effective_user.id):
        msg = update.message
        forward = msg.forward_from
        if forward:
            escaped_un = escape_username(forward.username)
            info = f"📨 *Forwarded Profile Metadata Extraction:*\n\n👤 *Full Name:* {forward.full_name}\n🆔 *User ID:* `{forward.id}`\n👤 *Username Reference:* @{escaped_un if forward.username else 'None'}"
            msg.reply_text(info, parse_mode='Markdown', disable_web_page_preview=True)

def system_error_catch(update, context):
    logger.error(f"Global pipeline caught runtime error instance: {context.error}")

def main():
    server_thread = threading.Thread(target=start_health_server, daemon=True)
    server_thread.start()

    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    except Exception as e: logger.warning(f"Webhook cleanup routing warning: {e}")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.photo, handle_receipt_upload))
    dp.add_handler(MessageHandler(Filters.forwarded, process_forwarded_profiles))
    dp.add_handler(CallbackQueryHandler(handle_callback_query))
    dp.add_error_handler(system_error_catch)
    
    print("🤖 Production Service Pipeline Connected: Active...")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()