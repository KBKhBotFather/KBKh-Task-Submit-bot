import os
import re
import threading
import time
import json
from datetime import datetime, timedelta
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardRemove
)
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask

# ==========================================
# ⚙️ CONFIGURATION & ENVIRONMENT
# ==========================================
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "8868042763:AAHHKMQCQ8yFrF6OkrywTNoV4urwWFUdWys").strip()
DB_URI = (os.environ.get("DATABASE_URL") or "postgresql://postgres.knktfswiljvqttbnlufg:%23%23RoKy5502%23%23@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres").strip()
ADMIN_CHAT_ID = (os.environ.get("ADMIN_ID") or "8383532004").strip()
PRIVATE_GROUP_ID = -1004465038452

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)
app = Flask(__name__)

@app.route('/')
def home():
    return "KBKh Task Bot (5 Doors) is Alive & Perfect!", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

def get_bd_time():
    return datetime.utcnow() + timedelta(hours=6)

def get_db_connection():
    uri = DB_URI
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(uri, connect_timeout=10)

# ==========================================
# 🛠️ DATABASE SETUP (Fully Isolated)
# ==========================================
def init_db():
    conn = get_db_connection()
    try:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kbkh_active_assignments (
                id SERIAL PRIMARY KEY, team_name TEXT, task_num INT, 
                scheduled_for TIMESTAMP, is_started BOOLEAN DEFAULT FALSE, current_msg INT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS kbkh_submissions (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, content_type TEXT, 
                content_text TEXT, photo_id TEXT, status TEXT DEFAULT 'Pending', 
                feedback TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS kbkh_tasks (
                id SERIAL PRIMARY KEY, task_num INT UNIQUE, msg_1 TEXT, msg_2 TEXT, msg_3 TEXT
            );
            CREATE TABLE IF NOT EXISTS kbkh_organized_tasks (
                id SERIAL PRIMARY KEY, sequence TEXT
            );
            CREATE TABLE IF NOT EXISTS kbkh_question_bank (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, question_text TEXT, month TEXT
            );
            CREATE TABLE IF NOT EXISTS kbkh_user_task_status (
                telegram_id BIGINT, task_num INT, completed BOOLEAN DEFAULT FALSE, UNIQUE(telegram_id, task_num)
            );
            CREATE TABLE IF NOT EXISTS kbkh_qna_moderators (
                telegram_id BIGINT PRIMARY KEY, mod_name TEXT, team_name TEXT, 
                is_active BOOLEAN DEFAULT TRUE, total_assigned INT DEFAULT 0, 
                resign_count INT DEFAULT 0, is_blocked BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS kbkh_qna_submissions (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, q_dict TEXT, a_dict TEXT, 
                status TEXT DEFAULT 'Pending', assigned_grader BIGINT, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, feedback TEXT, mark INT
            );
            CREATE TABLE IF NOT EXISTS kbkh_task_records (
                telegram_id BIGINT, month TEXT, task_done INT DEFAULT 0, 
                task_total INT DEFAULT 0, qna_mark INT DEFAULT 0, UNIQUE(telegram_id, month)
            );
            CREATE TABLE IF NOT EXISTS kbkh_custom_instructions (
                id INT PRIMARY KEY, instruction_text TEXT
            );
            CREATE TABLE IF NOT EXISTS kbkh_publisher_moderators (
                telegram_id BIGINT PRIMARY KEY, mod_name TEXT, 
                is_active BOOLEAN DEFAULT TRUE, total_assigned INT DEFAULT 0, 
                resign_count INT DEFAULT 0, is_blocked BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS kbkh_article_submissions (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, article_type TEXT, 
                content_text TEXT, photo_id TEXT, status TEXT DEFAULT 'Pending', 
                assigned_grader BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                feedback TEXT, mark INT
            );
            CREATE TABLE IF NOT EXISTS kbkh_writers (
                telegram_id BIGINT PRIMARY KEY, short_name TEXT, full_name TEXT, 
                status TEXT DEFAULT 'Pending', is_blocked BOOLEAN DEFAULT FALSE
            );
        """)
        
        try: cursor.execute("ALTER TABLE kbkh_task_records ADD COLUMN article_mark INT DEFAULT 0;")
        except Exception: pass 
            
        default_inst = {
            1: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!", 
            2: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!",
            3: "উত্তরের মান উন্নত করা প্রয়োজন!", 
            4: "মোটামুটি ভালো হয়েছে। আরও ভালো করার চেষ্টা করতে হবে।",
            5: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।", 
            6: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।"
        }
        for k, v in default_inst.items():
            try: cursor.execute("INSERT INTO kbkh_custom_instructions (id, instruction_text) VALUES (%s, %s) ON CONFLICT DO NOTHING", (k, v))
            except Exception: pass
                
    except Exception as e:
        print(f"DB Init Error: {e}")
    finally:
        conn.close()

init_db()
user_state = {}
admin_state = {}

# ==========================================
# 🎹 KEYBOARDS
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

def qna_marking_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Pending QnA"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def article_publish_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Pending Articles"), KeyboardButton("On Hold"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def writer_main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Submit Article"), KeyboardButton("Pending Article"))
    return markup

def secondary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, is_persistent=True)
    markup.row(KeyboardButton("KBKh Team"), KeyboardButton("BKLn Team"))
    return markup

def get_inline_cancel():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================
def check_member_registration(tg_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT fb_name, team_name, status FROM members WHERE telegram_id = %s AND status = 'Approved' AND is_blocked = FALSE AND is_removed = FALSE", (tg_id,))
        return cursor.fetchone()
    finally:
        conn.close()

def get_least_loaded_qna_mod():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id FROM kbkh_qna_moderators WHERE is_active = TRUE AND is_blocked = FALSE ORDER BY total_assigned ASC, telegram_id ASC LIMIT 1")
        mod = cursor.fetchone()
        return mod['telegram_id'] if mod else None
    finally:
        conn.close()

def get_least_loaded_pub_mod():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id FROM kbkh_publisher_moderators WHERE is_active = TRUE AND is_blocked = FALSE ORDER BY total_assigned ASC, telegram_id ASC LIMIT 1")
        mod = cursor.fetchone()
        return mod['telegram_id'] if mod else None
    finally:
        conn.close()

# ==========================================
# 🚪 MULTI-DOOR LOGIN SYSTEM
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
            bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are back in QnA Marking Team!", reply_markup=qna_marking_menu())
            return
        elif mod and mod['is_blocked']:
            bot.send_message(message.chat.id, "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
            return
            
        cursor.execute("SELECT is_active, is_blocked FROM kbkh_publisher_moderators WHERE telegram_id = %s", (tg_id,))
        pub = cursor.fetchone()
        if pub and pub['is_active'] and not pub['is_blocked']:
            bot.send_message(message.chat.id, "Welcome Sir!❤️\nYou are back in the Article Publish Team!", reply_markup=article_publish_menu())
            return
        elif pub and pub['is_blocked']:
            bot.send_message(message.chat.id, "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
            return
            
        cursor.execute("SELECT status, is_blocked FROM kbkh_writers WHERE telegram_id = %s", (tg_id,))
        writer = cursor.fetchone()
        if writer:
            if writer['is_blocked']:
                bot.send_message(message.chat.id, "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
            elif writer['status'] == 'Approved':
                bot.send_message(message.chat.id, "Welcome back!❤️", reply_markup=writer_main_menu())
            else:
                markup = ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("Refresh🔄"))
                bot.send_message(message.chat.id, "Please wait for admin approval!", reply_markup=markup)
            return
    finally:
        conn.close()

    user = check_member_registration(tg_id)
    if user:
        bot.send_message(message.chat.id, f"Welcome to KBKh Bot Ecosystem, {user['fb_name']}!\nYou are in {user['team_name']}.", reply_markup=member_main_menu())
    else:
        bot.send_message(message.chat.id, "You are not registered yet❌\nPlease register from the Registration Bot first.", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(commands=['start_task'])
def trigger_task_now(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        return
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        past_time = get_bd_time() - timedelta(minutes=2)
        cursor.execute("UPDATE kbkh_active_assignments SET scheduled_for = %s WHERE is_started = FALSE", (past_time,))
        conn.commit()
        bot.send_message(message.chat.id, "Cheat Code Activated! 🚀\n\nAny pending assigned task will trigger within the next 60 seconds.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Cheat Code Error: {e}")
    finally:
        conn.close()

@bot.message_handler(func=lambda msg: msg.text in ["QnAKEY22", "PublisherKEY22", "ADMINKEY22", "WriterKEY22"])
def handle_secret_keys(message):
    tg_id = message.from_user.id
    user_state[tg_id] = {'login_flow': message.text}
    
    markup = get_inline_cancel()
    if message.text == "WriterKEY22":
        msg_box = bot.send_message(message.chat.id, "Please enter your short name(In English):", reply_markup=markup)
    else:
        msg_box = bot.send_message(message.chat.id, "Please enter your full name:", reply_markup=markup)
        
    user_state[tg_id]['prompt_msg_id'] = msg_box.message_id
    bot.register_next_step_handler(msg_box, process_door_login)

def process_door_login(message):
    tg_id = message.from_user.id
    if tg_id not in user_state or 'login_flow' not in user_state[tg_id]:
        return
        
    key = user_state[tg_id]['login_flow']
    user_state[tg_id]['mod_name'] = message.text.strip()
    
    prompt_msg_id = user_state[tg_id].get('prompt_msg_id')
    if prompt_msg_id:
        try: bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    
    if key == "QnAKEY22":
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(InlineKeyboardButton("Alpha", callback_data="qteam_Team Alpha"), InlineKeyboardButton("Beta", callback_data="qteam_Team Beta"), InlineKeyboardButton("Gamma", callback_data="qteam_Team Gamma"))
        bot.send_message(message.chat.id, "Please Select Your Team:", reply_markup=markup)
        
    elif key == "PublisherKEY22":
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO kbkh_publisher_moderators (telegram_id, mod_name, is_active) 
                VALUES (%s, %s, TRUE) 
                ON CONFLICT (telegram_id) DO UPDATE SET is_active = TRUE, mod_name = %s
            """, (tg_id, user_state[tg_id]['mod_name'], user_state[tg_id]['mod_name']))
            conn.commit()
            bot.send_message(message.chat.id, "Welcome Sir!❤️", reply_markup=article_publish_menu())
        finally:
            conn.close()
        user_state.pop(tg_id, None)
        
    elif key == "ADMINKEY22":
        bot.send_message(message.chat.id, "Welcome Sir!❤️", reply_markup=secondary_admin_menu())
        user_state.pop(tg_id, None)
        
    elif key == "WriterKEY22":
        msg_box = bot.send_message(message.chat.id, "Please enter your full name(In English):", reply_markup=get_inline_cancel())
        user_state[tg_id]['prompt_msg_id'] = msg_box.message_id
        bot.register_next_step_handler(msg_box, finalize_writer_login)

def finalize_writer_login(message):
    tg_id = message.from_user.id
    if tg_id not in user_state or 'login_flow' not in user_state[tg_id]:
        return
        
    prompt_msg_id = user_state[tg_id].get('prompt_msg_id')
    if prompt_msg_id:
        try: bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
        
    full_name = message.text.strip()
    short_name = user_state[tg_id]['mod_name']
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO kbkh_writers (telegram_id, short_name, full_name, status) 
            VALUES (%s, %s, %s, 'Pending') 
            ON CONFLICT (telegram_id) DO UPDATE SET short_name = %s, full_name = %s, status = 'Pending'
        """, (tg_id, short_name, full_name, short_name, full_name))
        conn.commit()
        
        markup = ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("Refresh🔄"))
        bot.send_message(message.chat.id, "Thank you!❤️\nPlease wait for admin approval.", reply_markup=markup)
    finally:
        conn.close()
    user_state.pop(tg_id, None)

@bot.message_handler(func=lambda msg: msg.text == "Refresh🔄")
def check_writer_status(message):
    tg_id = message.from_user.id
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT status FROM kbkh_writers WHERE telegram_id = %s", (tg_id,))
        writer = cursor.fetchone()
        if writer and writer['status'] == 'Approved':
            bot.send_message(message.chat.id, "Welcome!❤️", reply_markup=writer_main_menu())
        else:
            bot.send_message(message.chat.id, "Please wait for admin approval!")
    finally:
        conn.close()

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
        cursor.execute("""
            INSERT INTO kbkh_qna_moderators (telegram_id, mod_name, team_name, is_active) 
            VALUES (%s, %s, %s, TRUE) 
            ON CONFLICT (telegram_id) DO UPDATE SET is_active = TRUE, mod_name = %s, team_name = %s
        """, (tg_id, name, team, name, team))
        conn.commit()
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        bot.send_message(call.message.chat.id, "Welcome Sir❤️\nYou are now in QnA Marking Team!", reply_markup=qna_marking_menu())
    finally:
        conn.close()
    user_state.pop(tg_id, None)

# ==========================================
# 🟢 COMBINED TASK HANDLER
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Task")
def handle_task_routing(message):
    tg_id = message.from_user.id
    
    if str(tg_id) == ADMIN_CHAT_ID:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
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
                if sub_status and sub_status['status'] == 'Pending':
                    bot.send_message(message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")
                else:
                    bot.send_message(message.chat.id, "Your task has been successfully reviewed and marked as completed!✅")
            else:
                cursor.execute("SELECT msg_1, msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (assign['task_num'],))
                t_data = cursor.fetchone()
                msgs = []
                if t_data and t_data['msg_1'] and assign['current_msg'] >= 1: msgs.append(t_data['msg_1'])
                if t_data and t_data['msg_2'] and assign['current_msg'] >= 2: msgs.append(t_data['msg_2'])
                if t_data and t_data['msg_3'] and assign['current_msg'] >= 3: msgs.append(t_data['msg_3'])
                if msgs: bot.send_message(message.chat.id, "\n\n".join(msgs))
                else: bot.send_message(message.chat.id, "Task started, please wait for instructions.")
    finally:
        conn.close()

# ==========================================
# 🟢 ADMIN ONLY MENUS
# ==========================================
@bot.message_handler(func=lambda msg: msg.text in ["Task Assign", "Triggered Task", "Reset Task Data", "Edit Instructions"])
def admin_management_buttons(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
        
    text = message.text
    if text == "Task Assign":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Add Task", callback_data="ta_add"), InlineKeyboardButton("Task List", callback_data="ta_list"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Task Assign Menu:", reply_markup=markup)
        
    elif text == "Triggered Task":
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT a.team_name, a.task_num, a.is_started, a.scheduled_for 
                FROM kbkh_active_assignments a
                WHERE EXISTS (SELECT 1 FROM members m WHERE m.team_name = a.team_name)
                ORDER BY a.id ASC
            """)
            assigns = cursor.fetchall()
            
            if not assigns:
                bot.send_message(message.chat.id, "No Task Triggered!")
            else:
                is_st = any(a['is_started'] for a in assigns)
                display_teams = []
                task_start = None
                duration_hours = 24
                
                for a in assigns:
                    if task_start is None or a['scheduled_for'] < task_start:
                        task_start = a['scheduled_for']
                        
                    team = a['team_name']
                    t_num = a['task_num']
                    
                    cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                    total_members = cursor.fetchone()['count']
                    
                    cursor.execute("SELECT COUNT(DISTINCT s.telegram_id) FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE m.team_name = %s AND s.task_num = %s AND s.status = 'Approved'", (team, t_num))
                    done_members = cursor.fetchone()['count']
                    
                    if total_members > 0 and done_members < total_members:
                        display_teams.append(f"{team} - [Task-{t_num}]")
                        
                    cursor.execute("SELECT msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                    t_msgs_check = cursor.fetchone()
                    if t_msgs_check:
                        if t_msgs_check['msg_3']: duration_hours = max(duration_hours, 72)
                        elif t_msgs_check['msg_2']: duration_hours = max(duration_hours, 48)
                            
                if not display_teams:
                    msg_text = "All teams have successfully completed their tasks! 🟢\nWaiting for background auto-end..."
                else:
                    msg_text = "\n".join(display_teams)
                    msg_text += f"\n\nTask Status: {'Started!🟢' if is_st else 'Not Assigned yet!🔴'}"
                    
                    if task_start:
                        end_date = task_start + timedelta(hours=duration_hours)
                        def fmt_dt(dt):
                            hour = dt.hour % 12
                            if hour == 0: hour = 12
                            ampm = "A.M" if dt.hour < 12 else "P.M"
                            return f"{dt.day}{dt.strftime('%B')} - {hour:02d}:{dt.strftime('%M')} {ampm}"
                        msg_text += f"\nTask Start Date: {fmt_dt(task_start)}"
                        msg_text += f"\nTask End Date: {fmt_dt(end_date)}"
                
                markup = InlineKeyboardMarkup(row_width=2)
                if not is_st: markup.add(InlineKeyboardButton("Stop Task", callback_data="ta_stop"))
                else: markup.add(InlineKeyboardButton("End", callback_data="ta_force_end"))
                markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
                bot.send_message(message.chat.id, msg_text, reply_markup=markup)
        finally:
            conn.close()
            
    elif text == "Reset Task Data":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Yes", callback_data="reset_task_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Are you sure you want to reset all Task Data?", reply_markup=markup)
        
    elif text == "Edit Instructions":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Task Instructions", callback_data="ei_task"), InlineKeyboardButton("QnA Instructions", callback_data="ei_qna"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Edit Instructions:", reply_markup=markup)

# ==========================================
# 🟢 SUBMIT QnA FLOW (General Members)
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Submit QnA")
def start_qna_submit(message):
    tg_id = message.from_user.id
    user = check_member_registration(tg_id)
    if not user: return
        
    user_state[tg_id] = {'flow': 'wait_q', 'q_dict': None, 'a_dict': None}
    msg = bot.send_message(message.chat.id, "Please submit the question:", reply_markup=get_inline_cancel())
    user_state[tg_id]['q_msg_id'] = msg.message_id

def send_qna_preview(chat_id, q_dict, a_dict, markup=None):
    q_txt = q_dict.get('text', '')
    q_pic = q_dict.get('photo')
    a_txt = a_dict.get('text', '')
    a_pic = a_dict.get('photo')
    
    combined_text = f"{q_txt}\n\nAnswer: {a_txt}"
    ans_text = f"Answer: {a_txt}"
    
    if q_pic and not a_pic: 
        if len(combined_text) <= 1024: bot.send_photo(chat_id, q_pic, caption=combined_text, reply_markup=markup)
        else:
            bot.send_photo(chat_id, q_pic)
            bot.send_message(chat_id, combined_text, reply_markup=markup)
    elif not q_pic and a_pic: 
        if len(combined_text) <= 1024: bot.send_photo(chat_id, a_pic, caption=combined_text, reply_markup=markup)
        else:
            bot.send_photo(chat_id, a_pic)
            bot.send_message(chat_id, combined_text, reply_markup=markup)
    elif q_pic and a_pic:
        if len(q_txt) <= 1024: bot.send_photo(chat_id, q_pic, caption=q_txt)
        else:
            bot.send_photo(chat_id, q_pic)
            bot.send_message(chat_id, q_txt)
            
        if len(ans_text) <= 1024: bot.send_photo(chat_id, a_pic, caption=ans_text, reply_markup=markup)
        else:
            bot.send_photo(chat_id, a_pic)
            bot.send_message(chat_id, ans_text, reply_markup=markup)
    else:
        bot.send_message(chat_id, combined_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "qna_final_submit")
def process_qna_submit(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
        
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
    finally:
        conn.close()
    user_state.pop(tg_id, None)

# ==========================================
# 🟢 QnA MARKING TEAM (Pending, Grading, Resign)
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Resign⚠️")
def handle_qna_resign(message):
    tg_id = message.from_user.id
    markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("Yes", callback_data="qna_res_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "⚠️Are you sure you want to resign?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "qna_res_yes")
def confirm_qna_resign(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT is_active FROM kbkh_publisher_moderators WHERE telegram_id = %s AND is_active = TRUE", (tg_id,))
        is_active_pub = cursor.fetchone()
        
        cursor.execute("SELECT is_active FROM kbkh_qna_moderators WHERE telegram_id = %s AND is_active = TRUE", (tg_id,))
        is_active_qna = cursor.fetchone()
        
        if is_active_pub:
            cursor.execute("UPDATE kbkh_publisher_moderators SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (tg_id,))
            cursor.execute("SELECT id FROM kbkh_article_submissions WHERE assigned_grader = %s AND status = 'Pending'", (tg_id,))
            for p in cursor.fetchall():
                new_mod = get_least_loaded_pub_mod()
                cursor.execute("UPDATE kbkh_article_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                if new_mod: cursor.execute("UPDATE kbkh_publisher_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                
        if is_active_qna:
            cursor.execute("UPDATE kbkh_qna_moderators SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (tg_id,))
            cursor.execute("SELECT id FROM kbkh_qna_submissions WHERE assigned_grader = %s AND status = 'Pending'", (tg_id,))
            for p in cursor.fetchall():
                new_mod = get_least_loaded_qna_mod()
                cursor.execute("UPDATE kbkh_qna_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                if new_mod: cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                
        conn.commit()
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        
        if check_member_registration(tg_id):
            bot.send_message(call.message.chat.id, "You have successfully resigned!✅", reply_markup=member_main_menu())
        else:
            bot.send_message(call.message.chat.id, "You have successfully resigned!✅", reply_markup=ReplyKeyboardRemove())
    finally:
        conn.close()

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
            FROM kbkh_qna_submissions s JOIN members m ON s.telegram_id = m.telegram_id 
            WHERE s.assigned_grader = %s AND s.status = 'Pending' 
            GROUP BY s.telegram_id, m.fb_name, m.team_name
        """, (tg_id,))
        records = cursor.fetchall()
        
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for r in records:
            if r['team_name'] in teams: teams[r['team_name']].append(r)
            
        markup = InlineKeyboardMarkup(row_width=1)
        for team in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            markup.add(InlineKeyboardButton(f"[--{team}--]", callback_data="ignore"))
            if teams[team]:
                for m in teams[team]: markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"qna_user_{m['telegram_id']}"))
                
        markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Pending QnA List:", reply_markup=markup)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("qna_user_"))
def fetch_user_qna(call):
    mod_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    target_user = int(call.data.split("_")[2])
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_qna_submissions WHERE assigned_grader = %s AND telegram_id = %s AND status = 'Pending' ORDER BY id ASC LIMIT 2", (mod_id, target_user))
        submissions = cursor.fetchall()
        if not submissions:
            bot.send_message(call.message.chat.id, "No pending QnA found for this user.")
            return
        for sub in submissions:
            q_dict = json.loads(sub['q_dict'])
            a_dict = json.loads(sub['a_dict'])
            send_qna_preview(call.message.chat.id, q_dict, a_dict, get_qna_grading_kb(sub['id']))
    finally:
        conn.close()

def get_qna_grading_kb(sub_id, mark=None):
    markup = InlineKeyboardMarkup(row_width=7)
    btns = []
    for i in range(1, 7): btns.append(InlineKeyboardButton(f"{i}✅" if str(mark)==str(i) else str(i), callback_data=f"qm_sel_{sub_id}_{i}"))
    btns.append(InlineKeyboardButton("❌✅" if str(mark)=="0" else "❌", callback_data=f"qm_sel_{sub_id}_0"))
    markup.add(*btns)
    markup.row(InlineKeyboardButton("Submit&Feedback", callback_data=f"qm_subfb_{sub_id}"), InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub_id}"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("qm_sel_") or call.data.startswith("qm_sub_") or call.data.startswith("qm_subfb_"))
def qna_grading_actions(call):
    mod_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    if mod_id not in admin_state: admin_state[mod_id] = {}
        
    parts = call.data.split("_")
    action, sub_id = parts[1], int(parts[2])
    
    if action == "sel":
        mark = parts[3]
        admin_state[mod_id][f'qmark_{sub_id}'] = mark
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_qna_grading_kb(sub_id, mark))
        except: pass
        
    elif action == "subfb":
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        if not mark: return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, process_qna_feedback, sub_id)
        
    elif action == "sub":
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        if not mark: return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        finalize_qna_grading(sub_id, mark, None, mod_id)

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
        a_dict['text'] = a_dict.get('text', '') + f"\n\n✔️Marks Obtained - {mark}\n◀️Feedback: {message.text}"
        send_qna_preview(message.chat.id, q_dict, a_dict, markup)
    finally:
        conn.close()

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
            fixed_fb, add_mark = "গ্রহণযোগ্য নয়!", 0
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
    finally:
        conn.close()
    
    if mod_id in admin_state:
        admin_state[mod_id].pop(f'qmark_{sub_id}', None)
        admin_state[mod_id].pop(f'qfbk_{sub_id}', None)

# ==========================================
# 🟢 SUBMIT ARTICLE & PUBLISHER TEAM FLOW
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Submit Article")
def submit_article_start(message):
    tg_id = message.from_user.id
    conn = get_db_connection()
    is_writer = False
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT status FROM kbkh_writers WHERE telegram_id = %s", (tg_id,))
        res = cursor.fetchone()
        if res and res['status'] == 'Approved': is_writer = True
    finally:
        conn.close()
        
    if not is_writer and not check_member_registration(tg_id): return
        
    if is_writer:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.row(InlineKeyboardButton("Website", callback_data="art_sel_web"), InlineKeyboardButton("BigyanDiary(Txt+Img)", callback_data="art_sel_grp_b"))
        markup.row(InlineKeyboardButton("BigyanDiary(Only Txt)", callback_data="art_sel_txt"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Choose category:", reply_markup=markup)
    else:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Website", callback_data="art_sel_web"), InlineKeyboardButton("Group's", callback_data="art_sel_grp"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Choose category:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("art_sel_"))
def article_platform_selection(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
        
    if call.data == "art_sel_web":
        msg = bot.send_message(call.message.chat.id, "Please submit your article(GOOGLE DOCS LINK):\nCancel", reply_markup=get_inline_cancel())
        user_state[tg_id] = {'flow': 'art_wait_web', 'msg_id': msg.message_id}
    elif call.data in ["art_sel_grp", "art_sel_grp_b"]:
        msg = bot.send_message(call.message.chat.id, "1. Submit your Article PHOTOCARD:\nCancel", reply_markup=get_inline_cancel())
        user_state[tg_id] = {'flow': 'art_wait_grp_photo', 'msg_id': msg.message_id}
    elif call.data == "art_sel_txt":
        msg = bot.send_message(call.message.chat.id, "Please submit your Article TEXT:\nCancel", reply_markup=get_inline_cancel())
        user_state[tg_id] = {'flow': 'art_wait_txt', 'msg_id': msg.message_id}

@bot.callback_query_handler(func=lambda call: call.data == "art_final_submit")
def process_article_submit(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
        
    state = user_state.get(tg_id)
    if not state or 'art_data' not in state: return
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        mod_id = get_least_loaded_pub_mod()
        
        art_type = state['art_data']['type']
        content = state['art_data'].get('text', '')
        photo_id = state['art_data'].get('photo', '')
        
        cursor.execute("INSERT INTO kbkh_article_submissions (telegram_id, article_type, content_text, photo_id, assigned_grader) VALUES (%s, %s, %s, %s, %s)", (tg_id, art_type, content, photo_id, mod_id))
        if mod_id: cursor.execute("UPDATE kbkh_publisher_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (mod_id,))
        conn.commit()
        bot.send_message(call.message.chat.id, "Your article has been successfully SUBMITTED✅ \nPlease wait for the final confirmation!")
    finally:
        conn.close()
    user_state.pop(tg_id, None)

@bot.message_handler(func=lambda msg: msg.text == "On Hold")
def on_hold_coming_soon(message):
    bot.send_message(message.chat.id, "⏳ This feature is Coming Soon!")

@bot.message_handler(func=lambda msg: msg.text == "BKLn Team")
def on_hold_coming_soon_bkln(message):
    bot.send_message(message.chat.id, "⏳ Coming Soon!")

@bot.message_handler(func=lambda msg: msg.text in ["Pending Articles", "Pending Article"])
def pub_pending_articles(message):
    tg_id = message.from_user.id
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT status FROM kbkh_writers WHERE telegram_id = %s", (tg_id,))
        writer = cursor.fetchone()
        
        if writer and writer['status'] == 'Approved':
            cursor.execute("SELECT * FROM kbkh_article_submissions WHERE telegram_id = %s AND status = 'Approved' ORDER BY id ASC", (tg_id,))
            approved = cursor.fetchall()
            if not approved:
                bot.send_message(message.chat.id, "No approved articles found in the waiting list!")
                return
                
            markup = InlineKeyboardMarkup(row_width=6)
            btns = []
            for idx, art in enumerate(approved, 1):
                btns.append(InlineKeyboardButton(str(idx), callback_data=f"wart_{art['id']}"))
            markup.add(*btns)
            markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
            bot.send_message(message.chat.id, "Waiting List:", reply_markup=markup)
            return

        cursor.execute("SELECT is_active FROM kbkh_publisher_moderators WHERE telegram_id = %s", (tg_id,))
        mod = cursor.fetchone()
        if not mod or not mod['is_active']: return
            
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Intern Members", callback_data="pub_intern"), InlineKeyboardButton("Other Members", callback_data="pub_other"))
        markup.row(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Select Category:", reply_markup=markup)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("wart_"))
def show_writer_waiting_article(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    art_id = int(call.data.split("_")[1])
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_article_submissions WHERE id = %s", (art_id,))
        art = cursor.fetchone()
        if not art: return
        
        msg_extra = "\n\nWe hope your article will be published soon. You will receive a confirmation once it is published. Thank you!❤️"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        
        if art['article_type'] in ['website_link', 'website_text', 'text_only']:
            bot.send_message(call.message.chat.id, f"{art['content_text']}{msg_extra}", reply_markup=markup)
        elif art['article_type'] == 'groups':
            combined_text = f"{art['content_text']}{msg_extra}"
            m1 = bot.send_photo(call.message.chat.id, art['photo_id'])
            m2 = bot.send_message(call.message.chat.id, combined_text, reply_markup=markup)
            user_id = call.from_user.id
            if user_id not in user_state: user_state[user_id] = {}
            if 'task_msgs' not in user_state[user_id]: user_state[user_id]['task_msgs'] = []
            user_state[user_id]['task_msgs'].append(m1.message_id)
    finally:
        conn.close()

def render_pub_intern_list(chat_id, mod_id, message_id=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT s.telegram_id, m.fb_name, m.team_name, COUNT(s.id) as total 
            FROM kbkh_article_submissions s JOIN members m ON s.telegram_id = m.telegram_id 
            WHERE s.assigned_grader = %s AND s.status = 'Pending' 
            GROUP BY s.telegram_id, m.fb_name, m.team_name
        """, (mod_id,))
        records = cursor.fetchall()
        
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for r in records:
            if r['team_name'] in teams: teams[r['team_name']].append(r)
            
        markup = InlineKeyboardMarkup(row_width=1)
        for team in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            markup.add(InlineKeyboardButton(f"[--{team}--]", callback_data="ignore"))
            if teams[team]:
                for m in teams[team]: markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"pub_user_{m['telegram_id']}"))
                
        markup.row(InlineKeyboardButton("Back", callback_data="pub_back"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        if message_id:
            try: bot.edit_message_text("Intern Members List:", chat_id, message_id, reply_markup=markup)
            except: pass
        else:
            bot.send_message(chat_id, "Intern Members List:", reply_markup=markup)
    finally:
        conn.close()

def render_pub_other_list(chat_id, mod_id, message_id=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT s.telegram_id, w.short_name, COUNT(s.id) as total 
            FROM kbkh_article_submissions s JOIN kbkh_writers w ON s.telegram_id = w.telegram_id 
            WHERE s.assigned_grader = %s AND s.status = 'Pending' 
            GROUP BY s.telegram_id, w.short_name
        """, (mod_id,))
        records = cursor.fetchall()
        
        markup = InlineKeyboardMarkup(row_width=1)
        for m in records:
            markup.add(InlineKeyboardButton(f"{m['short_name']} - {m['total']}", callback_data=f"pub_otheru_{m['telegram_id']}"))
        markup.row(InlineKeyboardButton("Back", callback_data="pub_back"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        if message_id:
            try: bot.edit_message_text("Other Members List:", chat_id, message_id, reply_markup=markup)
            except: pass
        else:
            bot.send_message(chat_id, "Other Members List:", reply_markup=markup)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data in ["pub_intern", "pub_other", "pub_back"])
def pub_category_selection(call):
    mod_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    
    if call.data == "pub_intern":
        render_pub_intern_list(call.message.chat.id, mod_id, call.message.message_id)
    elif call.data == "pub_other":
        render_pub_other_list(call.message.chat.id, mod_id, call.message.message_id)
    elif call.data == "pub_back":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Intern Members", callback_data="pub_intern"), InlineKeyboardButton("Other Members", callback_data="pub_other"))
        markup.row(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try: bot.edit_message_text("Select Category:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("pub_user_") or call.data.startswith("pub_otheru_"))
def fetch_pub_user_article(call):
    mod_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    
    parts = call.data.split("_")
    is_other = (parts[1] == "otheru")
    target_user = int(parts[2])
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if is_other:
            cursor.execute("SELECT s.*, w.short_name as name FROM kbkh_article_submissions s JOIN kbkh_writers w ON s.telegram_id = w.telegram_id WHERE s.assigned_grader = %s AND s.telegram_id = %s AND s.status = 'Pending' ORDER BY s.id ASC LIMIT 1", (mod_id, target_user))
        else:
            cursor.execute("SELECT s.*, m.fb_name as name, m.team_name FROM kbkh_article_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.assigned_grader = %s AND s.telegram_id = %s AND s.status = 'Pending' ORDER BY s.id ASC LIMIT 1", (mod_id, target_user))
        sub = cursor.fetchone()
        
        if not sub:
            bot.answer_callback_query(call.id, "No pending articles found for this user.", show_alert=True)
            return
            
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        
        text_info = f"\n\nName: {sub['name']}"
        if not is_other: text_info += f"\nTeam: {sub['team_name']}"
        
        markup = get_pub_grading_kb(sub['id'], mark=None, is_approve=False, is_reject=False, is_writer=is_other)
        
        if sub['article_type'] in ['website_link', 'website_text', 'text_only']:
            msg_body = f"{sub['content_text']}{text_info}"
            bot.send_message(call.message.chat.id, msg_body, reply_markup=markup)
        elif sub['article_type'] == 'groups':
            combined_text = f"{sub['content_text']}{text_info}"
            m1 = bot.send_photo(call.message.chat.id, sub['photo_id'])
            bot.send_message(call.message.chat.id, combined_text, reply_markup=markup)
            if mod_id not in admin_state: admin_state[mod_id] = {}
            if 'task_msgs' not in admin_state[mod_id]: admin_state[mod_id]['task_msgs'] = []
            admin_state[mod_id]['task_msgs'].append(m1.message_id)
    finally:
        conn.close()

def get_pub_grading_kb(sub_id, mark=None, is_approve=False, is_reject=False, is_writer=False):
    markup = InlineKeyboardMarkup(row_width=6)
    if not is_writer:
        btns = []
        for i in range(1, 7): btns.append(InlineKeyboardButton(f"{i}✅" if str(mark)==str(i) else str(i), callback_data=f"pamk_{sub_id}_{i}"))
        markup.add(*btns)
    
    app_btn = InlineKeyboardButton("Approve✅" if is_approve else "Approve", callback_data=f"pamk_{sub_id}_app")
    rej_btn = InlineKeyboardButton("Reject❌" if is_reject else "Reject", callback_data=f"pamk_{sub_id}_rej")
    markup.row(app_btn, rej_btn)
    
    markup.row(InlineKeyboardButton("💬 Feedback", callback_data=f"pamk_{sub_id}_fbk"))
    markup.row(InlineKeyboardButton("Submit", callback_data=f"pamk_{sub_id}_sub"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("pamk_"))
def pub_grading_actions(call):
    mod_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    
    if mod_id not in admin_state: admin_state[mod_id] = {}
    parts = call.data.split("_")
    sub_id = int(parts[1])
    action = parts[2]
    
    mark = admin_state[mod_id].get(f'pamk_{sub_id}')
    is_approve = admin_state[mod_id].get(f'paapp_{sub_id}', False)
    is_reject = admin_state[mod_id].get(f'parej_{sub_id}', False)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id FROM kbkh_article_submissions WHERE id = %s", (sub_id,))
        uid = cursor.fetchone()['telegram_id']
        cursor.execute("SELECT telegram_id FROM kbkh_writers WHERE telegram_id = %s", (uid,))
        is_writer = bool(cursor.fetchone())
    finally:
        conn.close()
    
    if action in ["1", "2", "3", "4", "5", "6"]:
        admin_state[mod_id][f'pamk_{sub_id}'] = action
        admin_state[mod_id][f'parej_{sub_id}'] = False
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_pub_grading_kb(sub_id, mark=action, is_approve=is_approve, is_reject=False, is_writer=is_writer))
        except: pass
        
    elif action == "app":
        admin_state[mod_id][f'paapp_{sub_id}'] = True
        admin_state[mod_id][f'parej_{sub_id}'] = False
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_pub_grading_kb(sub_id, mark=mark, is_approve=True, is_reject=False, is_writer=is_writer))
        except: pass
        
    elif action == "rej":
        admin_state[mod_id][f'pamk_{sub_id}'] = None
        admin_state[mod_id][f'paapp_{sub_id}'] = False
        admin_state[mod_id][f'parej_{sub_id}'] = True
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_pub_grading_kb(sub_id, mark=None, is_approve=False, is_reject=True, is_writer=is_writer))
        except: pass
        
    elif action == "fbk":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:\nCancel", reply_markup=get_inline_cancel())
        admin_state[mod_id][f'prompt_msg_id_{sub_id}'] = msg_box.message_id
        bot.register_next_step_handler(msg_box, process_pub_feedback, sub_id, is_writer)
        
    elif action == "sub":
        if not is_reject and not is_approve:
            return bot.answer_callback_query(call.id, "Please select Approve or Reject!", show_alert=True)
        if not is_writer and is_approve and not mark:
            return bot.answer_callback_query(call.id, "Please select a mark before Approving!", show_alert=True)
            
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        finalize_pub_grading(sub_id, mod_id, call.message.chat.id, is_writer)

def process_pub_feedback(message, sub_id, is_writer):
    mod_id = message.from_user.id
    if mod_id not in admin_state: admin_state[mod_id] = {}
    admin_state[mod_id][f'pafbk_{sub_id}'] = message.text
    
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    
    prompt_msg_id = admin_state[mod_id].get(f'prompt_msg_id_{sub_id}')
    if prompt_msg_id:
        try: bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_article_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        if is_writer:
            cursor.execute("SELECT short_name as name FROM kbkh_writers WHERE telegram_id = %s", (sub['telegram_id'],))
            uinfo = cursor.fetchone()
            cap_info = f"\n\nName: {uinfo['name']}"
        else:
            cursor.execute("SELECT fb_name as name, team_name FROM members WHERE telegram_id = %s", (sub['telegram_id'],))
            uinfo = cursor.fetchone()
            cap_info = f"\n\nName: {uinfo['name']}\nTeam: {uinfo['team_name']}"
        
        mark = admin_state[mod_id].get(f'pamk_{sub_id}')
        is_approve = admin_state[mod_id].get(f'paapp_{sub_id}', False)
        is_reject = admin_state[mod_id].get(f'parej_{sub_id}', False)
        
        markup = get_pub_grading_kb(sub_id, mark=mark, is_approve=is_approve, is_reject=is_reject, is_writer=is_writer)
        
        if is_reject:
            cap_extra = f"{cap_info}\nSTATUS: Rejected❌\n⏪Feedback: {message.text}"
        else:
            if is_writer:
                cap_extra = f"{cap_info}\nSTATUS: Approved✅\n⏪Feedback: {message.text}"
            else:
                cap_extra = f"{cap_info}\n🔖Marks: {mark}️⃣\nSTATUS: Approved✅\n⏪Feedback: {message.text}"
            
        if sub['article_type'] == 'groups':
            combined_text = f"{sub['content_text']}{cap_extra}"
            m1 = bot.send_photo(message.chat.id, sub['photo_id'])
            bot.send_message(message.chat.id, combined_text, reply_markup=markup)
            if mod_id not in admin_state: admin_state[mod_id] = {}
            if 'task_msgs' not in admin_state[mod_id]: admin_state[mod_id]['task_msgs'] = []
            admin_state[mod_id]['task_msgs'].append(m1.message_id)
        else:
            bot.send_message(message.chat.id, f"{sub['content_text']}{cap_extra}", reply_markup=markup)
    finally:
        conn.close()

def finalize_pub_grading(sub_id, mod_id, chat_id, is_writer):
    mark = admin_state[mod_id].get(f'pamk_{sub_id}')
    is_reject = admin_state[mod_id].get(f'parej_{sub_id}')
    feedback = admin_state[mod_id].get(f'pafbk_{sub_id}', '')
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_article_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        cursor.execute("SELECT mod_name FROM kbkh_publisher_moderators WHERE telegram_id = %s", (mod_id,))
        mod_info = cursor.fetchone()
        mod_name = mod_info['mod_name'] if mod_info else "Moderator"
        
        status_update = "Rejected" if is_reject else "Approved"
        final_mark = int(mark) if mark and not is_writer else 0
        
        cursor.execute("UPDATE kbkh_article_submissions SET status = %s, mark = %s, feedback = %s WHERE id = %s", (status_update, final_mark, feedback, sub_id))
        cursor.execute("UPDATE kbkh_publisher_moderators SET total_assigned = GREATEST(0, total_assigned - 1) WHERE telegram_id = %s", (mod_id,))
        
        month_name = (sub['created_at'] + timedelta(hours=6)).strftime("%B")
        if not is_reject and final_mark > 0 and not is_writer:
            cursor.execute("INSERT INTO kbkh_task_records (telegram_id, month, article_mark) VALUES (%s, %s, %s) ON CONFLICT (telegram_id, month) DO UPDATE SET article_mark = kbkh_task_records.article_mark + %s", (sub['telegram_id'], month_name, final_mark, final_mark))
        conn.commit()
        
        # Notify User
        base_body = sub['content_text']
        if sub['article_type'] in ['website_link', 'website_text', 'text_only']:
            if is_reject:
                msg_to_user = f"{base_body}\n\nSorry, your article has been REJECTED❌\nRejected by Publisher: {mod_name}"
            else:
                msg_to_user = f"{base_body}\n\nCongratulations❤️\nYour article has been REVIEWED and will be PUBLISHED SOON!"
                if not is_writer and final_mark > 0: msg_to_user += f"\n\n🔖Obtained Marks - {mark}️⃣"
        else: # groups
            if is_reject:
                msg_to_user = f"{base_body}\n\nSorry, your article has been REJECTED❌\nRejected by Publisher: {mod_name}"
            else:
                msg_to_user = f"{base_body}\n\nArticle Review Completed! Your Results Are Ready.✅"
                if not is_writer and final_mark > 0: msg_to_user += f"\n\n🔖Obtained Marks - {mark}️⃣"
                else: msg_to_user = f"{base_body}\n\nCongratulations❤️\nYour article has been REVIEWED and will be PUBLISHED SOON!"
                
        if feedback: msg_to_user += f"\n⏪Feedback: {feedback}"
            
        try:
            if sub['article_type'] == 'groups': 
                if len(msg_to_user) <= 1024:
                    bot.send_photo(sub['telegram_id'], sub['photo_id'], caption=msg_to_user)
                else:
                    bot.send_photo(sub['telegram_id'], sub['photo_id'])
                    bot.send_message(sub['telegram_id'], msg_to_user)
            else: 
                bot.send_message(sub['telegram_id'], msg_to_user)
        except: pass
            
    finally:
        conn.close()
        
    if mod_id in admin_state:
        admin_state[mod_id].pop(f'pamk_{sub_id}', None)
        admin_state[mod_id].pop(f'paapp_{sub_id}', None)
        admin_state[mod_id].pop(f'parej_{sub_id}', None)
        admin_state[mod_id].pop(f'pafbk_{sub_id}', None)
        admin_state[mod_id].pop(f'prompt_msg_id_{sub_id}', None)
        
    if is_writer: render_pub_other_list(chat_id, mod_id)
    else: render_pub_intern_list(chat_id, mod_id)

# ==========================================
# 📊 STATUS PANELS (Month Selector)
# ==========================================
def get_months_kb(prefix):
    markup = InlineKeyboardMarkup(row_width=3)
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    btns = []
    for m in months: btns.append(InlineKeyboardButton(m[:3], callback_data=f"{prefix}_{m}"))
    markup.add(*btns)
    markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
    return markup

@bot.message_handler(func=lambda msg: msg.text in ["My Task Status", "Members Status", "KBKh Team"])
def status_selectors(message):
    tg_id = message.from_user.id
    if message.text == "My Task Status":
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("myts"))
    else:
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("modst"))

@bot.callback_query_handler(func=lambda call: call.data.startswith("myts_") or call.data.startswith("modst_") or call.data.startswith("modstteam_") or call.data == "back_modst")
def status_callbacks(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
        
    if call.data == "back_modst":
        try: bot.edit_message_text("🗓️Please Select Month:", call.message.chat.id, call.message.message_id, reply_markup=get_months_kb("modst"))
        except: pass
        return
        
    parts = call.data.split("_")
    action = parts[0]
    
    if action == "myts":
        month = parts[1]
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM kbkh_task_records WHERE telegram_id = %s AND month = %s", (tg_id, month))
            rec = cursor.fetchone()
            
            tdone = rec['task_done'] if rec else 0
            ttot = rec['task_total'] if rec else 0
            qmark = rec['qna_mark'] if rec else 0
            amark = rec['article_mark'] if rec else 0
            
            text = f"🗓️ Month - {month}\n\nSpecial Task- {tdone}/{ttot}\nQnA Mark - {qmark}\nArticle Mark- {amark}"
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_inline_cancel())
            except: pass
        finally:
            conn.close()
            
    elif action == "modst":
        month = parts[1]
        if tg_id not in admin_state: admin_state[tg_id] = {}
        admin_state[tg_id]['modst_month'] = month
        admin_state[tg_id]['modst_exp_team'] = None 
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, month)
        
    elif action == "modstteam":
        t_name = parts[1]
        if tg_id not in admin_state: admin_state[tg_id] = {}
        current = admin_state[tg_id].get('modst_exp_team')
        admin_state[tg_id]['modst_exp_team'] = None if current == t_name else t_name
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, admin_state[tg_id].get('modst_month'))

def render_members_status_list(chat_id, message_id, mod_id, month):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, fb_name, team_name FROM members WHERE status = 'Approved' ORDER BY team_name, fb_name")
        members = cursor.fetchall()
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for m in members:
            if m['team_name'] in teams: teams[m['team_name']].append(m)
                
        expanded_team = admin_state.get(mod_id, {}).get('modst_exp_team')
        
        text = f"🗓️Month - {month}\n\n"
        markup = InlineKeyboardMarkup(row_width=1)
        
        for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if expanded_team == t:
                markup.add(InlineKeyboardButton(f"🔺{t}", callback_data=f"modstteam_{t}"))
                if not teams[t]:
                    pass
                else:
                    for m in teams[t]:
                        cursor.execute("SELECT task_done, task_total, qna_mark, article_mark FROM kbkh_task_records WHERE telegram_id = %s AND month = %s", (m['telegram_id'], month))
                        rec = cursor.fetchone()
                        tdone = rec['task_done'] if rec else 0
                        ttot = rec['task_total'] if rec else 0
                        qmark = rec['qna_mark'] if rec else 0
                        amark = rec['article_mark'] if rec else 0
                        
                        text += f"👤{m['fb_name']}\n"
                        text += f"- Special Task - {tdone}/{ttot}\n"
                        text += f"- QnA Mark - {qmark}\n"
                        text += f"- Article Mark - {amark}\n\n"
            else:
                markup.add(InlineKeyboardButton(f"🔻{t}", callback_data=f"modstteam_{t}"))
                
        markup.row(InlineKeyboardButton("Back", callback_data="back_modst"), InlineKeyboardButton("Close", callback_data="cancel_action"))
        try: bot.edit_message_text(text.strip(), chat_id, message_id, reply_markup=markup)
        except: pass
    finally:
        conn.close()

# ==========================================
# 👑 MAIN ADMIN: MODERATORS PANEL
# ==========================================
def render_main_admin_mods(chat_id, adm_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        markup = InlineKeyboardMarkup(row_width=3)
        exp_team = admin_state.get(adm_id, {}).get('admin_mod_exp')
        target_mod = admin_state.get(adm_id, {}).get('mod_target')
        
        # QnA Team
        if exp_team == 'qna':
            markup.add(InlineKeyboardButton("QnA Making Team 🔻", callback_data="amod_qna"))
            cursor.execute("SELECT telegram_id, mod_name, team_name, total_assigned, is_blocked FROM kbkh_qna_moderators WHERE is_active = TRUE")
            mods = cursor.fetchall()
            teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
            for m in mods:
                if m['team_name'] in teams: teams[m['team_name']].append(m)
            for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
                if teams[t]:
                    markup.add(InlineKeyboardButton(f"--{t}--", callback_data="ignore"))
                    for m in teams[t]:
                        blk_icon = "⛔🔒" if m['is_blocked'] else "⛔"
                        kck_icon = "❌"
                        if target_mod and target_mod['id'] == m['telegram_id']:
                            if target_mod['action'] == 'block': blk_icon = "⛔" if m['is_blocked'] else "⛔🔒"
                            elif target_mod['action'] == 'kick': kck_icon = "❌✅"
                        btn_name = InlineKeyboardButton(f"{m['mod_name']} - {m['total_assigned']}", callback_data="ignore")
                        btn_blk = InlineKeyboardButton(blk_icon, callback_data=f"amodblk_qna_{m['telegram_id']}")
                        btn_kck = InlineKeyboardButton(kck_icon, callback_data=f"amodkck_qna_{m['telegram_id']}")
                        markup.row(btn_name, btn_blk, btn_kck)
            markup.add(InlineKeyboardButton("Submit", callback_data="amod_sub"))
        else:
            markup.add(InlineKeyboardButton("QnA Making Team 🔺", callback_data="amod_qna"))
            
        # Publisher Team
        if exp_team == 'pub':
            markup.add(InlineKeyboardButton("Publisher Team 🔻", callback_data="amod_pub"))
            cursor.execute("SELECT telegram_id, mod_name, total_assigned, is_blocked FROM kbkh_publisher_moderators WHERE is_active = TRUE")
            p_mods = cursor.fetchall()
            for m in p_mods:
                blk_icon = "⛔🔒" if m['is_blocked'] else "⛔"
                kck_icon = "❌"
                if target_mod and target_mod['id'] == m['telegram_id']:
                    if target_mod['action'] == 'block': blk_icon = "⛔" if m['is_blocked'] else "⛔🔒"
                    elif target_mod['action'] == 'kick': kck_icon = "❌✅"
                btn_name = InlineKeyboardButton(f"{m['mod_name']} - {m['total_assigned']}", callback_data="ignore")
                btn_blk = InlineKeyboardButton(blk_icon, callback_data=f"amodblk_pub_{m['telegram_id']}")
                btn_kck = InlineKeyboardButton(kck_icon, callback_data=f"amodkck_pub_{m['telegram_id']}")
                markup.row(btn_name, btn_blk, btn_kck)
            if p_mods: markup.add(InlineKeyboardButton("Submit", callback_data="amod_sub"))
        else:
            markup.add(InlineKeyboardButton("Publisher Team 🔺", callback_data="amod_pub"))
            
        # Writer Team
        if exp_team == 'write':
            markup.add(InlineKeyboardButton("Writer Team 🔻", callback_data="amod_write_open"))
            markup.row(InlineKeyboardButton("Pending Registration", callback_data="wreg_pend"), InlineKeyboardButton("Member's", callback_data="wreg_mem"))
        else:
            markup.add(InlineKeyboardButton("Writer Team 🔺", callback_data="amod_write_open"))
            
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        if message_id:
            try: bot.edit_message_text("Admin Moderators Panel:", chat_id, message_id, reply_markup=markup)
            except: pass
        else:
            bot.send_message(chat_id, "Admin Moderators Panel:", reply_markup=markup)
    finally:
        conn.close()

def render_writer_pending_list(chat_id, adm_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, short_name FROM kbkh_writers WHERE status = 'Pending'")
        writers = cursor.fetchall()
        
        markup = InlineKeyboardMarkup(row_width=3)
        if not writers:
            markup.add(InlineKeyboardButton("No pending registrations", callback_data="ignore"))
        else:
            target_w = admin_state.get(adm_id, {}).get('writer_target')
            for w in writers:
                app_icon = "🔲"
                rej_icon = "❌"
                if target_w and target_w['id'] == w['telegram_id']:
                    if target_w['action'] == 'app': app_icon = "✅"
                    elif target_w['action'] == 'rej': rej_icon = "❌✅"
                
                markup.row(
                    InlineKeyboardButton(w['short_name'], callback_data="ignore"),
                    InlineKeyboardButton(app_icon, callback_data=f"wact_app_{w['telegram_id']}"),
                    InlineKeyboardButton(rej_icon, callback_data=f"wact_rej_{w['telegram_id']}")
                )
        markup.row(InlineKeyboardButton("Back", callback_data="amod_write_open"), InlineKeyboardButton("Submit", callback_data="wreg_sub"))
        try: bot.edit_message_text("Pending Writer Registrations:", chat_id, message_id, reply_markup=markup)
        except: pass
    finally:
        conn.close()

def render_writer_members_list(chat_id, adm_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, short_name, is_blocked FROM kbkh_writers WHERE status = 'Approved'")
        writers = cursor.fetchall()
        
        markup = InlineKeyboardMarkup(row_width=2)
        if not writers:
            markup.add(InlineKeyboardButton("No writers found", callback_data="ignore"))
        else:
            target_w = admin_state.get(adm_id, {}).get('writer_target')
            for w in writers:
                cursor.execute("SELECT COUNT(*) FROM kbkh_article_submissions WHERE telegram_id = %s AND status = 'Approved'", (w['telegram_id'],))
                total_sub = cursor.fetchone()['count']
                
                blk_icon = "⛔🔒" if w['is_blocked'] else "⛔"
                kck_icon = "❌"
                if target_w and target_w['id'] == w['telegram_id']:
                    if target_w['action'] == 'blk': blk_icon = "⛔" if w['is_blocked'] else "⛔🔒"
                    elif target_w['action'] == 'kck': kck_icon = "❌✅"
                
                markup.row(InlineKeyboardButton(f"{w['short_name']} - {total_sub}", callback_data="ignore"))
                markup.row(
                    InlineKeyboardButton(blk_icon, callback_data=f"wact_blk_{w['telegram_id']}"),
                    InlineKeyboardButton(kck_icon, callback_data=f"wact_kck_{w['telegram_id']}")
                )
        markup.row(InlineKeyboardButton("Back", callback_data="amod_write_open"), InlineKeyboardButton("Submit", callback_data="wmem_sub"))
        try: bot.edit_message_text("Writer Members:", chat_id, message_id, reply_markup=markup)
        except: pass
    finally:
        conn.close()

@bot.message_handler(func=lambda msg: msg.text == "Moderators")
def admin_moderators_panel(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        return
    render_main_admin_mods(message.chat.id, message.from_user.id, None)

# ==========================================
# ⚙️ ADMIN ACTIONS HANDLER
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data == "cancel_action")
def universal_cancel_action(call):
    user_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
        
    if user_id in admin_state and 'task_msgs' in admin_state[user_id]:
        for m_id in admin_state[user_id]['task_msgs']:
            try: bot.delete_message(call.message.chat.id, m_id)
            except: pass
            
    if user_id in user_state and 'task_msgs' in user_state[user_id]:
        for m_id in user_state[user_id]['task_msgs']:
            try: bot.delete_message(call.message.chat.id, m_id)
            except: pass

    if user_id in admin_state: admin_state.pop(user_id, None)
    if user_id in user_state: user_state.pop(user_id, None)
        
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    try: bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("amod_") or call.data.startswith("amodblk_") or call.data.startswith("amodkck_") or call.data.startswith("wreg_") or call.data.startswith("wact_") or call.data == "wmem_sub" or call.data.startswith("ta_") or call.data.startswith("ei_") or call.data.startswith("ti_") or call.data.startswith("mi_") or call.data == "reset_task_yes" or call.data.startswith("adm_") or call.data.startswith("grd_") or call.data.startswith("gact_") or call.data.startswith("gfbk_") or call.data.startswith("gsub_"))
def central_admin_actions(call):
    adm_id = call.from_user.id
    if str(adm_id) != ADMIN_CHAT_ID: return
        
    try: bot.answer_callback_query(call.id)
    except: pass
    
    data = call.data
    if adm_id not in admin_state: admin_state[adm_id] = {}

    if data in ["amod_qna", "amod_pub", "amod_write", "amod_write_open"]:
        if data == "amod_write_open": team_type = 'write'
        else: team_type = data.split("_")[1]
        
        curr = admin_state[adm_id].get('admin_mod_exp')
        admin_state[adm_id]['admin_mod_exp'] = None if curr == team_type and data != "amod_write_open" else team_type
        render_main_admin_mods(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data.startswith("wreg_"):
        act = data.split("_")[1]
        admin_state[adm_id]['writer_target'] = None
        if act == "pend": render_writer_pending_list(call.message.chat.id, adm_id, call.message.message_id)
        elif act == "mem": render_writer_members_list(call.message.chat.id, adm_id, call.message.message_id)
        elif act == "sub":
            target = admin_state.get(adm_id, {}).get('writer_target')
            if not target: return bot.answer_callback_query(call.id, "Select action first!", show_alert=True)
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                if target['action'] == 'app':
                    cursor.execute("UPDATE kbkh_writers SET status = 'Approved' WHERE telegram_id = %s", (target['id'],))
                    try: bot.send_message(target['id'], "Welcome!❤️", reply_markup=writer_main_menu())
                    except: pass
                elif target['action'] == 'rej':
                    cursor.execute("DELETE FROM kbkh_writers WHERE telegram_id = %s", (target['id'],))
                    try: bot.send_message(target['id'], "Application REJECTED❌", reply_markup=ReplyKeyboardRemove())
                    except: pass
                conn.commit()
            finally:
                conn.close()
            admin_state[adm_id]['writer_target'] = None
            render_writer_pending_list(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data.startswith("wact_"):
        parts = data.split("_")
        act = parts[1]
        uid = int(parts[2])
        curr = admin_state[adm_id].get('writer_target')
        
        if curr and curr['id'] == uid and curr['action'] == act:
            admin_state[adm_id]['writer_target'] = None
        else:
            admin_state[adm_id]['writer_target'] = {'id': uid, 'action': act}
            
        if act in ['app', 'rej']: render_writer_pending_list(call.message.chat.id, adm_id, call.message.message_id)
        elif act in ['blk', 'kck']: render_writer_members_list(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data == "wmem_sub":
        target = admin_state.get(adm_id, {}).get('writer_target')
        if not target: return bot.answer_callback_query(call.id, "Select action first!", show_alert=True)
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            if target['action'] == 'blk':
                cursor.execute("SELECT is_blocked FROM kbkh_writers WHERE telegram_id = %s", (target['id'],))
                w = cursor.fetchone()
                if w:
                    new_status = not w['is_blocked']
                    cursor.execute("UPDATE kbkh_writers SET is_blocked = %s WHERE telegram_id = %s", (new_status, target['id']))
                    try:
                        if new_status: bot.send_message(target['id'], "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
                        else: bot.send_message(target['id'], "Welcome back!❤️", reply_markup=writer_main_menu())
                    except: pass
            elif target['action'] == 'kck':
                cursor.execute("DELETE FROM kbkh_writers WHERE telegram_id = %s", (target['id'],))
                try: bot.send_message(target['id'], "You are not REGISTERED❌", reply_markup=ReplyKeyboardRemove())
                except: pass
            conn.commit()
        finally:
            conn.close()
        admin_state[adm_id]['writer_target'] = None
        render_writer_members_list(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data.startswith("amodblk_"):
        parts = data.split("_")
        team_type = parts[1]
        tg = int(parts[2])
        curr = admin_state[adm_id].get('mod_target')
        if curr and curr['id'] == tg and curr['action'] == 'block':
            admin_state[adm_id]['mod_target'] = None
        else:
            admin_state[adm_id]['mod_target'] = {'id': tg, 'action': 'block', 'type': team_type}
        render_main_admin_mods(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data.startswith("amodkck_"):
        parts = data.split("_")
        team_type = parts[1]
        tg = int(parts[2])
        curr = admin_state[adm_id].get('mod_target')
        if curr and curr['id'] == tg and curr['action'] == 'kick':
            admin_state[adm_id]['mod_target'] = None
        else:
            admin_state[adm_id]['mod_target'] = {'id': tg, 'action': 'kick', 'type': team_type}
        render_main_admin_mods(call.message.chat.id, adm_id, call.message.message_id)
        return
        
    elif data == "amod_sub":
        target = admin_state.get(adm_id, {}).get('mod_target')
        if not target: return bot.answer_callback_query(call.id, "Select action first!", show_alert=True)
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            table_name = "kbkh_qna_moderators" if target['type'] == 'qna' else "kbkh_publisher_moderators"
            
            if target['action'] == 'block':
                cursor.execute(f"SELECT is_blocked FROM {table_name} WHERE telegram_id = %s", (target['id'],))
                mod = cursor.fetchone()
                if mod:
                    new_status = not mod['is_blocked']
                    cursor.execute(f"UPDATE {table_name} SET is_blocked = %s WHERE telegram_id = %s", (new_status, target['id']))
                    try:
                        if new_status:
                            bot.send_message(target['id'], "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
                        else:
                            bot.send_message(target['id'], "Welcome Sir❤️\nYou are back in Team!", reply_markup=qna_marking_menu() if target['type'] == 'qna' else article_publish_menu())
                    except: pass
                        
            elif target['action'] == 'kick':
                cursor.execute(f"UPDATE {table_name} SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (target['id'],))
                if target['type'] == 'qna':
                    cursor.execute("SELECT id FROM kbkh_qna_submissions WHERE assigned_grader = %s AND status = 'Pending'", (target['id'],))
                    for p in cursor.fetchall():
                        new_mod = get_least_loaded_qna_mod()
                        cursor.execute("UPDATE kbkh_qna_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                        if new_mod: cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                else:
                    cursor.execute("SELECT id FROM kbkh_article_submissions WHERE assigned_grader = %s AND status = 'Pending'", (target['id'],))
                    for p in cursor.fetchall():
                        new_mod = get_least_loaded_pub_mod()
                        cursor.execute("UPDATE kbkh_article_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
                        if new_mod: cursor.execute("UPDATE kbkh_publisher_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                try: bot.send_message(target['id'], "You are not REGISTERED❌", reply_markup=ReplyKeyboardRemove())
                except: pass
                    
            conn.commit()
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, "Action executed successfully!✅")
        finally:
            conn.close()
            
        admin_state[adm_id].pop('mod_target', None)
        return

    # 3. Reset Data Action
    if data == "reset_task_yes":
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kbkh_user_task_status;")
            cursor.execute("DELETE FROM kbkh_active_assignments;")
            cursor.execute("DELETE FROM kbkh_submissions;")
            cursor.execute("DELETE FROM kbkh_question_bank;")
            cursor.execute("DELETE FROM kbkh_qna_submissions;")
            cursor.execute("DELETE FROM kbkh_task_records;")
            cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = 0;")
            cursor.execute("DELETE FROM kbkh_article_submissions;")
            cursor.execute("UPDATE kbkh_publisher_moderators SET total_assigned = 0;")
            conn.commit()
            
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, "All Member Data has been permanently reset!✅")
        finally:
            conn.close()
        return
        
    # 4. ADMIN TASK REVIEW (Task Submitted / Completed)
    if data == "adm_back":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try: bot.edit_message_text("Task Menu:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return
        
    elif data in ["adm_tsub", "adm_tcomp"]:
        is_completed = (data == "adm_tcomp")
        render_admin_submission_list(call.message.chat.id, call.message.message_id, is_completed)
        return
        
    elif data.startswith("grd_"):
        sub_id = int(data.split("_")[1])
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
            sub = cursor.fetchone()
            
            if not sub: return
                
            admin_state[adm_id]['grading_sub'] = sub_id
            admin_state[adm_id]['action'] = None
            admin_state[adm_id]['task_msgs'] = []
            
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            try:
                items = json.loads(sub['content_text'])
                for item in items:
                    if item.get('photo'):
                        if item.get('text') and len(item['text']) > 1024:
                            bot.send_photo(call.message.chat.id, item['photo'])
                            m = bot.send_message(call.message.chat.id, item['text'])
                        else:
                            m = bot.send_photo(call.message.chat.id, item['photo'], caption=item.get('text', ''))
                    else: m = bot.send_message(call.message.chat.id, item.get('text', ''))
                    admin_state[adm_id]['task_msgs'].append(m.message_id)
            except:
                if sub['photo_id']:
                    if sub['content_text'] and len(sub['content_text']) > 1024:
                        bot.send_photo(call.message.chat.id, sub['photo_id'])
                        m = bot.send_message(call.message.chat.id, sub['content_text'])
                    else:
                        m = bot.send_photo(call.message.chat.id, sub['photo_id'], caption=sub['content_text'])
                else: m = bot.send_message(call.message.chat.id, sub['content_text'])
                admin_state[adm_id]['task_msgs'].append(m.message_id)
                
            info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}"
            markup = get_admin_grading_kb(sub_id)
            bot.send_message(call.message.chat.id, info_text, reply_markup=markup)
        finally:
            conn.close()
        return
        
    elif data.startswith("gact_"):
        parts = data.split("_")
        sub_id = int(parts[1])
        act = parts[2]
        admin_state[adm_id]['action'] = act
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_grading_kb(sub_id, act))
        except: pass
        return
        
    elif data.startswith("gfbk_"):
        sub_id = int(data.split("_")[1])
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        for m_id in admin_state.get(adm_id, {}).get('task_msgs', []):
            try: bot.delete_message(call.message.chat.id, m_id)
            except: pass
        markup = get_inline_cancel()
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=markup)
        admin_state[adm_id]['prompt_msg_id'] = msg_box.message_id
        bot.register_next_step_handler(msg_box, process_admin_feedback, sub_id)
        return
        
    elif data.startswith("gsub_"):
        sub_id = int(data.split("_")[1])
        act = admin_state.get(adm_id, {}).get('action')
        feedback = admin_state.get(adm_id, {}).get('feedback')
        if not act: return bot.answer_callback_query(call.id, "Select Approve or Reject!", show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        finalize_grading(sub_id, act, feedback, adm_id, call.message.chat.id)
        return

    # 5. Task Assign & Organize Flow
    if data == "ta_main":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Add Task", callback_data="ta_add"), InlineKeyboardButton("Task List", callback_data="ta_list"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return

    if data == "ta_list":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Organize Task", callback_data="ta_org"), InlineKeyboardButton("Assign Task", callback_data="ta_assign"))
        markup.row(InlineKeyboardButton("Back", callback_data="ta_main"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return

    if data == "ta_add":
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(task_num) FROM kbkh_tasks")
            row = cursor.fetchone()
            next_t = (row[0] if row[0] is not None else 0) + 1
            admin_state[adm_id]['t_num'] = next_t
            admin_state[adm_id]['clean_msgs'] = []
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            msg = bot.send_message(call.message.chat.id, f"Give the first message of the Task -{next_t}:", reply_markup=get_inline_cancel())
            admin_state[adm_id]['clean_msgs'].append(msg.message_id)
            bot.register_next_step_handler(msg, step_add_msg1)
        finally:
            conn.close()
        return

    if data.startswith("ta_end_"):
        try: bot.clear_step_handler_by_chat_id(call.message.chat.id)
        except: pass
        if 'clean_msgs' in admin_state[adm_id]: admin_state[adm_id]['clean_msgs'].append(call.message.message_id)
        state = admin_state.get(adm_id, {})
        t_num = state.get('t_num')
        if not t_num: return
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO kbkh_tasks (task_num, msg_1, msg_2, msg_3) 
                VALUES (%s, %s, %s, %s) 
                ON CONFLICT (task_num) DO UPDATE SET msg_1=EXCLUDED.msg_1, msg_2=EXCLUDED.msg_2, msg_3=EXCLUDED.msg_3
            """, (t_num, state.get('msg_1'), state.get('msg_2'), state.get('msg_3')))
            conn.commit()
            for m_id in state.get('clean_msgs', []):
                try: bot.delete_message(call.message.chat.id, m_id)
                except: pass
            admin_state[adm_id].pop('t_num', None)
            admin_state[adm_id].pop('clean_msgs', None)
            bot.send_message(call.message.chat.id, f"All your messages for Task-{t_num} have been successfully added!✅")
        finally:
            conn.close()
        return

    if data == "ta_org":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg = bot.send_message(call.message.chat.id, "Please provide the list.\n(Example: 1,2,3)", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg, step_org_task)
        return

    if data == "ta_assign":
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT COUNT(*) FROM kbkh_active_assignments")
            if cursor.fetchone()['count'] > 0: 
                return bot.answer_callback_query(call.id, "Already assigned a Task! Please stop it first in Triggered Task.", show_alert=True)
            admin_state[adm_id]['assigning'] = {'selected': None}
            render_ta_assign_page(call.message.chat.id, call.message.message_id, adm_id)
        finally:
            conn.close()
        return

    if data.startswith("ta_asgsel_"):
        org_id = int(data.split("_")[2])
        curr_sel = admin_state[adm_id].get('assigning', {}).get('selected')
        admin_state[adm_id]['assigning']['selected'] = None if curr_sel == org_id else org_id
        render_ta_assign_page(call.message.chat.id, call.message.message_id, adm_id)
        return

    if data == "ta_asgdel":
        selected_id = admin_state[adm_id].get('assigning', {}).get('selected')
        if not selected_id: return
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kbkh_organized_tasks WHERE id = %s", (selected_id,))
            conn.commit()
            admin_state[adm_id]['assigning']['selected'] = None
            render_ta_assign_page(call.message.chat.id, call.message.message_id, adm_id)
        finally:
            conn.close()
        return

    if data == "ta_asgsub":
        org_id = admin_state[adm_id].get('assigning', {}).get('selected')
        if not org_id: return
        seq_str = next((o['sequence'] for o in admin_state[adm_id].get('assigning', {}).get('orgs', []) if o['id'] == org_id), None)
        if not seq_str: return
        tasks = seq_str.split(',')
        teams = ['Team Alpha', 'Team Beta', 'Team Gamma']
        next_midnight = (get_bd_time() + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
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
            admin_state[adm_id]['assigning']['selected'] = None
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, f"Task: {seq_str.replace(',',' ')} Assigned Successfully✅\nWill trigger at Midnight.")
        finally:
            conn.close()
        return

    if data == "ta_stop":
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kbkh_active_assignments WHERE is_started = FALSE")
            conn.commit()
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            bot.send_message(call.message.chat.id, "Task Assign Cancelled Successfully✅")
        finally:
            conn.close()
        return

    if data == "ta_force_end":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Yes", callback_data="ta_force_end_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
        bot.send_message(call.message.chat.id, "Are you sure you want to end the task?", reply_markup=markup)
        return

    if data == "ta_force_end_yes":
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
        finally:
            conn.close()
            
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        bot.send_message(call.message.chat.id, "Task Successfully end!✅")
        for uid in auto_end_users:
            try: bot.send_message(uid, "Task END!\nThank you dear member♥️")
            except: pass
        return

    # 6. Edit Instructions Flow
    if data == "ei_back":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Task Instructions", callback_data="ei_task"), InlineKeyboardButton("QnA Instructions", callback_data="ei_qna"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return

    if data == "ei_task":
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(adm_id))
        except: pass
        return

    if data == "ei_qna":
        markup, text = get_qna_inst_keyboard(adm_id)
        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return

    if data.startswith("mi_sel_"):
        sel_id = int(data.split("_")[2])
        admin_state[adm_id]['edit_main'] = sel_id
        markup, text = get_qna_inst_keyboard(adm_id, sel_id)
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except: pass
        return

    if data.startswith("mi_view_"):
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
        finally:
            conn.close()
        return

    if data.startswith("mi_yes_"):
        sel_id = int(data.split("_")[2])
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg = bot.send_message(call.message.chat.id, f"Input the new message for Instruction {sel_id}:", reply_markup=get_inline_cancel())
        admin_state[adm_id]['wait_mi'] = sel_id
        bot.register_next_step_handler(msg, step_update_qna_inst)
        return

    if data == "mi_click":
        sel_id = admin_state[adm_id].get('edit_main')
        if not sel_id: return
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kbkh_custom_instructions WHERE id = %s", (sel_id,))
            conn.commit()
            admin_state[adm_id]['edit_main'] = None
            markup, text = get_qna_inst_keyboard(adm_id)
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
        finally:
            conn.close()
        return

    if data.startswith("ti_exp_"):
        t_num = int(data.split("_")[2])
        current_exp = admin_state[adm_id].get('edit_task_exp')
        admin_state[adm_id]['edit_task_exp'] = t_num if current_exp != t_num else None
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(adm_id))
        except: pass
        return

    if data.startswith("ti_edit_"):
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
        finally:
            conn.close()
        return

    if data.startswith("ti_yes_"):
        parts = data.split("_")
        t_num, msg_idx = int(parts[2]), int(parts[3])
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg = bot.send_message(call.message.chat.id, f"Input the new message for Task -{t_num} ;Message -{msg_idx}:", reply_markup=get_inline_cancel())
        admin_state[adm_id]['wait_ti'] = {'t_num': t_num, 'msg_idx': msg_idx}
        bot.register_next_step_handler(msg, step_update_task_msg)
        return

    if data.startswith("ti_del_sel_"):
        t_num = int(data.split("_")[3])
        admin_state[adm_id]['del_task'] = t_num
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(adm_id, t_num))
        except: pass
        return

    if data == "ti_del_sub":
        t_num = admin_state[adm_id].get('del_task')
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
            admin_state[adm_id]['del_task'] = None
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_task_edit_keyboard(adm_id))
            except: pass
            bot.answer_callback_query(call.id, "Task Deleted Successfully!", show_alert=True)
        finally:
            conn.close()
        return

# ==========================================
# 👑 ADMIN: TASK REVIEW / ASSIGN ORGANIZE HELPER
# ==========================================
def get_admin_grading_kb(sub_id, act=None):
    markup = InlineKeyboardMarkup(row_width=2)
    app_icon = "Approve✅" if act == "Approve" else "Approve"
    rej_icon = "Reject❌" if act == "Reject" else "Reject"
    markup.row(InlineKeyboardButton(app_icon, callback_data=f"gact_{sub_id}_Approve"), InlineKeyboardButton(rej_icon, callback_data=f"gact_{sub_id}_Reject"))
    markup.row(InlineKeyboardButton("💬 Feedback", callback_data=f"gfbk_{sub_id}"), InlineKeyboardButton("Submit", callback_data=f"gsub_{sub_id}"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

def process_admin_feedback(message, sub_id):
    adm_id = message.from_user.id
    if adm_id not in admin_state: admin_state[adm_id] = {}
    admin_state[adm_id]['feedback'] = message.text
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    prompt_id = admin_state.get(adm_id, {}).get('prompt_msg_id')
    if prompt_id:
        try: bot.delete_message(message.chat.id, prompt_id)
        except: pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        if sub:
            admin_state[adm_id]['task_msgs'] = []
            try:
                items = json.loads(sub['content_text'])
                for item in items:
                    if item.get('photo'):
                        if item.get('text') and len(item['text']) > 1024:
                            bot.send_photo(message.chat.id, item['photo'])
                            m = bot.send_message(message.chat.id, item['text'])
                        else:
                            m = bot.send_photo(message.chat.id, item['photo'], caption=item.get('text', ''))
                    else: m = bot.send_message(message.chat.id, item.get('text', ''))
                    admin_state[adm_id]['task_msgs'].append(m.message_id)
            except:
                if sub['photo_id']:
                    if sub['content_text'] and len(sub['content_text']) > 1024:
                        bot.send_photo(message.chat.id, sub['photo_id'])
                        m = bot.send_message(message.chat.id, sub['content_text'])
                    else:
                        m = bot.send_photo(message.chat.id, sub['photo_id'], caption=sub['content_text'])
                else: m = bot.send_message(message.chat.id, sub['content_text'])
                admin_state[adm_id]['task_msgs'].append(m.message_id)

            info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}\n\n📝 Feedback Added:\n{message.text}"
            act = admin_state[adm_id].get('action')
            markup = get_admin_grading_kb(sub_id, act)
            bot.send_message(message.chat.id, info_text, reply_markup=markup)
    finally:
        conn.close()

def finalize_grading(sub_id, act, feedback, adm_id, chat_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            bot.send_message(chat_id, "Submission not found!")
            return
            
        status_update = "Approved" if act == "Approve" else "Rejected"
        cursor.execute("UPDATE kbkh_submissions SET status = %s, feedback = %s WHERE id = %s", (status_update, feedback, sub_id))
        month_name = (sub['created_at'] + timedelta(hours=6)).strftime("%B")
        
        if act == "Approve":
            cursor.execute("INSERT INTO kbkh_task_records (telegram_id, month, task_done, task_total) VALUES (%s, %s, 1, 1) ON CONFLICT (telegram_id, month) DO UPDATE SET task_done = kbkh_task_records.task_done + 1, task_total = kbkh_task_records.task_total + 1", (sub['telegram_id'], month_name))
        else:
            cursor.execute("DELETE FROM kbkh_user_task_status WHERE telegram_id = %s AND task_num = %s", (sub['telegram_id'], sub['task_num']))
            
        conn.commit()
        
        base_msg = "We have reviewed your task and it has been ACCEPTED✅" if act == "Approve" else "Your task has been REJECTED❌"
        try:
            if feedback:
                try:
                    items = json.loads(sub['content_text'])
                    for item in items:
                        if item.get('photo'):
                            if item.get('text') and len(item['text']) > 1024:
                                bot.send_photo(sub['telegram_id'], item['photo'])
                                bot.send_message(sub['telegram_id'], item.get('text', ''))
                            else:
                                bot.send_photo(sub['telegram_id'], item['photo'], caption=item.get('text', ''))
                        else: bot.send_message(sub['telegram_id'], item.get('text', ''))
                except:
                    if sub['photo_id']:
                        if sub['content_text'] and len(sub['content_text']) > 1024:
                            bot.send_photo(sub['telegram_id'], sub['photo_id'])
                            bot.send_message(sub['telegram_id'], sub['content_text'])
                        else:
                            bot.send_photo(sub['telegram_id'], sub['photo_id'], caption=sub['content_text'])
                    else: bot.send_message(sub['telegram_id'], sub['content_text'])
                fb_msg = f"{base_msg}\n\n⏩ FEEDBACK: {feedback}"
                bot.send_message(sub['telegram_id'], fb_msg)
            else:
                bot.send_message(sub['telegram_id'], base_msg)
        except Exception as e:
            print("User notify error:", e)
            
        for m_id in admin_state.get(adm_id, {}).get('task_msgs', []):
            try: bot.delete_message(chat_id, m_id)
            except: pass
            
    finally:
        conn.close()
        
    if adm_id in admin_state:
        admin_state[adm_id].pop('action', None)
        admin_state[adm_id].pop('feedback', None)
        admin_state[adm_id].pop('grading_sub', None)
        admin_state[adm_id].pop('task_msgs', None)
        admin_state[adm_id].pop('prompt_msg_id', None)
        
    render_admin_submission_list(chat_id, message_id=None, is_completed=False)

def render_ta_assign_page(chat_id, message_id, adm_id):
    state = admin_state.get(adm_id, {}).get('assigning', {})
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_organized_tasks ORDER BY id ASC")
        orgs = cursor.fetchall()
    finally:
        conn.close()
        
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
        except: pass
    else:
        bot.send_message(chat_id, "Task Assign Menu:", reply_markup=markup)

def get_task_edit_keyboard(adm_id, sel_del_id=None):
    markup = InlineKeyboardMarkup()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT task_num, msg_1, msg_2, msg_3 FROM kbkh_tasks ORDER BY task_num")
        tasks = cursor.fetchall()
    finally:
        conn.close()
        
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
    markup.row(InlineKeyboardButton("Back", callback_data="ei_back"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

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
            except:
                failed.append(t)
                
        if success and not failed:
            cursor.execute("INSERT INTO kbkh_organized_tasks (sequence) VALUES (%s)", (seq,))
            bot.send_message(message.chat.id, "Task list added successfully✅")
        else:
            msg = ""
            if success: msg += f"Task {','.join(success)} added successfully✅\n"
            if failed: msg += f"Task {','.join(failed)} doesn't exist❌"
            bot.send_message(message.chat.id, msg)
        conn.commit()
    finally:
        conn.close()

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
    finally:
        conn.close()

def step_add_msg1(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state or 't_num' not in admin_state[adm_id]: return
    admin_state[adm_id]['msg_1'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    next_t = admin_state[adm_id]['t_num']
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"), InlineKeyboardButton("End", callback_data="ta_end_1"))
    msg = bot.send_message(message.chat.id, f"Give the first message of the Task -{next_t}:", reply_markup=markup)
    admin_state[adm_id]['clean_msgs'].append(msg.message_id)
    bot.register_next_step_handler(msg, step_add_msg2)

def step_add_msg2(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state or 't_num' not in admin_state[adm_id]: return
    admin_state[adm_id]['msg_2'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    next_t = admin_state[adm_id]['t_num']
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"), InlineKeyboardButton("End", callback_data="ta_end_2"))
    msg = bot.send_message(message.chat.id, f"Give the second message of the Task -{next_t}:", reply_markup=markup)
    admin_state[adm_id]['clean_msgs'].append(msg.message_id)
    bot.register_next_step_handler(msg, step_add_msg3)

def step_add_msg3(message):
    adm_id = message.from_user.id
    if adm_id not in admin_state: return
    admin_state[adm_id]['msg_3'] = message.text
    admin_state[adm_id]['clean_msgs'].append(message.message_id)
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Save and End Task", callback_data="ta_end_3"))
    msg = bot.send_message(message.chat.id, "All messages recorded. Press below to finalize.", reply_markup=markup)
    admin_state[adm_id]['clean_msgs'].append(msg.message_id)

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
    finally:
        conn.close()

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
    finally:
        conn.close()

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
        else:
            bot.send_message(chat_id, text, reply_markup=markup)
    finally:
        conn.close()

# ==========================================
# 🟢 GENERAL TASK HANDLERS (Assignments & Processing)
# ==========================================
@bot.message_handler(content_types=['text', 'photo'])
def handle_general_content(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID: return
        
    menu_items = ["Task", "Submit QnA", "Submit Article", "On Hold", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "Pending Article", "QnAKEY22", "PublisherKEY22", "ADMINKEY22", "WriterKEY22", "KBKh Team", "BKLn Team"]
    if message.content_type == 'text' and message.text in menu_items: return
        
    if tg_id in user_state and user_state[tg_id].get('waiting_btn'):
        bot.send_message(message.chat.id, "অনুগ্রহ করে পূর্বের মেসেজ এ \"Yes, No বা Cancel\" চেপে কমান্ড প্রদান করে পরবর্তী ধাপের কাজ করুন।")
        return

    flow = user_state.get(tg_id, {}).get('flow')
    
    # 📌 Submit Article Interceptors
    if flow == 'art_wait_web':
        if message.content_type != 'text':
            try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
            except: pass
            msg = bot.send_message(message.chat.id, "Invalid❌\nPlease provide the correct GOOGLE DOCUMENT LINK!\nCancel", reply_markup=get_inline_cancel())
            user_state[tg_id]['msg_id'] = msg.message_id
            return
            
        text = message.text
        if "docs.google.com" not in text:
            try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
            except: pass
            msg = bot.send_message(message.chat.id, "Invalid❌\nPlease provide the correct GOOGLE DOCUMENT LINK!\nCancel", reply_markup=get_inline_cancel())
            user_state[tg_id]['msg_id'] = msg.message_id
            return
            
        user_state[tg_id]['art_data'] = {'type': 'website_link', 'text': text}
        msg_text = f"{text}\n\n⚠️আপনি যে লিঙ্ক সাবমিট করেছেন সেটির View Access ঠিক আছে কি না তা নিশ্চিত হয়ে থাকলে \"Submit\" চাপুন।"
            
        try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
        except: pass
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit", callback_data="art_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        msg = bot.send_message(message.chat.id, msg_text, reply_markup=markup)
        user_state[tg_id]['msg_id'] = msg.message_id
        return
        
    elif flow == 'art_wait_grp_photo':
        if message.content_type != 'photo':
            try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
            except: pass
            msg = bot.send_message(message.chat.id, "Invalid ❌\n1. Submit your Article PHOTOCARD!", reply_markup=get_inline_cancel())
            user_state[tg_id]['msg_id'] = msg.message_id
            return
            
        user_state[tg_id]['art_data'] = {'photo': message.photo[-1].file_id}
        user_state[tg_id]['flow'] = 'art_wait_grp_text'
        try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
        except: pass
        msg = bot.send_message(message.chat.id, "2. Submit your Article TEXT:", reply_markup=get_inline_cancel())
        user_state[tg_id]['msg_id'] = msg.message_id
        return
        
    elif flow == 'art_wait_grp_text':
        if message.content_type != 'text':
            try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
            except: pass
            msg = bot.send_message(message.chat.id, "Invalid ❌\n2. Submit your Article TEXT!", reply_markup=get_inline_cancel())
            user_state[tg_id]['msg_id'] = msg.message_id
            return
            
        user_state[tg_id]['art_data']['text'] = message.text
        user_state[tg_id]['art_data']['type'] = 'groups'
        try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
        except: pass
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit", callback_data="art_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if len(message.text) <= 1024:
            msg = bot.send_photo(message.chat.id, user_state[tg_id]['art_data']['photo'], caption=message.text, reply_markup=markup)
        else:
            bot.send_photo(message.chat.id, user_state[tg_id]['art_data']['photo'])
            msg = bot.send_message(message.chat.id, message.text, reply_markup=markup)
        user_state[tg_id]['msg_id'] = msg.message_id
        return
        
    elif flow == 'art_wait_txt':
        if message.content_type != 'text': return
        user_state[tg_id]['art_data'] = {'type': 'text_only', 'text': message.text}
        try: bot.delete_message(message.chat.id, user_state[tg_id].get('msg_id'))
        except: pass
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit", callback_data="art_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        msg = bot.send_message(message.chat.id, f"{message.text}", reply_markup=markup)
        user_state[tg_id]['msg_id'] = msg.message_id
        return
    
    # QnA Flow Interceptor
    if flow == 'wait_q':
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['q_dict'] = {'text': caption, 'photo': photo_id}
        user_state[tg_id]['flow'] = 'wait_a'
        markup = get_inline_cancel()
        try:
            q_msg_id = user_state[tg_id].get('q_msg_id')
            if q_msg_id: bot.delete_message(message.chat.id, q_msg_id)
        except: pass
        a_msg = bot.send_message(message.chat.id, "Please submit your answer:", reply_markup=markup)
        user_state[tg_id]['a_msg_id'] = a_msg.message_id
        return
        
    if flow == 'wait_a':
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['a_dict'] = {'text': caption, 'photo': photo_id}
        user_state[tg_id]['flow'] = 'qna_preview'
        try:
            a_msg_id = user_state[tg_id].get('a_msg_id')
            if a_msg_id: bot.delete_message(message.chat.id, a_msg_id)
        except: pass
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit", callback_data="qna_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        send_qna_preview(message.chat.id, user_state[tg_id]['q_dict'], user_state[tg_id]['a_dict'], markup)
        return

    # Normal Tasks Check
    user = check_member_registration(tg_id)
    if not user: return
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT task_num FROM kbkh_active_assignments WHERE team_name = %s AND is_started = TRUE", (user['team_name'],))
        assign = cursor.fetchone()
        if not assign:
            bot.send_message(message.chat.id, "No Task available at this moment!")
            return
            
        active_task = assign['task_num']
        cursor.execute("SELECT completed FROM kbkh_user_task_status WHERE telegram_id = %s AND task_num = %s", (tg_id, active_task))
        uts = cursor.fetchone()
        
        if uts and uts['completed']:
            bot.send_message(message.chat.id, "You have already submitted the task once. Please wait for confirmation from the admin panel!")
            return
    finally:
        conn.close()

    user_state[tg_id] = {'task_num': active_task, 'collected': []}
    
    if active_task == 1 and message.content_type == 'text':
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text):
            bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
            return
        check_and_process_task_question(message, text, is_photo=False)
        
    elif active_task == 2 and message.content_type == 'photo':
        caption = message.caption
        if not caption:
            bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে অ্যাকশন।❌")
            return
        check_and_process_task_question(message, caption, is_photo=True, photo_id=message.photo[-1].file_id)
        
    elif active_task == 3 and message.content_type == 'photo':
        caption = message.caption
        if not caption or not re.search(r'http[s]?://', caption):
            bot.send_message(message.chat.id, "আপনি যে Article এর ওপর ভিত্তি করে Photocard তৈরি করেছেন, অনুগ্রহ করে ক্যাপশন হিসাবে উক্ত আর্টিকেল লিঙ্ক যুক্ত করে দিন। অন্যথায় টাস্ক গ্রহণ হবে না।❌")
            return
        user_state[tg_id]['single_sub'] = {'photo': message.photo[-1].file_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_photo(message.chat.id, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        
    elif active_task not in [1, 2, 3]:
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['single_sub'] = {'photo': photo_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if photo_id:
            if caption and len(caption) > 1024:
                bot.send_photo(message.chat.id, photo_id)
                bot.send_message(message.chat.id, caption, reply_markup=markup)
            else:
                bot.send_photo(message.chat.id, photo_id, caption=caption, reply_markup=markup)
        else: bot.send_message(message.chat.id, caption, reply_markup=markup)

def check_and_process_task_question(message, question_text, is_photo=False, photo_id=None):
    tg_id = message.from_user.id
    month_name = get_bd_time().strftime("%B")
    conn = get_db_connection()
    match, matched_line = None, ""
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        lines = [line.strip() for line in question_text.split('\n') if len(line.strip()) > 4]
        for line in lines:
            cursor.execute("""
                SELECT question_text, similarity(question_text, %s) as sim 
                FROM kbkh_question_bank 
                WHERE month = %s AND similarity(question_text, %s) > 0.35 
                ORDER BY sim DESC LIMIT 1
            """, (line, month_name, line))
            res = cursor.fetchone()
            if res:
                match, matched_line = res, line
                break
        if not match and len(lines) == 0:
            cursor.execute("""
                SELECT question_text, similarity(question_text, %s) as sim 
                FROM kbkh_question_bank 
                WHERE month = %s AND similarity(question_text, %s) > 0.35 
                ORDER BY sim DESC LIMIT 1
            """, (question_text, month_name, question_text))
            res = cursor.fetchone()
            if res: match, matched_line = res, question_text
    finally:
        conn.close()
    
    if match:
        user_state[tg_id]['temp_hold'] = {'q': question_text, 'p': photo_id}
        warn_msg = (f"↗️Your Question: {matched_line}\n\n↘️ Previously Submitted Question:\n{match['question_text']}\n\n"
                    f"⚠️দুইটি প্রশ্নের মধ্যে অনেকটা মিল পাওয়া গিয়েছে। তাই এটি পোস্ট করা যাবে লাল। "
                    f"আপনার যদি মনে হয় Ai ভুল করছে তাহলে 'Submit Anyway' Button চেপে সাবমিট করতে পারবেন।")
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Anyway", callback_data="force_add_q"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, warn_msg, reply_markup=markup)
    else:
        add_task_question_to_state(message.chat.id, tg_id, question_text, photo_id)

def add_task_question_to_state(chat_id, tg_id, text, photo_id=None):
    user_state[tg_id]['collected'].append({'text': text, 'photo': photo_id})
    user_state[tg_id]['waiting_btn'] = True 
    items = user_state[tg_id]['collected']
    for i in items:
        if i['photo']:
            if i['text'] and len(i['text']) > 1024:
                bot.send_photo(chat_id, i['photo'])
                bot.send_message(chat_id, i['text'])
            else:
                bot.send_photo(chat_id, i['photo'], caption=i['text'])
        else: bot.send_message(chat_id, i['text'])
    markup = InlineKeyboardMarkup(row_width=3)
    markup.row(InlineKeyboardButton("Yes", callback_data="add_more_q"), InlineKeyboardButton("No", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(chat_id, "Would you like to add any more questions?", reply_markup=markup)

def handle_next_task_question(message):
    tg_id = message.from_user.id
    if tg_id not in user_state: return
    active_task = user_state[tg_id].get('task_num')
    
    if active_task == 1:
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text):
            bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
            msg_box = bot.send_message(message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, handle_next_task_question)
            return
        check_and_process_task_question(message, text, False)
        
    elif active_task == 2:
        if message.content_type != 'photo' or not message.caption:
            bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
            msg_box = bot.send_message(message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
            bot.register_next_step_handler(msg_box, handle_next_task_question)
            return
        check_and_process_task_question(message, message.caption, True, message.photo[-1].file_id)

@bot.callback_query_handler(func=lambda call: call.data in ["add_more_q", "force_add_q", "final_submit_task"])
def task_flow_callbacks(call):
    tg_id = call.from_user.id
    try: bot.answer_callback_query(call.id)
    except: pass
    if tg_id in user_state: user_state[tg_id]['waiting_btn'] = False 
        
    if call.data == "force_add_q":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        temp = user_state[tg_id].pop('temp_hold', None)
        if temp: add_task_question_to_state(call.message.chat.id, tg_id, temp['q'], temp['p'])
            
    elif call.data == "add_more_q":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        msg_box = bot.send_message(call.message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, handle_next_task_question)
        
    elif call.data == "final_submit_task":
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
        finally:
            conn.close()
            
        user_state.pop(tg_id, None)
        bot.send_message(call.message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")

# ==========================================
# ⏰ BACKGROUND AUTO-TIMER
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
                
                all_teams_finished = True
                any_active = False
                force_end = False
                msg_updates = []
                
                for assign in assignments:
                    any_active = True
                    team = assign['team_name']
                    t_num = assign['task_num']
                    msg_lvl = assign['current_msg']
                    sched = assign['scheduled_for']
                    is_st = assign['is_started']
                    
                    if not is_st and now >= sched:
                        cursor.execute("UPDATE kbkh_active_assignments SET is_started = TRUE, current_msg = 1 WHERE id = %s", (assign['id'],))
                        cursor.execute("SELECT msg_1 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                        task_msgs = cursor.fetchone()
                        if task_msgs and task_msgs['msg_1']:
                            cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                            users = [u['telegram_id'] for u in cursor.fetchall()]
                            actions_to_take.append({'users': users, 'msg': task_msgs['msg_1']})
                        all_teams_finished = False
                        continue
                    
                    if not is_st:
                        all_teams_finished = False
                        continue 
                    
                    diff_hours = (now - sched).total_seconds() / 3600
                    cursor.execute("SELECT msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                    t_msgs = cursor.fetchone()
                    max_dur = 72 if t_msgs and t_msgs['msg_3'] else (48 if t_msgs and t_msgs['msg_2'] else 24)
                    
                    if diff_hours >= max_dur:
                        force_end = True
                        break
                        
                    cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                    total_members = cursor.fetchone()['count']
                    
                    cursor.execute("SELECT COUNT(DISTINCT s.telegram_id) FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE m.team_name = %s AND s.task_num = %s AND s.status = 'Approved'", (team, t_num))
                    done_members = cursor.fetchone()['count']
                    
                    if total_members == 0 or done_members < total_members:
                        all_teams_finished = False

                    cursor.execute("""
                        SELECT m.telegram_id FROM members m 
                        LEFT JOIN kbkh_user_task_status uts ON m.telegram_id = uts.telegram_id AND uts.task_num = %s
                        WHERE m.team_name = %s AND m.status = 'Approved' AND (uts.completed IS NULL OR uts.completed = FALSE)
                    """, (t_num, team))
                    pending_users = [u['telegram_id'] for u in cursor.fetchall()]

                    if diff_hours >= 24 and msg_lvl == 1 and t_msgs and t_msgs['msg_2']:
                        msg_updates.append((2, assign['id']))
                        actions_to_take.append({'users': pending_users, 'msg': t_msgs['msg_2']})
                    elif diff_hours >= 48 and msg_lvl == 2 and t_msgs and t_msgs['msg_3']:
                        msg_updates.append((3, assign['id']))
                        actions_to_take.append({'users': pending_users, 'msg': t_msgs['msg_3']})
                
                if any_active and (all_teams_finished or force_end):
                    users_to_notify = []
                    for assign in assignments:
                        cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (assign['team_name'],))
                        users_to_notify.extend([u['telegram_id'] for u in cursor.fetchall()])
                    actions_to_take.append({'users': list(set(users_to_notify)), 'msg': "Task END!\nThank you dear member♥️"})
                    cursor.execute("DELETE FROM kbkh_active_assignments")
                else:
                    for lvl, a_id in msg_updates:
                        cursor.execute("UPDATE kbkh_active_assignments SET current_msg = %s WHERE id = %s", (lvl, a_id))
                conn.commit()
            finally:
                conn.close()
                
            for action in actions_to_take:
                for uid in action['users']:
                    try: bot.send_message(uid, action['msg'])
                    except: pass
        except Exception as e:
            print("Timer Error:", e)
        time.sleep(60)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    timer_thread = threading.Thread(target=auto_task_timer)
    timer_thread.daemon = True
    timer_thread.start()
    print("🤖 KBKh Task Bot is Fast, Secure, and Fully Restored...")
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(5)
