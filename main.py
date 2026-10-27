import os
import re
import threading
import time
from datetime import datetime, timedelta
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask

# ⚙️ Environment Variables & Config
BOT_TOKEN = "8868042763:AAHHKMQCQ8yFrF6OkrywTNoV4urwWFUdWys"
DB_URI = "postgresql://postgres.knktfswiljvqttbnlufg:%23%23RoKy5502%23%23@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
ADMIN_CHAT_ID = "8383532004"
PRIVATE_GROUP_ID = -1004465038452

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home(): return "KBKh Task Bot is Alive!", 200
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

def get_bd_time():
    return datetime.utcnow() + timedelta(hours=6)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# 🛠️ Database Setup
def init_db():
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Enable AI Text Similarity Extension
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                telegram_id BIGINT PRIMARY KEY, fb_name TEXT, team_name TEXT, 
                role TEXT DEFAULT 'General', status TEXT DEFAULT 'Approved'
            );
            CREATE TABLE IF NOT EXISTS active_assignments (
                id SERIAL PRIMARY KEY, task_num INT, is_started BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, 
                content_text TEXT, photo_id TEXT, status TEXT DEFAULT 'Pending',
                feedback TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS question_bank (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, 
                question_text TEXT, month TEXT
            );
        """)
        conn.close()
    except Exception as e: print(f"DB Init Error: {e}")

init_db()

# 🧠 State Management
user_state = {}
admin_state = {}

# ==========================================
# 🎹 KEYBOARDS (5 DOORS)
# ==========================================

def get_general_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Task"))
    markup.add(KeyboardButton("Submit QnA"), KeyboardButton("Submit Article"))
    markup.add(KeyboardButton("My Task Status"))
    return markup

def get_qna_marking_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Pending QnA"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def get_article_publish_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Pending Articles"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def get_secondary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(KeyboardButton("Members Status"))
    return markup

def get_primary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Task"), KeyboardButton("Task Assign"))
    markup.add(KeyboardButton("Edit Instructions"), KeyboardButton("Triggered Task"))
    markup.add(KeyboardButton("Reset Task Data"), KeyboardButton("Moderators"))
    return markup

def get_inline_cancel():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))

# ==========================================
# 🚪 LOGIN SYSTEM (MULTI-DOOR)
# ==========================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    tg_id = str(message.from_user.id)
    if tg_id == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Primary Admin Panel!", reply_markup=get_primary_admin_menu())
        return
    # Default to General Member View (assuming they are registered in 'members' DB)
    bot.send_message(message.chat.id, "Welcome to KBKh Bot Ecosystem!", reply_markup=get_general_menu())

@bot.message_handler(func=lambda msg: msg.text in ["QnAKEY22", "PublisherKEY22", "ADMINKEY22"])
def handle_secret_keys(message):
    tg_id = message.from_user.id
    key = message.text
    user_state[tg_id] = {'login_flow': key}
    msg_box = bot.send_message(message.chat.id, "Please Enter Your Full Name:", reply_markup=get_inline_cancel())
    bot.register_next_step_handler(msg_box, process_door_login)

def process_door_login(message):
    tg_id = message.from_user.id
    if tg_id not in user_state or 'login_flow' not in user_state[tg_id]: return
    
    full_name = message.text
    key = user_state[tg_id]['login_flow']
    
    if key == "QnAKEY22":
        user_state[tg_id]['name'] = full_name
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(InlineKeyboardButton("Alpha", callback_data="qteam_Alpha"), 
                   InlineKeyboardButton("Beta", callback_data="qteam_Beta"), 
                   InlineKeyboardButton("Gamma", callback_data="qteam_Gamma"))
        bot.send_message(message.chat.id, "Please Select Your Team:", reply_markup=markup)
        
    elif key == "PublisherKEY22":
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the main panel of the Article Publish Team!", reply_markup=get_article_publish_menu())
        user_state.pop(tg_id, None)
        
    elif key == "ADMINKEY22":
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the main Admin Panel!", reply_markup=get_secondary_admin_menu())
        user_state.pop(tg_id, None)

# ==========================================
# 📝 GENERAL MEMBER: TASK SUBMISSION SYSTEM
# ==========================================

def get_active_task():
    # Placeholder for checking active task. Assumes Task-1 is active for logic demonstration.
    return 1 # Change dynamically based on active_assignments in DB

@bot.message_handler(content_types=['text', 'photo'])
def handle_general_submissions(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID: return
    
    # Ignore menu buttons
    if message.content_type == 'text' and message.text in ["Task", "Submit QnA", "Submit Article", "My Task Status"]:
        return

    active_task = get_active_task()
    if not active_task:
        return bot.send_message(message.chat.id, "No Task available at this moment!")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM submissions WHERE telegram_id = %s AND task_num = %s", (tg_id, active_task))
    existing = cursor.fetchone()
    conn.close()
    
    if existing:
        return bot.send_message(message.chat.id, "You have already submitted the task once. Please wait for confirmation from the admin panel!")

    user_state[tg_id] = {'task_num': active_task, 'collected': []}
    
    # 📌 TASK 1 (Text Questions)
    if active_task == 1 and message.content_type == 'text':
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text):
            return bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
            
        check_and_process_question(message, text, is_photo=False)

    # 📌 TASK 2 (Photo Questions)
    elif active_task == 2 and message.content_type == 'photo':
        caption = message.caption
        if not caption:
            return bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
        
        check_and_process_question(message, caption, is_photo=True, photo_id=message.photo[-1].file_id)

    # 📌 TASK 3 (Photocard + Link)
    elif active_task == 3 and message.content_type == 'photo':
        caption = message.caption
        if not caption or not re.search(r'http[s]?://', caption):
            return bot.send_message(message.chat.id, "আপনি যে Article এর ওপর ভিত্তি করে Photocard তৈরি করেছেন, অনুগ্রহ করে ক্যাপশন হিসাবে উক্ত আর্টিকেল লিঙ্ক যুক্ত করে দিন। অন্যথায় টাস্ক গ্রহণ হবে না।❌")
        
        user_state[tg_id]['single_sub'] = {'photo': message.photo[-1].file_id, 'caption': caption}
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_photo(message.chat.id, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        
    # 📌 NORMAL TASK (Text or Photo)
    elif active_task not in [1, 2, 3]:
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['single_sub'] = {'photo': photo_id, 'caption': caption}
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        if photo_id: bot.send_photo(message.chat.id, photo_id, caption=caption, reply_markup=markup)
        else: bot.send_message(message.chat.id, caption, reply_markup=markup)

def check_and_process_question(message, question_text, is_photo=False, photo_id=None):
    tg_id = message.from_user.id
    month_name = get_bd_time().strftime("%B")
    
    # 🤖 AI Similarity Check (pg_trgm)
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT question_text, similarity(question_text, %s) as sim 
        FROM question_bank 
        WHERE month = %s AND similarity(question_text, %s) > 0.75 
        ORDER BY sim DESC LIMIT 1
    """, (question_text, month_name, question_text))
    match = cursor.fetchone()
    conn.close()
    
    if match:
        user_state[tg_id]['temp_hold'] = {'q': question_text, 'p': photo_id}
        warn_msg = (f"↗️Your Question: {question_text}\n\n"
                    f"↘️Previously Submitted Question:\n{match['question_text']}\n\n"
                    f"⚠️দুইটি প্রশ্নের মধ্যে প্রায় ৮০% মিল পাওয়া গিয়েছে। তাই এটি পোস্ট করা যাবে না। আপনার যদি মনে হয় Ai ভুল করছে তাহলে 'Submit Anyway' Button চেপে সাবমিট করতে পারবেন।")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit Anyway", callback_data="force_add_q"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, warn_msg, reply_markup=markup)
    else:
        add_question_to_state(message.chat.id, tg_id, question_text, photo_id)

