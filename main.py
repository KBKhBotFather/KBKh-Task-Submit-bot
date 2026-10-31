import os
import re
import threading
import time
import json
from datetime import datetime, timedelta
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask

BOT_TOKEN = "8868042763:AAHHKMQCQ8yFrF6OkrywTNoV4urwWFUdWys"
DB_URI = "postgresql://postgres.knktfswiljvqttbnlufg:%23%23RoKy5502%23%23@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
ADMIN_CHAT_ID = "8383532004"
PRIVATE_GROUP_ID = -1004465038452

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)
app = Flask(__name__)

@app.route('/')
def home(): return "KBKh Task Bot is Alive & Fast!", 200
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
def get_bd_time(): return datetime.utcnow() + timedelta(hours=6)
def get_db_connection(): return psycopg2.connect(DB_URI)

# ==========================================
# 🛠️ DATABASE SETUP
# ==========================================
def init_db():
    conn = get_db_connection()
    try:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kbkh_active_assignments (id SERIAL PRIMARY KEY, team_name TEXT, task_num INT, scheduled_for TIMESTAMP, is_started BOOLEAN DEFAULT FALSE, current_msg INT DEFAULT 0);
            CREATE TABLE IF NOT EXISTS kbkh_submissions (id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, content_type TEXT, content_text TEXT, photo_id TEXT, status TEXT DEFAULT 'Pending', feedback TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS kbkh_tasks (id SERIAL PRIMARY KEY, task_num INT UNIQUE, msg_1 TEXT, msg_2 TEXT, msg_3 TEXT);
            CREATE TABLE IF NOT EXISTS kbkh_organized_tasks (id SERIAL PRIMARY KEY, sequence TEXT);
            CREATE TABLE IF NOT EXISTS kbkh_question_bank (id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, question_text TEXT, month TEXT);
            CREATE TABLE IF NOT EXISTS kbkh_user_task_status (telegram_id BIGINT, task_num INT, completed BOOLEAN DEFAULT FALSE, UNIQUE(telegram_id, task_num));
            CREATE TABLE IF NOT EXISTS kbkh_qna_moderators (telegram_id BIGINT PRIMARY KEY, mod_name TEXT, team_name TEXT, is_active BOOLEAN DEFAULT TRUE, total_assigned INT DEFAULT 0, resign_count INT DEFAULT 0, is_blocked BOOLEAN DEFAULT FALSE);
            CREATE TABLE IF NOT EXISTS kbkh_qna_submissions (id SERIAL PRIMARY KEY, telegram_id BIGINT, q_dict TEXT, a_dict TEXT, status TEXT DEFAULT 'Pending', assigned_grader BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, feedback TEXT, mark INT);
            CREATE TABLE IF NOT EXISTS kbkh_task_records (telegram_id BIGINT, month TEXT, task_done INT DEFAULT 0, task_total INT DEFAULT 0, qna_mark INT DEFAULT 0, UNIQUE(telegram_id, month));
            CREATE TABLE IF NOT EXISTS kbkh_custom_instructions (id INT PRIMARY KEY, instruction_text TEXT);
        """)
        default_inst = {
            1: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!", 2: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!",
            3: "উত্তরের মান উন্নত করা প্রয়োজন!", 4: "মোটামুটি ভালো হয়েছে। আরও ভালো করার চেষ্টা করতে হবে।",
            5: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।", 6: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।"
        }
        for k, v in default_inst.items():
            try: cursor.execute("INSERT INTO kbkh_custom_instructions (id, instruction_text) VALUES (%s, %s) ON CONFLICT DO NOTHING", (k, v))
            except: pass
    except Exception as e: print(f"DB Init Error: {e}")
    finally: conn.close()

init_db()
user_state = {}
admin_state = {}

# ==========================================
# 🎹 KEYBOARDS & HELPERS
# ==========================================
def member_main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Task"))
    markup.add(KeyboardButton("Submit QnA"), KeyboardButton("Submit Article"))
    markup.add(KeyboardButton("My Task Status"))
    return markup

def primary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Task"), KeyboardButton("Task Assign"))
    markup.add(KeyboardButton("Edit Instructions"), KeyboardButton("Triggered Task"))
    markup.add(KeyboardButton("Reset Task Data"), KeyboardButton("Moderators"))
    return markup

def qna_marking_menu(): return ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True).add(KeyboardButton("Pending QnA"), KeyboardButton("Members Status"), KeyboardButton("Resign⚠️"))
def article_publish_menu(): return ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True).add(KeyboardButton("Pending Articles"), KeyboardButton("Members Status"), KeyboardButton("Resign⚠️"))
def secondary_admin_menu(): return ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, is_persistent=True).add(KeyboardButton("Members Status"))
def get_inline_cancel(): return InlineKeyboardMarkup().add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))

def check_member_registration(tg_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT fb_name, team_name, status FROM members WHERE telegram_id = %s AND status = 'Approved' AND is_blocked = FALSE AND is_removed = FALSE", (tg_id,))
        return cursor.fetchone()
    finally: conn.close()

def get_least_loaded_qna_mod():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id FROM kbkh_qna_moderators WHERE is_active = TRUE AND is_blocked = FALSE ORDER BY total_assigned ASC, telegram_id ASC LIMIT 1")
        mod = cursor.fetchone()
        return mod['telegram_id'] if mod else None
    finally: conn.close()

# ==========================================
# 🚪 MULTI-DOOR LOGIN
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Primary Admin Panel!", reply_markup=primary_admin_menu())
        return
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT is_active, is_blocked FROM kbkh_qna_moderators WHERE telegram_id = %s", (tg_id,))
        mod = cursor.fetchone()
        if mod and mod['is_active'] and not mod['is_blocked']:
            return bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are back in QnA Marking Team!", reply_markup=qna_marking_menu())
        if mod and mod['is_blocked']:
            return bot.send_message(message.chat.id, "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
    finally: conn.close()

    user = check_member_registration(tg_id)
    if user: bot.send_message(message.chat.id, f"Welcome to KBKh Bot Ecosystem, {user['fb_name']}!\nYou are in {user['team_name']}.", reply_markup=member_main_menu())
    else: bot.send_message(message.chat.id, "You are not registered yet❌\nPlease register from the Registration Bot first.", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(commands=['start_task'])
def trigger_task_now(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        past_time = get_bd_time() - timedelta(minutes=2)
        cursor.execute("UPDATE kbkh_active_assignments SET scheduled_for = %s WHERE is_started = FALSE", (past_time,))
        conn.commit()
        bot.send_message(message.chat.id, "Cheat Code Activated! 🚀\n\nAny pending assigned task will trigger within the next 60 seconds.")
    except Exception as e: bot.send_message(message.chat.id, f"Cheat Code Error: {e}")
    finally: conn.close()

@bot.message_handler(func=lambda msg: msg.text in ["QnAKEY22", "PublisherKEY22", "ADMINKEY22"])
def handle_secret_keys(message):
    tg_id = message.from_user.id
    user_state[tg_id] = {'login_flow': message.text}
    msg_box = bot.send_message(message.chat.id, "Please Enter Your Full Name:", reply_markup=get_inline_cancel())
    bot.register_next_step_handler(msg_box, process_door_login)

def process_door_login(message):
    tg_id = message.from_user.id
    if tg_id not in user_state or 'login_flow' not in user_state[tg_id]: return
    key = user_state[tg_id]['login_flow']
    user_state[tg_id]['mod_name'] = message.text.strip()
    
    if key == "QnAKEY22":
        markup = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("Alpha", callback_data="qteam_Team Alpha"), InlineKeyboardButton("Beta", callback_data="qteam_Team Beta"), InlineKeyboardButton("Gamma", callback_data="qteam_Team Gamma"))
        bot.send_message(message.chat.id, "Please Select Your Team:", reply_markup=markup)
    elif key == "PublisherKEY22":
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Article Publish Team!", reply_markup=article_publish_menu())
        user_state.pop(tg_id, None)
    elif key == "ADMINKEY22":
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Secondary Admin Panel!", reply_markup=secondary_admin_menu())
        user_state.pop(tg_id, None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("qteam_"))
def finalize_qna_login(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    team = call.data.split("_")[1]
    name = user_state.get(tg_id, {}).get('mod_name', str(tg_id))
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kbkh_qna_moderators (telegram_id, mod_name, team_name, is_active) VALUES (%s, %s, %s, TRUE) ON CONFLICT (telegram_id) DO UPDATE SET is_active = TRUE, mod_name = %s, team_name = %s", (tg_id, name, team, name, team))
        conn.commit()
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        bot.send_message(call.message.chat.id, "Welcome Sir❤️\nYou are now in QnA Marking Team!", reply_markup=qna_marking_menu())
    finally: conn.close()
    user_state.pop(tg_id, None)

# ==========================================
# 🟢 COMBINED TASK HANDLER
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Task")
def handle_task_routing(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID:
        markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Task Menu:", reply_markup=markup)
        return

    user = check_member_registration(tg_id)
    if not user: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT task_num, current_msg FROM kbkh_active_assignments WHERE team_name = %s AND is_started = TRUE", (user['team_name'],))
        assign = cursor.fetchone()
        
        if not assign: 
            bot.send_message(message.chat.id, "No Task available at this moment!")
        else:
            cursor.execute("SELECT completed FROM kbkh_user_task_status WHERE telegram_id = %s AND task_num = %s", (tg_id, assign['task_num']))
            uts = cursor.fetchone()
            if uts and uts['completed']:
                cursor.execute("SELECT status FROM kbkh_submissions WHERE telegram_id = %s AND task_num = %s ORDER BY id DESC LIMIT 1", (tg_id, assign['task_num']))
                sub_status = cursor.fetchone()
                if sub_status and sub_status['status'] == 'Pending': bot.send_message(message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")
                else: bot.send_message(message.chat.id, "Your task has been successfully reviewed and marked as completed!✅")
            else:
                cursor.execute("SELECT msg_1, msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (assign['task_num'],))
                t_data = cursor.fetchone()
                msgs = []
                if t_data and t_data['msg_1'] and assign['current_msg'] >= 1: msgs.append(t_data['msg_1'])
                if t_data and t_data['msg_2'] and assign['current_msg'] >= 2: msgs.append(t_data['msg_2'])
                if t_data and t_data['msg_3'] and assign['current_msg'] >= 3: msgs.append(t_data['msg_3'])
                bot.send_message(message.chat.id, "\n\n".join(msgs) if msgs else "Task started, please wait for instructions.")
    finally: conn.close()

# ==========================================
# 🟢 ADMIN ONLY MENUS
# ==========================================
@bot.message_handler(func=lambda msg: msg.text in ["Task Assign", "Triggered Task", "Reset Task Data", "Edit Instructions"])
def admin_management_buttons(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    text = message.text
    if text == "Task Assign":
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Add Task", callback_data="ta_add"), InlineKeyboardButton("Task List", callback_data="ta_list")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Task Assign Menu:", reply_markup=markup)
    elif text == "Triggered Task":
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT team_name, task_num, is_started FROM kbkh_active_assignments ORDER BY id ASC")
            assigns = cursor.fetchall()
            if not assigns: 
                bot.send_message(message.chat.id, "No Task Triggered!")
            else:
                is_st = any(a['is_started'] for a in assigns)
                msg_text = "".join([f"{a['team_name']} - Task {a['task_num']}\n" for a in assigns]) + f"\nTask Status: {'Started!🟢' if is_st else 'Not Assigned yet!🔴'}"
                markup = InlineKeyboardMarkup(row_width=2)
                if not is_st: markup.add(InlineKeyboardButton("Stop Task", callback_data="ta_stop"))
                else: markup.add(InlineKeyboardButton("End", callback_data="ta_force_end"))
                markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
                bot.send_message(message.chat.id, msg_text, reply_markup=markup)
        finally: conn.close()
    elif text == "Reset Task Data":
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Yes", callback_data="reset_task_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Are you sure you want to reset all Task Data?", reply_markup=markup)
    elif text == "Edit Instructions":
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Task Instructions", callback_data="ei_task"), InlineKeyboardButton("QnA Instructions", callback_data="ei_qna")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Edit Instructions:", reply_markup=markup)

# ==========================================
# 🟢 RESTORED: QnA & STATUS MENUS
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Submit QnA")
def start_qna_submit(message):
    tg_id = message.from_user.id
    user = check_member_registration(tg_id)
    if not user: return
    user_state[tg_id] = {'flow': 'wait_q', 'q_dict': None, 'a_dict': None}
    bot.send_message(message.chat.id, "Please submit the question:", reply_markup=get_inline_cancel())

@bot.message_handler(func=lambda msg: msg.text == "Pending QnA")
def qna_pending_list(message):
    tg_id = message.from_user.id
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT is_active FROM kbkh_qna_moderators WHERE telegram_id = %s", (tg_id,))
        mod = cursor.fetchone()
        if not mod or not mod['is_active']: return
        
        cursor.execute("""
            SELECT s.telegram_id, m.fb_name, m.team_name, COUNT(s.id) as total 
            FROM kbkh_qna_submissions s 
            JOIN members m ON s.telegram_id = m.telegram_id 
            WHERE s.assigned_grader = %s AND s.status = 'Pending' 
            GROUP BY s.telegram_id, m.fb_name, m.team_name
        """, (tg_id,))
        records = cursor.fetchall()
        
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for r in records:
            if r['team_name'] in teams: teams[r['team_name']].append(r)
            
        markup = InlineKeyboardMarkup(row_width=1)
        exp_team = admin_state.get(tg_id, {}).get('qna_exp_team')
        
        for team in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if exp_team == team:
                markup.add(InlineKeyboardButton(f"🔺--{team}--🔺", callback_data=f"qna_tg_{team}"))
                for m in teams[team]: markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"qna_user_{m['telegram_id']}"))
            else:
                markup.add(InlineKeyboardButton(f"🔻--{team}--🔻", callback_data=f"qna_tg_{team}"))
                
        markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Pending QnA List:", reply_markup=markup)
    finally: conn.close()

@bot.message_handler(func=lambda msg: msg.text == "Resign⚠️")
def handle_qna_resign(message):
    tg_id = message.from_user.id
    markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Yes", callback_data="qna_res_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "⚠️Are you sure you want to resign?", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in ["My Task Status", "Members Status"])
def status_selectors(message):
    tg_id = message.from_user.id
    if message.text == "My Task Status":
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("myts"))
    else:
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("modst"))

def get_months_kb(prefix):
    markup = InlineKeyboardMarkup(row_width=3)
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    btns = [InlineKeyboardButton(m[:3], callback_data=f"{prefix}_{m}") for m in months]
    markup.add(*btns)
    markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
    return markup

# ==========================================
# 👑 MAIN ADMIN: MODERATORS PANEL
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Moderators")
def admin_moderators_panel(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    render_main_admin_mods(message.chat.id, None)

def render_main_admin_mods(chat_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, mod_name, team_name, total_assigned FROM kbkh_qna_moderators WHERE is_active = TRUE")
        mods = cursor.fetchall()
        
        markup = InlineKeyboardMarkup(row_width=1)
        exp_team = admin_state.get(ADMIN_CHAT_ID, {}).get('admin_mod_exp')
        
        if exp_team == 'qna':
            markup.add(InlineKeyboardButton("QnA Making Team 🔻", callback_data="amod_qna"))
            teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
            for m in mods:
                if m['team_name'] in teams: teams[m['team_name']].append(m)
            
            for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
                if teams[t]:
                    markup.add(InlineKeyboardButton(f"--{t}--", callback_data="ignore"))
                    for m in teams[t]:
                        btn_name = InlineKeyboardButton(f"{m['mod_name']} - {m['total_assigned']}", callback_data="ignore")
                        btn_blk = InlineKeyboardButton("⛔", callback_data=f"amodblk_{m['telegram_id']}")
                        btn_kck = InlineKeyboardButton("❌", callback_data=f"amodkck_{m['telegram_id']}")
                        markup.row(btn_name, btn_blk, btn_kck)
            markup.add(InlineKeyboardButton("Submit", callback_data="amod_sub"))
        else:
            markup.add(InlineKeyboardButton("QnA Making Team 🔺", callback_data="amod_qna"))
            
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if message_id:
            try: bot.edit_message_text("Admin Moderators Panel:", chat_id, message_id, reply_markup=markup)
            except: pass
        else: bot.send_message(chat_id, "Admin Moderators Panel:", reply_markup=markup)
    finally: conn.close()

# ==========================================
# 📝 GENERAL TASK & CONTENT SUBMISSION
# ==========================================
@bot.message_handler(content_types=['text', 'photo'])
def handle_general_submissions(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID: return
    
    menu_items = ["Task", "Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "QnAKEY22", "PublisherKEY22", "ADMINKEY22"]
    if message.content_type == 'text' and message.text in menu_items: return
    
    if tg_id in user_state and user_state[tg_id].get('waiting_btn'):
        return bot.send_message(message.chat.id, "অনুগ্রহ করে পূর্বের মেসেজ এ \"Yes, No বা Cancel\" চেপে কমান্ড প্রদান করে পরবর্তী ধাপের কাজ করুন।")
    
    # QnA Flow Interceptor
    if tg_id in user_state and user_state[tg_id].get('flow') == 'wait_q':
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['q_dict'] = {'text': caption, 'photo': photo_id}
        user_state[tg_id]['flow'] = 'wait_a'
        bot.send_message(message.chat.id, "Please submit your answer:", reply_markup=get_inline_cancel())
        return
        
    if tg_id in user_state and user_state[tg_id].get('flow') == 'wait_a':
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['a_dict'] = {'text': caption, 'photo': photo_id}
        user_state[tg_id]['flow'] = 'qna_preview'
        markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Submit", callback_data="qna_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        send_qna_preview(message.chat.id, user_state[tg_id]['q_dict'], user_state[tg_id]['a_dict'], markup)
        return

    # Normal Task Logic
    user = check_member_registration(tg_id)
    if not user: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT task_num FROM kbkh_active_assignments WHERE team_name = %s AND is_started = TRUE", (user['team_name'],))
        assign = cursor.fetchone()
        if not assign: return bot.send_message(message.chat.id, "No Task available at this moment!")
        
        active_task = assign['task_num']
        cursor.execute("SELECT completed FROM kbkh_user_task_status WHERE telegram_id = %s AND task_num = %s", (tg_id, active_task))
        uts = cursor.fetchone()
        if uts and uts['completed']: return bot.send_message(message.chat.id, "You have already submitted the task once. Please wait for confirmation from the admin panel!")
    finally: conn.close()

    user_state[tg_id] = {'task_num': active_task, 'collected': []}
    
    if active_task == 1 and message.content_type == 'text':
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text): return bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
        check_and_process_question(message, text, is_photo=False)
    elif active_task == 2 and message.content_type == 'photo':
        caption = message.caption
        if not caption: return bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
        check_and_process_question(message, caption, is_photo=True, photo_id=message.photo[-1].file_id)
    elif active_task == 3 and message.content_type == 'photo':
        caption = message.caption
        if not caption or not re.search(r'http[s]?://', caption): return bot.send_message(message.chat.id, "আপনি যে Article এর ওপর ভিত্তি করে Photocard তৈরি করেছেন, অনুগ্রহ করে ক্যাপশন হিসাবে উক্ত আর্টিকেল লিঙ্ক যুক্ত করে দিন। অন্যথায় টাস্ক গ্রহণ হবে না।❌")
        user_state[tg_id]['single_sub'] = {'photo': message.photo[-1].file_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_photo(message.chat.id, message.photo[-1].file_id, caption=caption, reply_markup=markup)
    elif active_task not in [1, 2, 3]:
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['single_sub'] = {'photo': photo_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if photo_id: bot.send_photo(message.chat.id, photo_id, caption=caption, reply_markup=markup)
        else: bot.send_message(message.chat.id, caption, reply_markup=markup)

# ==========================================
# 🟢 QnA PREVIEW HELPER
# ==========================================
def send_qna_preview(chat_id, q_dict, a_dict, markup=None):
    q_txt = q_dict.get('text', '')
    q_pic = q_dict.get('photo')
    a_txt = a_dict.get('text', '')
    a_pic = a_dict.get('photo')
    
    if q_pic and not a_pic: bot.send_photo(chat_id, q_pic, caption=f"{q_txt}\n\nAnswer: {a_txt}"[:1024], reply_markup=markup)
    elif not q_pic and a_pic: bot.send_photo(chat_id, a_pic, caption=f"{q_txt}\n\nAnswer: {a_txt}"[:1024], reply_markup=markup)
    elif q_pic and a_pic:
        bot.send_photo(chat_id, q_pic, caption=q_txt)
        bot.send_photo(chat_id, a_pic, caption=f"Answer: {a_txt}"[:1024], reply_markup=markup)
    else: bot.send_message(chat_id, f"{q_txt}\n\nAnswer: {a_txt}", reply_markup=markup)

# ==========================================
# 🟢 TASK PROCESSING HELPER (With Anti-Jam & 80% Text)
# ==========================================
def check_and_process_question(message, question_text, is_photo=False, photo_id=None):
    tg_id = message.from_user.id
    month_name = get_bd_time().strftime("%B")
    conn = get_db_connection()
    match = None
    matched_line = ""
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        lines = [line.strip() for line in question_text.split('\n') if len(line.strip()) > 4]
        for line in lines:
            cursor.execute("SELECT question_text, similarity(question_text, %s) as sim FROM kbkh_question_bank WHERE month = %s AND similarity(question_text, %s) > 0.35 ORDER BY sim DESC LIMIT 1", (line, month_name, line))
            res = cursor.fetchone()
            if res:
                match = res
                matched_line = line
                break
        if not match and len(lines) == 0:
            cursor.execute("SELECT question_text, similarity(question_text, %s) as sim FROM kbkh_question_bank WHERE month = %s AND similarity(question_text, %s) > 0.35 ORDER BY sim DESC LIMIT 1", (question_text, month_name, question_text))
            res = cursor.fetchone()
            if res:
                match = res
                matched_line = question_text
    finally: conn.close()
    
    if match:
        user_state[tg_id]['temp_hold'] = {'q': question_text, 'p': photo_id}
        warn_msg = f"↗️Your Question: {matched_line}\n\n↘️ Previously Submitted Question:\n{match['question_text']}\n\n⚠️দুইটি প্রশ্নের মধ্যে অনেকটা মিল পাওয়া গিয়েছে। তাই এটি পোস্ট করা যাবে না। আপনার যদি মনে হয় Ai ভুল করছে তাহলে 'Submit Anyway' Button চেপে সাবমিট করতে পারবেন।"
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Anyway", callback_data="force_add_q"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, warn_msg, reply_markup=markup)
    else: add_question_to_state(message.chat.id, tg_id, question_text, photo_id)

def add_question_to_state(chat_id, tg_id, text, photo_id=None):
    user_state[tg_id]['collected'].append({'text': text, 'photo': photo_id})
    user_state[tg_id]['waiting_btn'] = True 
    items = user_state[tg_id]['collected']
    for i in items:
        if i['photo']: bot.send_photo(chat_id, i['photo'], caption=i['text'])
        else: bot.send_message(chat_id, i['text'])
    markup = InlineKeyboardMarkup(row_width=3).row(InlineKeyboardButton("Yes", callback_data="add_more_q"), InlineKeyboardButton("No", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(chat_id, "Would you like to add any more questions?", reply_markup=markup)

def handle_next_question(message):
    tg_id = message.from_user.id
    if tg_id not in user_state: return
    active_task = user_state[tg_id].get('task_num')
    if active_task == 1:
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text):
            bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
            msg_box = bot.send_message(message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, handle_next_question)
            return
        check_and_process_question(message, text, False)
    elif active_task == 2:
        if message.content_type != 'photo' or not message.caption:
            bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
            msg_box = bot.send_message(message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, handle_next_question)
            return
        check_and_process_question(message, message.caption, True, message.photo[-1].file_id)

# ==========================================
# 🔗 ALL CALLBACKS MANAGER
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def central_callback_handler(call):
    tg_id = call.from_user.id
    data = call.data
    try: bot.answer_callback_query(call.id)
    except: pass

    # 1. CANCEL ACTION
    if data == "cancel_action":
        user_state.pop(tg_id, None)
        if tg_id in admin_state:
            admin_state[tg_id].pop('feedback', None)
            admin_state[tg_id].pop('action', None)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        try: bot.clear_step_handler_by_chat_id(call.message.chat.id)
        except: pass
        return

    # 2. TASK SUBMISSION FLOW
    if data in ["force_add_q", "add_more_q", "final_submit_task"]:
        if tg_id in user_state: user_state[tg_id]['waiting_btn'] = False 
        
        if data == "force_add_q":
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            temp = user_state[tg_id].pop('temp_hold', None)
            if temp: add_question_to_state(call.message.chat.id, tg_id, temp['q'], temp['p'])
            
        elif data == "add_more_q":
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg_box = bot.send_message(call.message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, handle_next_question)
            
        elif data == "final_submit_task":
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            state = user_state.get(tg_id, {})
            t_num = state.get('task_num')
            if not t_num: return
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                month_name = get_bd_time().strftime("%B")
                if 'single_sub' in state:
                    cursor.execute("INSERT INTO kbkh_submissions (telegram_id, task_num, content_text, photo_id) VALUES (%s, %s, %s, %s)", (tg_id, t_num, state['single_sub']['caption'], state['single_sub']['photo']))
                elif 'collected' in state:
                    full_content = json.dumps(state['collected'], ensure_ascii=False)
                    cursor.execute("INSERT INTO kbkh_submissions (telegram_id, task_num, content_text) VALUES (%s, %s, %s)", (tg_id, t_num, full_content))
                    for q in state['collected']: cursor.execute("INSERT INTO kbkh_question_bank (telegram_id, task_num, question_text, month) VALUES (%s, %s, %s, %s)", (tg_id, t_num, q['text'], month_name))
                cursor.execute("INSERT INTO kbkh_user_task_status (telegram_id, task_num, completed) VALUES (%s, %s, TRUE) ON CONFLICT (telegram_id, task_num) DO UPDATE SET completed = TRUE", (tg_id, t_num))
                conn.commit()
            finally: conn.close()
            user_state.pop(tg_id, None)
            bot.send_message(call.message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")
        return

    # 3. QnA SUBMISSION (MEMBER)
    if data == "qna_final_submit":
        state = user_state.get(tg_id)
        if not state or state.get('flow') != 'qna_preview': return
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            mod_id = get_least_loaded_qna_mod()
            q_json = json.dumps(state['q_dict'], ensure_ascii=False)
            a_json = json.dumps(state['a_dict'], ensure_ascii=False)
            cursor.execute("INSERT INTO kbkh_qna_submissions (telegram_id, q_dict, a_dict, assigned_grader) VALUES (%s, %s, %s, %s)", (tg_id, q_json, a_json, mod_id))
            if mod_id: cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (mod_id,))
            conn.commit()
            bot.send_message(call.message.chat.id, "Submitted successfully. Please wait for feedback. Thank you!❤️")
        finally: conn.close()
        user_state.pop(tg_id, None)
        return

    # 4. QnA MODERATOR ACTIONS
    if data == "qna_res_yes":
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("UPDATE kbkh_qna_moderators SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (tg_id,))
            cursor.execute("SELECT id FROM kbkh_qna_submissions WHERE assigned_grader = %s AND status = 'Pending'", (tg_id,))
            pending = cursor.fetchall()
            for p in pending:
                new_mod = get_least_loaded_qna_mod()
                cursor.execute("UPDATE kbkh_qna_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                if new_mod: cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
            conn.commit()
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            # Execute outer logic cleanly
            cursor.execute("SELECT fb_name FROM members WHERE telegram_id = %s AND status = 'Approved'", (tg_id,))
            user = cursor.fetchone()
            bot.send_message(call.message.chat.id, "You have successfully resigned!✅", reply_markup=member_main_menu() if user else ReplyKeyboardRemove())
        finally: conn.close()
        return

    if data.startswith("qna_tg_"):
        team = data.split("_")[2]
        if tg_id not in admin_state: admin_state[tg_id] = {}
        current = admin_state[tg_id].get('qna_exp_team')
        admin_state[tg_id]['qna_exp_team'] = None if current == team else team
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT s.telegram_id, m.fb_name, m.team_name, COUNT(s.id) as total FROM kbkh_qna_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.assigned_grader = %s AND s.status = 'Pending' GROUP BY s.telegram_id, m.fb_name, m.team_name", (tg_id,))
            records = cursor.fetchall()
            teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
            for r in records:
                if r['team_name'] in teams: teams[r['team_name']].append(r)
                
            markup = InlineKeyboardMarkup(row_width=1)
            exp_team = admin_state[tg_id]['qna_exp_team']
            for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
                if exp_team == t:
                    markup.add(InlineKeyboardButton(f"🔺--{t}--🔺", callback_data=f"qna_tg_{t}"))
                    for m in teams[t]: markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"qna_user_{m['telegram_id']}"))
                else: markup.add(InlineKeyboardButton(f"🔻--{t}--🔻", callback_data=f"qna_tg_{t}"))
            markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        finally: conn.close()
        return

    if data.startswith("qna_user_"):
        target_user = int(data.split("_")[2])
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM kbkh_qna_submissions WHERE assigned_grader = %s AND telegram_id = %s AND status = 'Pending' ORDER BY id ASC LIMIT 2", (tg_id, target_user))
            submissions = cursor.fetchall()
            if not submissions: bot.send_message(call.message.chat.id, "No pending QnA found for this user.")
            else:
                for sub in submissions:
                    q_dict = json.loads(sub['q_dict'])
                    a_dict = json.loads(sub['a_dict'])
                    markup = InlineKeyboardMarkup(row_width=7)
                    btns = [InlineKeyboardButton(str(i), callback_data=f"qm_sel_{sub['id']}_{i}") for i in range(1, 7)]
                    btns.append(InlineKeyboardButton("❌", callback_data=f"qm_sel_{sub['id']}_0"))
                    markup.add(*btns)
                    markup.row(InlineKeyboardButton("Submit&Feedback", callback_data=f"qm_subfb_{sub['id']}"), InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub['id']}"))
                    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
                    send_qna_preview(call.message.chat.id, q_dict, a_dict, markup)
        finally: conn.close()
        return

    if data.startswith("qm_"):
        if tg_id not in admin_state: admin_state[tg_id] = {}
        parts = data.split("_")
        action, sub_id = parts[1], int(parts[2])
        
        if action == "sel":
            mark = parts[3]
            admin_state[tg_id][f'qmark_{sub_id}'] = mark
            markup = InlineKeyboardMarkup(row_width=7)
            btns = [InlineKeyboardButton(f"{i}✅" if str(mark)==str(i) else str(i), callback_data=f"qm_sel_{sub_id}_{i}") for i in range(1, 7)]
            btns.append(InlineKeyboardButton("❌✅" if str(mark)=="0" else "❌", callback_data=f"qm_sel_{sub_id}_0"))
            markup.add(*btns)
            markup.row(InlineKeyboardButton("Submit&Feedback", callback_data=f"qm_subfb_{sub_id}"), InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub_id}"))
            markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
            
        elif action == "subfb":
            mark = admin_state[tg_id].get(f'qmark_{sub_id}')
            if not mark: return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, process_qna_feedback, sub_id)
            
        elif action == "sub":
            mark = admin_state[tg_id].get(f'qmark_{sub_id}')
            if not mark: return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            finalize_qna_grading(sub_id, mark, None, tg_id)
        return

    # 5. STATUS SELECTORS (My Task & Members)
    if data == "back_modst":
        markup = InlineKeyboardMarkup(row_width=3)
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        btns = [InlineKeyboardButton(m[:3], callback_data=f"modst_{m}") for m in months]
        markup.add(*btns)
        markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        try: bot.edit_message_text("🗓️Please Select Month:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return
        
    if data.startswith("myts_"):
        month = data.split("_")[1]
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM kbkh_task_records WHERE telegram_id = %s AND month = %s", (tg_id, month))
            rec = cursor.fetchone()
            tdone = rec['task_done'] if rec else 0
            ttot = rec['task_total'] if rec else 0
            qmark = rec['qna_mark'] if rec else 0
            text = f"🗓️ Month - {month}\n\nSpecial Task- {tdone}/{ttot}\nQnA Mark - {qmark}"
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_inline_cancel())
            except: pass
        finally: conn.close()
        return

    if data.startswith("modst_"):
        month = data.split("_")[1]
        if tg_id not in admin_state: admin_state[tg_id] = {}
        admin_state[tg_id]['modst_month'] = month
        admin_state[tg_id]['modst_exp'] = None 
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, month)
        return
        
    if data.startswith("modstuser_"):
        u_id = int(data.split("_")[1])
        if tg_id not in admin_state: admin_state[tg_id] = {}
        current = admin_state[tg_id].get('modst_exp')
        admin_state[tg_id]['modst_exp'] = None if current == u_id else u_id
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, admin_state[tg_id].get('modst_month'))
        return

    # 6. ADMIN MODERATOR ACTIONS
    if data.startswith("amod_") or data.startswith("amodblk_") or data.startswith("amodkck_"):
        if str(tg_id) != ADMIN_CHAT_ID: return
        if data == "amod_qna":
            if ADMIN_CHAT_ID not in admin_state: admin_state[ADMIN_CHAT_ID] = {}
            curr = admin_state[ADMIN_CHAT_ID].get('admin_mod_exp')
            admin_state[ADMIN_CHAT_ID]['admin_mod_exp'] = None if curr == 'qna' else 'qna'
            render_main_admin_mods(call.message.chat.id, call.message.message_id)
        elif data.startswith("amodblk_"):
            if ADMIN_CHAT_ID not in admin_state: admin_state[ADMIN_CHAT_ID] = {}
            admin_state[ADMIN_CHAT_ID]['mod_target'] = {'id': int(data.split("_")[1]), 'action': 'block'}
            bot.answer_callback_query(call.id, "Block selected. Press Submit.", show_alert=True)
        elif data.startswith("amodkck_"):
            if ADMIN_CHAT_ID not in admin_state: admin_state[ADMIN_CHAT_ID] = {}
            admin_state[ADMIN_CHAT_ID]['mod_target'] = {'id': int(data.split("_")[1]), 'action': 'kick'}
            bot.answer_callback_query(call.id, "Kick selected. Press Submit.", show_alert=True)
        elif data == "amod_sub":
            target = admin_state.get(ADMIN_CHAT_ID, {}).get('mod_target')
            if not target: return bot.answer_callback_query(call.id, "Select action first!", show_alert=True)
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                if target['action'] == 'block':
                    cursor.execute("UPDATE kbkh_qna_moderators SET is_blocked = TRUE WHERE telegram_id = %s", (target['id'],))
                elif target['action'] == 'kick':
                    cursor.execute("UPDATE kbkh_qna_moderators SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (target['id'],))
                    cursor.execute("SELECT id FROM kbkh_qna_submissions WHERE assigned_grader = %s AND status = 'Pending'", (target['id'],))
                    pending = cursor.fetchall()
                    for p in pending:
                        new_mod = get_least_loaded_qna_mod()
                        cursor.execute("UPDATE kbkh_qna_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                        if new_mod: cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                    try: bot.send_message(target['id'], "You are not registered!❌", reply_markup=ReplyKeyboardRemove())
                    except: pass
                conn.commit()
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                bot.send_message(call.message.chat.id, "Action executed successfully!✅")
            finally: conn.close()
            admin_state[ADMIN_CHAT_ID].pop('mod_target', None)
        return

    # 7. ADMIN TASK ASSIGN & ORGANIZE & REVIEW
    if data == "reset_task_yes":
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kbkh_user_task_status; DELETE FROM kbkh_active_assignments; DELETE FROM kbkh_submissions; DELETE FROM kbkh_question_bank;")
            conn.commit()
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, "All Data has been permanently reset!✅")
        finally: conn.close()
        return

    if data.startswith("ta_") or data.startswith("ti_") or data.startswith("ei_") or data.startswith("mi_") or data.startswith("adm_") or data.startswith("grd_") or data.startswith("gact_") or data.startswith("gfbk_") or data.startswith("gsub_"):
        if str(tg_id) != ADMIN_CHAT_ID: return
        
        if data == "ta_main":
            markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Add Task", callback_data="ta_add"), InlineKeyboardButton("Task List", callback_data="ta_list")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data == "ta_list":
            markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Organize Task", callback_data="ta_org"), InlineKeyboardButton("Assign Task", callback_data="ta_assign")).row(InlineKeyboardButton("Back", callback_data="ta_main"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data == "ta_add":
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(task_num) FROM kbkh_tasks")
                row = cursor.fetchone()
                next_t = (row[0] if row[0] is not None else 0) + 1
                if tg_id not in admin_state: admin_state[tg_id] = {}
                admin_state[tg_id]['t_num'] = next_t
                admin_state[tg_id]['clean_msgs'] = []
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                msg = bot.send_message(call.message.chat.id, f"Give the first message of the Task -{next_t}:", reply_markup=get_inline_cancel())
                admin_state[tg_id]['clean_msgs'].append(msg.message_id)
                bot.register_next_step_handler(msg, step_add_msg1)
            finally: conn.close()
        elif data.startswith("ta_end_"):
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            if 'clean_msgs' in admin_state.get(tg_id, {}): admin_state[tg_id]['clean_msgs'].append(call.message.message_id)
            finalize_task(tg_id, call.message.chat.id)
        elif data == "ta_org":
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg = bot.send_message(call.message.chat.id, "Please provide the list.\n(Example: 1,2,3)", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg, step_org_task)
        elif data == "ta_assign":
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT COUNT(*) FROM kbkh_active_assignments")
                if cursor.fetchone()['count'] > 0: return bot.answer_callback_query(call.id, "Already assigned a Task! Please stop it first in Triggered Task.", show_alert=True)
                if tg_id not in admin_state: admin_state[tg_id] = {}
                admin_state[tg_id]['assigning'] = {'selected': None}
                render_ta_assign_page(call.message.chat.id, call.message.message_id, tg_id)
            finally: conn.close()
        elif data.startswith("ta_asgsel_"):
            org_id = int(data.split("_")[2])
            curr_sel = admin_state.get(tg_id, {}).get('assigning', {}).get('selected')
            admin_state[tg_id]['assigning']['selected'] = None if curr_sel == org_id else org_id
            render_ta_assign_page(call.message.chat.id, call.message.message_id, tg_id)
        elif data == "ta_asgdel":
            selected_id = admin_state.get(tg_id, {}).get('assigning', {}).get('selected')
            if not selected_id: return
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM kbkh_organized_tasks WHERE id = %s", (selected_id,))
                conn.commit()
                admin_state[tg_id]['assigning']['selected'] = None
                render_ta_assign_page(call.message.chat.id, call.message.message_id, tg_id)
            finally: conn.close()
        elif data == "ta_asgsub":
            org_id = admin_state.get(tg_id, {}).get('assigning', {}).get('selected')
            if not org_id: return
            seq_str = next((o['sequence'] for o in admin_state[tg_id].get('assigning', {}).get('orgs', []) if o['id'] == org_id), None)
            if not seq_str: return
            tasks = seq_str.split(',')
            teams = ['Team Alpha', 'Team Beta', 'Team Gamma']
            next_midnight = datetime.combine(get_bd_time().date() + timedelta(days=1), datetime.min.time())
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                for i, t_num in enumerate(tasks):
                    if i < len(teams):
                        cursor.execute("DELETE FROM kbkh_active_assignments WHERE team_name = %s", (teams[i],))
                        cursor.execute("DELETE FROM kbkh_user_task_status WHERE task_num = %s AND telegram_id IN (SELECT telegram_id FROM members WHERE team_name = %s)", (int(t_num), teams[i]))
                        cursor.execute("DELETE FROM kbkh_submissions WHERE task_num = %s AND telegram_id IN (SELECT telegram_id FROM members WHERE team_name = %s)", (int(t_num), teams[i]))
                        cursor.execute("INSERT INTO kbkh_active_assignments (team_name, task_num, scheduled_for, is_started, current_msg) VALUES (%s, %s, %s, FALSE, 0)", (teams[i], int(t_num), next_midnight))
                conn.commit()
                admin_state[tg_id]['assigning']['selected'] = None
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                bot.send_message(call.message.chat.id, f"Task: {seq_str.replace(',',' ')} Assigned Successfully✅\nWill trigger at Midnight.")
            finally: conn.close()
        elif data == "ta_stop":
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM kbkh_active_assignments WHERE is_started = FALSE")
                conn.commit()
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                bot.send_message(call.message.chat.id, "Task Assign Cancelled Successfully✅")
            finally: conn.close()
        elif data == "ta_force_end":
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Yes", callback_data="ta_force_end_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
            bot.send_message(call.message.chat.id, "Are you sure you want to end the Task?", reply_markup=markup)
        elif data == "ta_force_end_yes":
            conn = get_db_connection()
            auto_end_users = []
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT team_name FROM kbkh_active_assignments WHERE is_started = TRUE")
                teams = cursor.fetchall()
                for t in teams:
                    cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s", (t['team_name'],))
                    for u in cursor.fetchall(): auto_end_users.append(u['telegram_id'])
                cursor.execute("DELETE FROM kbkh_active_assignments WHERE is_started = TRUE")
                conn.commit()
            finally: conn.close()
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, "Task Successfully end!✅")
            for uid in auto_end_users:
                try: bot.send_message(uid, "Task END!\nThank you dear member♥️")
                except: pass

        # ADMIN EDIT INSTRUCTIONS
        elif data == "ei_back":
            markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Task Instructions", callback_data="ei_task"), InlineKeyboardButton("QnA Instructions", callback_data="ei_qna")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data == "ei_task":
            markup = get_task_edit_keyboard(tg_id)
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data == "ei_qna":
            markup, text = get_qna_inst_keyboard(tg_id)
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data.startswith("mi_sel_"):
            sel_id = int(data.split("_")[2])
            if tg_id not in admin_state: admin_state[tg_id] = {}
            admin_state[tg_id]['edit_main'] = sel_id
            markup, text = get_qna_inst_keyboard(tg_id, sel_id)
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data.startswith("mi_view_"):
            i_id = int(data.split("_")[2])
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT instruction_text FROM kbkh_custom_instructions WHERE id = %s", (i_id,))
                inst = cursor.fetchone()
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Yes", callback_data=f"mi_yes_{i_id}"), InlineKeyboardButton("No", callback_data="cancel_action"))
                bot.send_message(call.message.chat.id, f"{inst['instruction_text']}\n\nWould you like to change anything here?", reply_markup=markup)
            finally: conn.close()
        elif data.startswith("mi_yes_"):
            sel_id = int(data.split("_")[2])
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg = bot.send_message(call.message.chat.id, f"Input the new message for Instruction {sel_id}:", reply_markup=get_inline_cancel())
            if tg_id not in admin_state: admin_state[tg_id] = {}
            admin_state[tg_id]['wait_mi'] = sel_id
            bot.register_next_step_handler(msg, step_update_qna_inst)
        elif data == "mi_click":
            sel_id = admin_state.get(tg_id, {}).get('edit_main')
            if not sel_id: return
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM kbkh_custom_instructions WHERE id = %s", (sel_id,))
                conn.commit()
                admin_state[tg_id]['edit_main'] = None
                markup, text = get_qna_inst_keyboard(tg_id)
                try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                except: pass
            finally: conn.close()
        elif data.startswith("ti_exp_"):
            t_num = int(data.split("_")[2])
            if tg_id not in admin_state: admin_state[tg_id] = {}
            current_exp = admin_state[tg_id].get('edit_task_exp')
            admin_state[tg_id]['edit_task_exp'] = t_num if current_exp != t_num else None
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(tg_id))
            except: pass
        elif data.startswith("ti_edit_"):
            parts = data.split("_")
            t_num, msg_idx = int(parts[2]), int(parts[3])
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(f"SELECT msg_{msg_idx} FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                msg_text = cursor.fetchone()[f'msg_{msg_idx}']
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Yes", callback_data=f"ti_yes_{t_num}_{msg_idx}"), InlineKeyboardButton("No", callback_data="cancel_action"))
                bot.send_message(call.message.chat.id, f"{msg_text}\n\nWould you like to change anything here?", reply_markup=markup)
            finally: conn.close()
        elif data.startswith("ti_yes_"):
            parts = data.split("_")
            t_num, msg_idx = int(parts[2]), int(parts[3])
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg = bot.send_message(call.message.chat.id, f"Input the new message for Task -{t_num} ;Message -{msg_idx}:", reply_markup=get_inline_cancel())
            if tg_id not in admin_state: admin_state[tg_id] = {}
            admin_state[tg_id]['wait_ti'] = {'t_num': t_num, 'msg_idx': msg_idx}
            bot.register_next_step_handler(msg, step_update_task_msg)
        elif data.startswith("ti_del_sel_"):
            t_num = int(data.split("_")[3])
            if tg_id not in admin_state: admin_state[tg_id] = {}
            admin_state[tg_id]['del_task'] = t_num
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(tg_id, t_num))
            except: pass
        elif data == "ti_del_sub":
            t_num = admin_state.get(tg_id, {}).get('del_task')
            if not t_num: return bot.send_message(call.message.chat.id, "Select one to delete!")
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("DELETE FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                cursor.execute("SELECT id, sequence FROM kbkh_organized_tasks")
                orgs = cursor.fetchall()
                for org in orgs:
                    if str(t_num) in org['sequence'].split(','):
                        cursor.execute("DELETE FROM kbkh_organized_tasks WHERE id = %s", (org['id'],))
                conn.commit()
                admin_state[tg_id]['del_task'] = None
                try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(tg_id))
                except: pass
                bot.answer_callback_query(call.id, "Task Deleted Successfully!", show_alert=True)
            finally: conn.close()

        # ADMIN TASK REVIEW
        elif data == "adm_back":
            markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp")).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            try: bot.edit_message_text("Task Menu:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        elif data in ["adm_tsub", "adm_tcomp"]:
            is_completed = (data == "adm_tcomp")
            if tg_id not in admin_state: admin_state[tg_id] = {}
            render_admin_submission_list(call.message.chat.id, call.message.message_id, is_completed)
        elif data.startswith("grd_"):
            sub_id = int(data.split("_")[1])
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
                sub = cursor.fetchone()
                if not sub: return
                if tg_id not in admin_state: admin_state[tg_id] = {}
                admin_state[tg_id]['grading_sub'] = sub_id
                admin_state[tg_id]['action'] = None
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                
                try:
                    items = json.loads(sub['content_text'])
                    for item in items:
                        if item.get('photo'): bot.send_photo(call.message.chat.id, item['photo'], caption=item.get('text', ''))
                        else: bot.send_message(call.message.chat.id, item.get('text', ''))
                except:
                    if sub['photo_id']: bot.send_photo(call.message.chat.id, sub['photo_id'], caption=sub['content_text'])
                    else: bot.send_message(call.message.chat.id, sub['content_text'])
                    
                info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}"
                markup = get_admin_grading_kb(sub_id)
                bot.send_message(call.message.chat.id, info_text, reply_markup=markup)
            finally: conn.close()
        elif data.startswith("gact_"):
            parts = data.split("_")
            sub_id, act = int(parts[1]), parts[2]
            if tg_id not in admin_state: admin_state[tg_id] = {}
            admin_state[tg_id]['action'] = act
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_grading_kb(sub_id, act))
            except: pass
        elif data.startswith("gfbk_"):
            sub_id = int(data.split("_")[1])
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, process_admin_feedback, sub_id)
        elif data.startswith("gsub_"):
            sub_id = int(data.split("_")[1])
            act = admin_state.get(tg_id, {}).get('action')
            feedback = admin_state.get(tg_id, {}).get('feedback')
            if not act: return bot.answer_callback_query(call.id, "Select Approve or Reject!", show_alert=True)
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            finalize_grading(sub_id, act, feedback, call.message.chat.id)
        return

# ==========================================
# 🟢 QnA MODERATOR SPECIFIC HELPER FUNCTIONS
# ==========================================
def process_qna_feedback(message, sub_id):
    mod_id = message.from_user.id
    if mod_id not in admin_state: admin_state[mod_id] = {}
    admin_state[mod_id][f'qfbk_{sub_id}'] = message.text
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_qna_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        q_dict = json.loads(sub['q_dict'])
        a_dict = json.loads(sub['a_dict'])
        
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        cap_extra = f"\n\n✔️Marks Obtained - {mark}\n◀️Feedback: {message.text}"
        a_dict['text'] = a_dict.get('text', '') + cap_extra
        send_qna_preview(message.chat.id, q_dict, a_dict, markup)
    finally: conn.close()

def finalize_qna_grading(sub_id, mark, feedback, mod_id):
    if not feedback and f'qfbk_{sub_id}' in admin_state.get(mod_id, {}):
        feedback = admin_state[mod_id][f'qfbk_{sub_id}']
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_qna_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        cursor.execute("UPDATE kbkh_qna_submissions SET status = 'Graded', mark = %s, feedback = %s WHERE id = %s", (int(mark), feedback, sub_id))
        cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = GREATEST(0, total_assigned - 1) WHERE telegram_id = %s", (mod_id,))
        
        month_name = (sub['created_at'] + timedelta(hours=6)).strftime("%B")
        
        if mark == "0":
            fixed_fb = "গ্রহণযোগ্য নয়!"
            add_mark = 0
        else:
            cursor.execute("SELECT instruction_text FROM kbkh_custom_instructions WHERE id = %s", (int(mark),))
            res = cursor.fetchone()
            fixed_fb = res['instruction_text'] if res else ""
            add_mark = int(mark)
            
        cursor.execute("INSERT INTO kbkh_task_records (telegram_id, month, qna_mark) VALUES (%s, %s, %s) ON CONFLICT (telegram_id, month) DO UPDATE SET qna_mark = kbkh_task_records.qna_mark + %s", (sub['telegram_id'], month_name, add_mark, add_mark))
        conn.commit()
        
        q_dict = json.loads(sub['q_dict'])
        a_dict = json.loads(sub['a_dict'])
        cap_extra = f"\n\n✔️Marks Obtained - {mark}\n[{fixed_fb}]"
        if feedback: cap_extra += f"\n\n◀️Feedback: {feedback}"
        a_dict['text'] = a_dict.get('text', '') + cap_extra
        try: send_qna_preview(sub['telegram_id'], q_dict, a_dict)
        except: pass
    finally: conn.close()
    
    if mod_id in admin_state:
        admin_state[mod_id].pop(f'qmark_{sub_id}', None)
        admin_state[mod_id].pop(f'qfbk_{sub_id}', None)

# ==========================================
# 🟢 ADMIN SPECIFIC HELPER FUNCTIONS
# ==========================================
def render_members_status_list(chat_id, message_id, mod_id, month):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, fb_name, team_name FROM members WHERE status = 'Approved' ORDER BY team_name, fb_name")
        members = cursor.fetchall()
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for m in members:
            if m['team_name'] in teams: teams[m['team_name']].append(m)
            
        expanded_u = admin_state.get(mod_id, {}).get('modst_exp')
        text = f"🗓️ Month - {month}\n\n"
        markup = InlineKeyboardMarkup(row_width=1)
        for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if not teams[t]: continue
            text += f"🔶--{t}--🔶\n"
            for m in teams[t]:
                if m['telegram_id'] == expanded_u:
                    cursor.execute("SELECT task_done, task_total, qna_mark FROM kbkh_task_records WHERE telegram_id = %s AND month = %s", (m['telegram_id'], month))
                    rec = cursor.fetchone()
                    tdone = rec['task_done'] if rec else 0
                    ttot = rec['task_total'] if rec else 0
                    qmark = rec['qna_mark'] if rec else 0
                    text += f"🔻{m['fb_name']}\nSpecial Task- {tdone}/{ttot}\nQnA Mark - {qmark}\n\n"
                    markup.add(InlineKeyboardButton(f"{m['fb_name']} 🔻", callback_data=f"modstuser_{m['telegram_id']}"))
                else:
                    text += f"🔺{m['fb_name']}\n"
                    markup.add(InlineKeyboardButton(f"{m['fb_name']} 🔺", callback_data=f"modstuser_{m['telegram_id']}"))
            text += "\n"
        markup.row(InlineKeyboardButton("Back", callback_data="back_modst"), InlineKeyboardButton("Close", callback_data="cancel_action"))
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception: pass
    finally: conn.close()

def render_ta_assign_page(chat_id, message_id, adm_id):
    state = admin_state.get(adm_id, {}).get('assigning', {})
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_organized_tasks ORDER BY id ASC")
        orgs = cursor.fetchall()
    finally: conn.close()
    state['orgs'] = orgs
    selected_id = state.get('selected')
    markup = InlineKeyboardMarkup(row_width=1)
    if not orgs: markup.add(InlineKeyboardButton("(No Tasks Organized)", callback_data="ignore"))
    else:
        for org in orgs:
            icon = "✅" if org['id'] == selected_id else "🔳"
            seq_display = org['sequence'].replace(',', '  ')
            markup.add(InlineKeyboardButton(f"Task {seq_display}  {icon}", callback_data=f"ta_asgsel_{org['id']}"))
    markup.row(InlineKeyboardButton("Submit", callback_data="ta_asgsub"), InlineKeyboardButton("Delete", callback_data="ta_asgdel"))
    markup.row(InlineKeyboardButton("Back", callback_data="ta_list"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    if message_id:
        try: bot.edit_message_text("Task Assign Menu:", chat_id, message_id, reply_markup=markup)
        except Exception: pass
    else: bot.send_message(chat_id, "Task Assign Menu:", reply_markup=markup)

def get_task_edit_keyboard(adm_id, sel_del_id=None):
    markup = InlineKeyboardMarkup()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT task_num, msg_1, msg_2, msg_3 FROM kbkh_tasks ORDER BY task_num")
        tasks = cursor.fetchall()
    finally: conn.close()
    exp = admin_state.get(adm_id, {}).get('edit_task_exp')
    if not tasks:
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        return markup
    for t in tasks:
        t_num = t['task_num']
        del_icon = "❌" if str(sel_del_id) == str(t_num) else "🔳"
        row = []
        if exp == t_num: row.append(InlineKeyboardButton(f"Task - {t_num} 🔻", callback_data=f"ti_exp_{t_num}"))
        else: row.append(InlineKeyboardButton(f"Task - {t_num} 🔺", callback_data=f"ti_exp_{t_num}"))
        row.append(InlineKeyboardButton(del_icon, callback_data=f"ti_del_sel_{t_num}"))
        markup.row(*row)
        if exp == t_num:
            btns = []
            if t['msg_1']: btns.append(InlineKeyboardButton("1", callback_data=f"ti_edit_{t_num}_1"))
            if t['msg_2']: btns.append(InlineKeyboardButton("2", callback_data=f"ti_edit_{t_num}_2"))
            if t['msg_3']: btns.append(InlineKeyboardButton("3", callback_data=f"ti_edit_{t_num}_3"))
            if btns: markup.row(*btns)
    if sel_del_id: markup.row(InlineKeyboardButton("Submit", callback_data="ti_del_sub"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

def render_main_admin_mods(chat_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, mod_name, team_name, total_assigned FROM kbkh_qna_moderators WHERE is_active = TRUE")
        mods = cursor.fetchall()
        markup = InlineKeyboardMarkup(row_width=1)
        exp_team = admin_state.get(ADMIN_CHAT_ID, {}).get('admin_mod_exp')
        if exp_team == 'qna':
            markup.add(InlineKeyboardButton("QnA Making Team 🔻", callback_data="amod_qna"))
            teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
            for m in mods:
                if m['team_name'] in teams: teams[m['team_name']].append(m)
            for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
                if teams[t]:
                    markup.add(InlineKeyboardButton(f"--{t}--", callback_data="ignore"))
                    for m in teams[t]:
                        btn_name = InlineKeyboardButton(f"{m['mod_name']} - {m['total_assigned']}", callback_data="ignore")
                        btn_blk = InlineKeyboardButton("⛔", callback_data=f"amodblk_{m['telegram_id']}")
                        btn_kck = InlineKeyboardButton("❌", callback_data=f"amodkck_{m['telegram_id']}")
                        markup.row(btn_name, btn_blk, btn_kck)
            markup.add(InlineKeyboardButton("Submit", callback_data="amod_sub"))
        else: markup.add(InlineKeyboardButton("QnA Making Team 🔺", callback_data="amod_qna"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if message_id:
            try: bot.edit_message_text("Admin Moderators Panel:", chat_id, message_id, reply_markup=markup)
            except: pass
        else: bot.send_message(chat_id, "Admin Moderators Panel:", reply_markup=markup)
    finally: conn.close()

def render_admin_submission_list(chat_id, message_id=None, is_completed=False):
    status_filter = 'Approved' if is_completed else 'Pending'
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.id, s.telegram_id, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.status = %s ORDER BY s.id ASC", (status_filter,))
        records = cursor.fetchall()
        if not records:
            msg = "No status found!" if is_completed else "No Pending Submissions found!"
            if message_id: 
                try: bot.edit_message_text(msg, chat_id, message_id, reply_markup=get_inline_cancel())
                except: pass
            else: bot.send_message(chat_id, msg, reply_markup=get_inline_cancel())
            return
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for r in records:
            t_name = r.get('team_name', 'Team Alpha')
            if t_name in teams: teams[t_name].append(r)
        markup = InlineKeyboardMarkup(row_width=1)
        for team in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if teams[team]: 
                markup.add(InlineKeyboardButton(f"-- {team} --", callback_data="ignore"))
                for m in teams[team]:
                    cb_data = "ignore" if is_completed else f"grd_{m['id']}"
                    markup.add(InlineKeyboardButton(f"{m['fb_name']}", callback_data=cb_data))
        markup.row(InlineKeyboardButton("Back", callback_data="adm_back"), InlineKeyboardButton("Close" if is_completed else "Cancel", callback_data="cancel_action"))
        text = "Task Completed List:" if is_completed else "Task Submitted List:"
        if message_id: 
            try: bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            except: pass
        else: bot.send_message(chat_id, text, reply_markup=markup)
    finally: conn.close()

def get_admin_grading_kb(sub_id, action=None):
    markup = InlineKeyboardMarkup(row_width=2)
    ap_btn = "Approve✅" if action == "approve" else "Approve"
    rj_btn = "Reject✅" if action == "reject" else "Reject"
    markup.row(InlineKeyboardButton(ap_btn, callback_data=f"gact_{sub_id}_approve"), InlineKeyboardButton(rj_btn, callback_data=f"gact_{sub_id}_reject"))
    markup.add(InlineKeyboardButton("- Feedback -", callback_data=f"gfbk_{sub_id}"))
    markup.row(InlineKeyboardButton("Submit", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

def process_admin_feedback(message, sub_id):
    if ADMIN_CHAT_ID not in admin_state: admin_state[ADMIN_CHAT_ID] = {}
    admin_state[ADMIN_CHAT_ID]['feedback'] = message.text
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
        sub = cursor.fetchone()
        info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}\n◀️Feedback: {message.text}"
        markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Send", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, info_text, reply_markup=markup)
    finally: conn.close()

def finalize_grading(sub_id, status_act, feedback, admin_chat_id):
    if ADMIN_CHAT_ID in admin_state:
        admin_state[ADMIN_CHAT_ID].pop('feedback', None) 
        admin_state[ADMIN_CHAT_ID].pop('action', None)
    notifications_to_send = []
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
        sub = cursor.fetchone()
        if not sub: return
        try:
            items = json.loads(sub['content_text'])
            cap = "\n\n".join([i['text'] for i in items])
        except: cap = sub['content_text']
        if status_act == "approve":
            cursor.execute("UPDATE kbkh_submissions SET status = 'Approved' WHERE id = %s", (sub_id,))
            user_msg = "Your task has been successfully reviewed and marked as completed!✅" + (f"\n◀️Feedback: {feedback}" if feedback else "")
            notifications_to_send.append({'tg_id': sub['telegram_id'], 'photo_id': sub['photo_id'], 'msg': user_msg})
            if sub['task_num'] == 3:
                fwd_cap = f"{cap}\nName: {sub['fb_name']}"
                notifications_to_send.append({'tg_id': PRIVATE_GROUP_ID, 'photo_id': sub['photo_id'], 'msg': fwd_cap})
        else:
            cursor.execute("DELETE FROM kbkh_submissions WHERE id = %s", (sub_id,))
            cursor.execute("UPDATE kbkh_user_task_status SET completed = FALSE WHERE telegram_id = %s AND task_num = %s", (sub['telegram_id'], sub['task_num']))
            user_msg = f"{cap[:50]}...\nTask Status: Failed❌\n" + (f"◀️Feedback: {feedback}" if feedback else "Please try again. If the issue persists, contact a senior team member for assistance.")
            notifications_to_send.append({'tg_id': sub['telegram_id'], 'photo_id': sub['photo_id'], 'msg': user_msg})
        conn.commit()
    finally: conn.close()
    
    for notif in notifications_to_send:
        try:
            if notif['photo_id']: bot.send_photo(notif['tg_id'], notif['photo_id'], caption=notif['msg'])
            else: bot.send_message(notif['tg_id'], notif['msg'])
        except: pass
    render_admin_submission_list(admin_chat_id, None, False)
    
    # 🟢 Auto-End Execution
    if status_act == "approve":
        conn = get_db_connection()
        auto_end_users = []
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (sub['team_name'],))
            total_m = cursor.fetchone()['count']
            cursor.execute("SELECT COUNT(DISTINCT s.telegram_id) FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE m.team_name = %s AND s.task_num = %s AND s.status = 'Approved'", (sub['team_name'], sub['task_num']))
            done_m = cursor.fetchone()['count']
            if total_m > 0 and done_m >= total_m:
                cursor.execute("DELETE FROM kbkh_active_assignments WHERE team_name = %s AND task_num = %s", (sub['team_name'], sub['task_num']))
                cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (sub['team_name'],))
                auto_end_users = [u['telegram_id'] for u in cursor.fetchall()]
                conn.commit()
        finally: conn.close()
        for uid in auto_end_users:
            try: bot.send_message(uid, "Task END!\nThank you dear member♥️")
            except: pass

def get_qna_inst_keyboard(adm_id, sel_id=None):
    markup = InlineKeyboardMarkup()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id FROM kbkh_custom_instructions ORDER BY id")
        insts = cursor.fetchall()
        if not insts:
            markup.row(InlineKeyboardButton("Back", callback_data="ei_back"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
            return markup, "No Instructions Available!"
        for inst in insts:
            i_id = inst['id']
            icon = "❌" if str(i_id) == str(sel_id) else "🔳"
            markup.row(InlineKeyboardButton(f"Instruction - {i_id}", callback_data=f"mi_view_{i_id}"), InlineKeyboardButton(icon, callback_data=f"mi_sel_{i_id}"))
        markup.row(InlineKeyboardButton("Submit", callback_data="mi_click"))
        markup.row(InlineKeyboardButton("Back", callback_data="ei_back"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        return markup, "QnA Instructions:"
    finally: conn.close()

def step_update_qna_inst(message):
    adm_id = message.from_user.id
    sel_id = admin_state.get(adm_id, {}).get('wait_mi')
    if not sel_id: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE kbkh_custom_instructions SET instruction_text = %s WHERE id = %s", (message.text, sel_id))
        conn.commit()
        bot.send_message(message.chat.id, "Successfully Replaced!✅")
    finally: conn.close()

def step_add_msg1(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state or 't_num' not in admin_state[adm_id]: return
    admin_state[adm_id]['msg_1'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    next_t = admin_state[adm_id]['t_num']
    markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"), InlineKeyboardButton("End", callback_data="ta_end_1"))
    msg = bot.send_message(message.chat.id, f"Give the second message of the Task -{next_t}:", reply_markup=markup)
    admin_state[adm_id]['clean_msgs'].append(msg.message_id)
    bot.register_next_step_handler(msg, step_add_msg2)

def step_add_msg2(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state or 't_num' not in admin_state[adm_id]: return
    admin_state[adm_id]['msg_2'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    next_t = admin_state[adm_id]['t_num']
    markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Cancel", callback_data="cancel_action"), InlineKeyboardButton("End", callback_data="ta_end_2"))
    msg = bot.send_message(message.chat.id, f"Give the Third message of the Task -{next_t}:", reply_markup=markup)
    admin_state[adm_id]['clean_msgs'].append(msg.message_id)
    bot.register_next_step_handler(msg, step_add_msg3)

def step_add_msg3(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state: return
    admin_state[adm_id]['msg_3'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    finalize_task(adm_id, message.chat.id)

def finalize_task(adm_id, chat_id):
    state = admin_state.get(adm_id, {})
    t_num = state.get('t_num')
    if not t_num: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kbkh_tasks (task_num, msg_1, msg_2, msg_3) VALUES (%s, %s, %s, %s) ON CONFLICT (task_num) DO UPDATE SET msg_1=EXCLUDED.msg_1, msg_2=EXCLUDED.msg_2, msg_3=EXCLUDED.msg_3", 
                       (t_num, state.get('msg_1'), state.get('msg_2'), state.get('msg_3')))
        conn.commit()
        for m_id in state.get('clean_msgs', []):
            try: bot.delete_message(chat_id, m_id)
            except: pass
        admin_state[adm_id].pop('t_num', None)
        admin_state[adm_id].pop('clean_msgs', None)
        bot.send_message(chat_id, f"All your messages for Task-{t_num} have been successfully added!✅")
    finally: conn.close()

def step_org_task(message):
    seq = message.text.replace(" ", "")
    tasks = seq.split(',')
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        success, failed = [], []
        for t in tasks:
            try:
                cursor.execute("SELECT id FROM kbkh_tasks WHERE task_num = %s", (int(t),))
                if cursor.fetchone(): success.append(t)
                else: failed.append(t)
            except: failed.append(t)
        if success and not failed:
            cursor.execute("INSERT INTO kbkh_organized_tasks (sequence) VALUES (%s)", (seq,))
            bot.send_message(message.chat.id, "Task list added successfully✅")
        else:
            msg = ""
            if success: msg += f"Task {','.join(success)} added successfully✅\n"
            if failed: msg += f"Task {','.join(failed)} doesn't exist❌"
            bot.send_message(message.chat.id, msg)
        conn.commit()
    finally: conn.close()

def step_update_task_msg(message):
    adm_id = message.from_user.id
    state = admin_state.get(adm_id, {}).get('wait_ti')
    if not state: return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE kbkh_tasks SET msg_{state['msg_idx']} = %s WHERE task_num = %s", (message.text, state['t_num']))
        conn.commit()
        bot.send_message(message.chat.id, "Successfully Replaced!✅")
    finally: conn.close()

# ==========================================
# ⏰ BACKGROUND AUTO-TIMER (Leak-Proof)
# ==========================================
def auto_task_timer():
    while True:
        try:
            actions_to_take = []
            conn = get_db_connection()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM kbkh_active_assignments")
                assignments = cursor.fetchall()
                now = get_bd_time()
                
                for assign in assignments:
                    team, t_num, msg_lvl, sched = assign['team_name'], assign['task_num'], assign['current_msg'], assign['scheduled_for']
                    is_st = assign['is_started']
                    
                    if not is_st and now >= sched:
                        cursor.execute("UPDATE kbkh_active_assignments SET is_started = TRUE, current_msg = 1 WHERE id = %s", (assign['id'],))
                        cursor.execute("SELECT msg_1 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                        task_msgs = cursor.fetchone()
                        if task_msgs and task_msgs['msg_1']:
                            cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                            users = [u['telegram_id'] for u in cursor.fetchall()]
                            actions_to_take.append({'users': users, 'msg': task_msgs['msg_1']})
                        continue
                    
                    if not is_st: continue 
                    
                    cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                    total_members = cursor.fetchone()['count']
                    cursor.execute("SELECT COUNT(DISTINCT telegram_id) FROM kbkh_submissions WHERE team_name = %s AND task_num = %s AND status = 'Approved'", (team, t_num))
                    done_members = cursor.fetchone()['count']
                    
                    diff_hours = (now - sched).total_seconds() / 3600
                    
                    if (total_members > 0 and done_members >= total_members) or (diff_hours >= 72):
                        cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                        users = [u['telegram_id'] for u in cursor.fetchall()]
                        actions_to_take.append({'users': users, 'msg': "Task END!\nThank you dear member♥️"})
                        cursor.execute("DELETE FROM kbkh_active_assignments WHERE id = %s", (assign['id'],))
                        continue

                    cursor.execute("SELECT msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                    t_msgs = cursor.fetchone()
                    
                    cursor.execute("""
                        SELECT m.telegram_id FROM members m 
                        LEFT JOIN kbkh_user_task_status uts ON m.telegram_id = uts.telegram_id AND uts.task_num = %s
                        WHERE m.team_name = %s AND m.status = 'Approved' AND (uts.completed IS NULL OR uts.completed = FALSE)
                    """, (t_num, team))
                    pending_users = [u['telegram_id'] for u in cursor.fetchall()]

                    if diff_hours >= 24 and msg_lvl == 1 and t_msgs and t_msgs['msg_2']:
                        cursor.execute("UPDATE kbkh_active_assignments SET current_msg = 2 WHERE id = %s", (assign['id'],))
                        actions_to_take.append({'users': pending_users, 'msg': t_msgs['msg_2']})
                        
                    elif diff_hours >= 48 and msg_lvl == 2 and t_msgs and t_msgs['msg_3']:
                        cursor.execute("UPDATE kbkh_active_assignments SET current_msg = 3 WHERE id = %s", (assign['id'],))
                        actions_to_take.append({'users': pending_users, 'msg': t_msgs['msg_3']})
                        
                conn.commit()
            finally: conn.close()
            
            # Execute Network calls OUTSIDE the DB block to prevent DB jam!
            for action in actions_to_take:
                for uid in action['users']:
                    try: bot.send_message(uid, action['msg'])
                    except: pass
                    
        except Exception as e: print("Timer Error:", e)
        time.sleep(60)

# ==========================================
# 🚧 COMING SOON
# ==========================================
@bot.message_handler(func=lambda msg: msg.text in ["Submit Article", "Pending Articles"])
def coming_soon(message):
    bot.send_message(message.chat.id, "⏳ This feature is Coming Soon!")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_task_timer, daemon=True).start()
    print("🤖 KBKh Task Bot is Fast, Secure, and Fully Restored...")
    try: bot.remove_webhook(); time.sleep(2)
    except: pass
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(e); time.sleep(5)
