import os
import json
import logging
import requests
import http.server
import socketserver
import threading
from datetime import datetime
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters, CallbackContext
from supabase import create_client, Client

# Enable system logging framework
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= HARDCODED CONFIGURATION =============
BOT_TOKEN = "7752472424:AAFW045z9xWUXvQX5MAKCoi8FNLO22pOl0Y" 
ADMIN_USER_ID = 7850023357  # Active Dashboard Admin Identifier from screenshots

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

def remove_branding(text: str) -> str:
    lines = text.split('\n')
    filtered_lines = []
    ads_blacklist = [
        'branding', 'developer', 'gaurav', 'tracexdata', 
        'api_buy_link', 'website_link', 't.me/', 'telegram.me/', 
        'join our channel', 'must join', 'a_toolsx', 'view channel', 'license_info'
    ]
    for line in lines:
        if not any(bad_word in line.lower() for bad_word in ads_blacklist):
            filtered_lines.append(line)
    return '\n'.join(filtered_lines)

def check_maintenance() -> bool:
    try:
        response = supabase.table("settings").select("value").eq("key", "maintenance_mode").execute()
        if response.data and len(response.data) > 0:
            val = response.data[0].get("value")
            return val.lower() == 'true' if isinstance(val, str) else bool(val)
        return False
    except:
        return False

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
                "total_lookups_done": 0
            }
            supabase.table("users").insert(new_profile).execute()
            return new_profile
    except Exception as e:
        logger.error(f"Critical error on user sync operation: {e}")
        return {"telegram_id": user_id, "username": username, "credits": 0, "total_lookups_done": 0}

def modify_credits(user_id: int, volume: int) -> bool:
    try:
        profile = sync_account(user_id)
        target_bal = max(0, profile.get("credits", 0) + volume)
        res = supabase.table("users").update({"credits": target_bal}).eq("telegram_id", user_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Database error balancing data index columns: {e}")
        return False

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
        [InlineKeyboardButton("🚫 Dismiss Panel", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(layout)

# ============= CONSOLE LOGIC ROUTER PIPELINES =============
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    sync_account(user.id, user.username)
    context.user_data.clear() # Clear state tokens to prevent deadlock logs
    
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

    # Substring flex searching to completely isolate emoji mismatch dependencies
    if "Number Lookup" in text or "📞" in text:
        profile = sync_account(user_id)
        if profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
            update.message.reply_text(f"⚠️ *Insufficient Balance:* You require at least `{CREDIT_COST_PER_LOOKUP}` credits.\n🪙 Current Balance: `{profile.get('credits', 0)}`", parse_mode='Markdown')
            return
        context.user_data['awaiting_lookup_target'] = True
        update.message.reply_text("📱 *Please enter the 10-digit mobile number you want to look up:*", parse_mode='Markdown')

    elif "Purchase Credits" in text or "💳" in text:
        update.message.reply_text("💳 *Select a currency package from the menu options below:*", parse_mode='Markdown', reply_markup=get_billing_keyboard())

    elif "My Plan" in text or "📊" in text:
        profile = sync_account(user_id, update.effective_user.username)
        status_msg = f"""
⭐ *Account Balance Metrics* ⭐
━━━━━━━━━━━━━━━━━━━━━
👤 *User ID:* `{profile['telegram_id']}`
🪙 *Available Credits:* `{profile['credits']}`
📊 *Total Lookups Executed:* `{profile['total_lookups_done']}`
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
        # Inform user without locking their regular interface buttons
        update.message.reply_text("⚠️ *Awaiting Payment Verification:* Please upload the transaction screenshot image directly here to proceed, or click another action.", parse_mode='Markdown')

def send_safely_in_chunks(update: Update, text: str):
    clean_text = remove_branding(text)
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
    
    if profile.get('credits', 0) < CREDIT_COST_PER_LOOKUP:
        update.message.reply_text("⚠️ *Transaction Denied:* Insufficient runtime balances.", parse_mode='Markdown')
        return
        
    loader = update.message.reply_text("⚡ *Querying Central Data Registry...*", parse_mode='Markdown')
    
    try:
        response = requests.get(LOOKUP_API.format(query_number), timeout=15)
        if response.status_code == 200:
            payload = response.json()
            if payload.get('status') == 'success' and payload.get('success'):
                records = payload.get('results', {})
                total_found = payload.get('results_found', 0)
                
                if total_found > 0:
                    modify_credits(user_id, -CREDIT_COST_PER_LOOKUP)
                    supabase.table("users").update({"total_lookups_done": profile.get('total_lookups_done', 0) + 1}).eq("telegram_id", user_id).execute()
                    
                    response_payload = f"📱 *Lookup Records for:* `{query_number}`\n━━━━━━━━━━━━━━━━━━━━━\n📊 *Total Found:* {total_found}\n💸 *Cost:* {CREDIT_COST_PER_LOOKUP} Credits Deducted\n━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
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
                update.message.reply_text("❌ *Query Failure:* Registry returned invalid execution arguments.", parse_mode='Markdown')
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
            invoice_text = f"💳 *Invoice Reference:* `{session_id}`\n━━━━━━━━━━━━━━━━━━━━━\n📦 *Selected Package:* {plan['label']}\n💵 *Total Cost Due:* ₹{plan['price']}\n\n👉 *Instructions:* Scan the QR code below to finalize payment. Once done, upload the screenshot receipt image directly into this chat layout."
            
            qr_path = os.path.join(os.getcwd(), "qr.png")
            if os.path.exists(qr_path):
                with open(qr_path, 'rb') as image:
                    query.message.reply_photo(photo=image, caption=invoice_text, parse_mode='Markdown')
            else:
                query.message.reply_text(f"⚠️ *QR Media Code Missing:*\n\n{invoice_text}", parse_mode='Markdown', disable_web_page_preview=True)
                
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
    context.user_data['payment_state_token'] = None # Clear state completely here to stop loop warnings
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
    context.user_data['admin_action_state'] = None 
    
    if state == 'search_user':
        if text.startswith('@'):
            res = supabase.table("users").select("*").eq("username", text[1:]).execute()
        else:
            try: res = supabase.table("users").select("*").eq("telegram_id", int(text)).execute()
            except: res = None
            
        if res and res.data:
            match = res.data[0]
            escaped_un = escape_username(match.get('username'))
            update.message.reply_text(f"👤 *Database Record Detail:*\n\n🆔 ID: `{match['telegram_id']}`\n👤 Username: @{escaped_un}\n🪙 Balance: `{match.get('credits', 0)}`\n📊 Total Lookups: `{match.get('total_lookups_done', 0)}`", parse_mode='Markdown')
        else:
            update.message.reply_text("❌ Target entry identity missing from active rows.")
            
    elif state == 'modify_credits':
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