def add_question_to_state(chat_id, tg_id, text, photo_id=None):
    user_state[tg_id]['collected'].append({'text': text, 'photo': photo_id})
    render_collected_questions(chat_id, tg_id)

def render_collected_questions(chat_id, tg_id):
    items = user_state[tg_id]['collected']
    msg = ""
    for item in items:
        if item['photo']: msg += f"[ছবি]\n{item['text']}\n\n"
        else: msg += f"{item['text']}\n"
    
    msg += "Would you like to add any more questions?"
    markup = InlineKeyboardMarkup(row_width=3)
    markup.row(InlineKeyboardButton("Yes", callback_data="add_more_q"), InlineKeyboardButton("No", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(chat_id, msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["add_more_q", "force_add_q", "final_submit_task", "cancel_action"])
def task_flow_callbacks(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass

    if call.data == "cancel_action":
        user_state.pop(tg_id, None)
        bot.delete_message(call.message.chat.id, call.message.message_id)

    elif call.data == "force_add_q":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        temp = user_state[tg_id].pop('temp_hold', None)
        if temp: add_question_to_state(call.message.chat.id, tg_id, temp['q'], temp['p'])

    elif call.data == "add_more_q":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg_box = bot.send_message(call.message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, handle_next_question)

    elif call.data == "final_submit_task":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        state = user_state.get(tg_id, {})
        t_num = state.get('task_num')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if 'single_sub' in state:
            cursor.execute("INSERT INTO submissions (telegram_id, task_num, content_text, photo_id) VALUES (%s, %s, %s, %s)", 
                           (tg_id, t_num, state['single_sub']['caption'], state['single_sub']['photo']))
        elif 'collected' in state:
            full_text = "\n\n".join([i['text'] for i in state['collected']])
            cursor.execute("INSERT INTO submissions (telegram_id, task_num, content_text) VALUES (%s, %s, %s) RETURNING id", (tg_id, t_num, full_text))
            
            # Save to Question Bank for similarity logic
            month_name = get_bd_time().strftime("%B")
            for q in state['collected']:
                cursor.execute("INSERT INTO question_bank (telegram_id, task_num, question_text, month) VALUES (%s, %s, %s, %s)", (tg_id, t_num, q['text'], month_name))
        
        conn.commit()
        conn.close()
        user_state.pop(tg_id, None)
        bot.send_message(call.message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")

def handle_next_question(message):
    tg_id = message.from_user.id
    if tg_id not in user_state: return
    active_task = user_state[tg_id].get('task_num')
    
    if active_task == 1:
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text):
            bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
            return bot.register_next_step_handler(message, handle_next_question)
        check_and_process_question(message, text, False)
        
    elif active_task == 2:
        if message.content_type != 'photo' or not message.caption:
            bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
            return bot.register_next_step_handler(message, handle_next_question)
        check_and_process_question(message, message.caption, True, message.photo[-1].file_id)

# ==========================================
# 👑 PRIMARY ADMIN: GRADING SYSTEM
# ==========================================

@bot.message_handler(func=lambda msg: msg.text == "Task")
def admin_task_review(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "Task Menu:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["adm_tsub", "adm_tcomp"])
def admin_task_lists(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    
    is_completed = (call.data == "adm_tcomp")
    status_filter = 'Approved' if is_completed else 'Pending'
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT s.id, s.telegram_id, m.fb_name, m.team_name 
        FROM submissions s 
        JOIN members m ON s.telegram_id = m.telegram_id 
        WHERE s.status = %s
    """, (status_filter,))
    records = cursor.fetchall()
    conn.close()
    
    if not records:
        return bot.edit_message_text("No status found!", call.message.chat.id, call.message.message_id, reply_markup=get_inline_cancel())
        
    teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
    for r in records:
        t_name = r.get('team_name', 'Team Alpha')
        if t_name in teams: teams[t_name].append(r)
        
    markup = InlineKeyboardMarkup(row_width=1)
    for team, members in teams.items():
        markup.add(InlineKeyboardButton(f"🔺{team}", callback_data="ignore"))
        for m in members:
            # Clicking a name opens grading
            markup.add(InlineKeyboardButton(f"{m['fb_name']}", callback_data=f"grd_{m['id']}"))
            
    markup.row(InlineKeyboardButton("Back", callback_data="ignore"), InlineKeyboardButton("Cancel" if not is_completed else "Close", callback_data="cancel_action"))
    bot.edit_message_text("Submissions List:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("grd_"))
def admin_grading_view(call):
    sub_id = int(call.data.split("_")[1])
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    if not sub: return
    
    admin_state[ADMIN_CHAT_ID] = {'grading_sub': sub_id, 'action': None}
    
    caption = f"{sub['content_text']}\nName: {sub['fb_name']}\nTeam: {sub['team_name']}"
    markup = get_admin_grading_kb(sub_id)
    
    if sub['photo_id']: bot.send_photo(call.message.chat.id, sub['photo_id'], caption=caption, reply_markup=markup)
    else: bot.send_message(call.message.chat.id, caption, reply_markup=markup)

def get_admin_grading_kb(sub_id, action=None):
    markup = InlineKeyboardMarkup(row_width=2)
    ap_btn = "Approve✅" if action == "approve" else "Approve"
    rj_btn = "Reject✅" if action == "reject" else "Reject"
    markup.row(InlineKeyboardButton(ap_btn, callback_data=f"gact_{sub_id}_approve"), InlineKeyboardButton(rj_btn, callback_data=f"gact_{sub_id}_reject"))
    markup.add(InlineKeyboardButton("- Feedback -", callback_data=f"gfbk_{sub_id}"))
    markup.row(InlineKeyboardButton("Submit", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("gact_") or call.data.startswith("gfbk_") or call.data.startswith("gsub_"))
def admin_grading_actions(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    
    parts = call.data.split("_")
    action_type = parts[0]
    sub_id = int(parts[1])
    
    if action_type == "gact":
        admin_state[ADMIN_CHAT_ID]['action'] = parts[2]
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_grading_kb(sub_id, parts[2]))
        
    elif action_type == "gfbk":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, process_admin_feedback, sub_id)
        
    elif action_type == "gsub":
        act = admin_state.get(ADMIN_CHAT_ID, {}).get('action')
        feedback = admin_state.get(ADMIN_CHAT_ID, {}).get('feedback')
        if not act: return bot.answer_callback_query(call.id, "Please select Approve or Reject!", show_alert=True)
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        finalize_grading(sub_id, act, feedback)

def process_admin_feedback(message, sub_id):
    admin_state[ADMIN_CHAT_ID]['feedback'] = message.text
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    act = admin_state[ADMIN_CHAT_ID].get('action', 'reject')
    caption = f"{sub['content_text']}\nName: {sub['fb_name']}\nTeam: {sub['team_name']}\n◀️Feedback: {message.text}"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("Send", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    
    if sub['photo_id']: bot.send_photo(message.chat.id, sub['photo_id'], caption=caption, reply_markup=markup)
    else: bot.send_message(message.chat.id, caption, reply_markup=markup)

def finalize_grading(sub_id, status_act, feedback=None):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM submissions WHERE id = %s", (sub_id,))
    sub = cursor.fetchone()
    
    if status_act == "approve":
        cursor.execute("UPDATE submissions SET status = 'Approved' WHERE id = %s", (sub_id,))
        user_msg = "Your task has been successfully reviewed and marked as completed!✅"
        if feedback: user_msg += f"\n◀️Feedback: {feedback}"
        
        # 📌 TASK 3: Forward to Private Group
        if sub['task_num'] == 3:
            fwd_cap = f"{sub['content_text']}\nName: (Approved by Admin)"
            try:
                if sub['photo_id']: bot.send_photo(PRIVATE_GROUP_ID, sub['photo_id'], caption=fwd_cap)
                else: bot.send_message(PRIVATE_GROUP_ID, fwd_cap)
            except Exception as e: print(f"Group Forward Error: {e}")
            
    else:
        cursor.execute("DELETE FROM submissions WHERE id = %s", (sub_id,))
        user_msg = f"{sub['content_text']}\nTask Status: Failed❌\n"
        if feedback: user_msg += f"◀️Feedback: {feedback}"
        else: user_msg += "Please try again. If the issue persists, contact a senior team member for assistance."
        
    conn.commit()
    conn.close()
    
    try: bot.send_message(sub['telegram_id'], user_msg)
    except: pass

# ==========================================
# 🚧 COMING SOON PLACEHOLDERS
# ==========================================
@bot.message_handler(func=lambda msg: msg.text in ["Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "Task Assign", "Edit Instructions", "Triggered Task", "Reset Task Data", "Moderators"])
def coming_soon(message):
    bot.send_message(message.chat.id, "⏳ This feature is Coming Soon!")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("🤖 KBKh Task Bot (5 Doors Edition) is running...")
    bot.infinity_polling()
