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

# ==========================================
# ⚙️ CONFIGURATION & ENVIRONMENT
# ==========================================
BOT_TOKEN = "8868042763:AAHHKMQCQ8yFrF6OkrywTNoV4urwWFUdWys"
DB_URI = "postgresql://postgres.knktfswiljvqttbnlufg:%23%23RoKy5502%23%23@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
ADMIN_CHAT_ID = "8383532004"
PRIVATE_GROUP_ID = -1004465038452

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)
app = Flask(__name__)

@app.route('/')
def home():
    return "KBKh Task Bot (5 Doors) is Alive & Fast!", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

def get_bd_time():
    return datetime.utcnow() + timedelta(hours=6)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# ==========================================
# 🛠️ DATABASE SETUP (Fully Isolated)
# ==========================================
def init_db():
    conn = get_db_connection()
    try:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        
        # Original Task Tables
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
        """)

        # QnA & Tracking Tables
        cursor.execute("""
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
        """)
        
        # Insert Default Instructions for QnA Marking
        default_inst = {
            1: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!", 
            2: "উত্তরের মান অনেক বেশি উন্নত করা প্রয়োজন!",
            3: "উত্তরের মান উন্নত করা প্রয়োজন!", 
            4: "মোটামুটি ভালো হয়েছে। আরও ভালো করার চেষ্টা করতে হবে।",
            5: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।", 
            6: "উত্তরের মান বেশ ভালো। অবস্থান ধরে রাখতে হবে।"
        }
        for k, v in default_inst.items():
            try:
                cursor.execute("INSERT INTO kbkh_custom_instructions (id, instruction_text) VALUES (%s, %s) ON CONFLICT DO NOTHING", (k, v))
            except Exception:
                pass
                
    except Exception as e:
        print(f"DB Init Error: {e}")
    finally:
        conn.close()

init_db()

# State Dictionaries
user_state = {}
admin_state = {}

# ==========================================
# 🎹 KEYBOARDS (5 Doors)
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
    markup.add(KeyboardButton("Pending Articles"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def secondary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, is_persistent=True)
    markup.add(KeyboardButton("Members Status"))
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
        if mod and mod['is_blocked']:
            bot.send_message(message.chat.id, "Access Blocked⛔", reply_markup=ReplyKeyboardRemove())
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

@bot.message_handler(func=lambda msg: msg.text in ["QnAKEY22", "PublisherKEY22", "ADMINKEY22"])
def handle_secret_keys(message):
    tg_id = message.from_user.id
    user_state[tg_id] = {'login_flow': message.text}
    msg_box = bot.send_message(message.chat.id, "Please Enter Your Full Name:", reply_markup=get_inline_cancel())
    bot.register_next_step_handler(msg_box, process_door_login)

def process_door_login(message):
    tg_id = message.from_user.id
    if tg_id not in user_state or 'login_flow' not in user_state[tg_id]:
        return
        
    key = user_state[tg_id]['login_flow']
    user_state[tg_id]['mod_name'] = message.text.strip()
    
    if key == "QnAKEY22":
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(InlineKeyboardButton("Alpha", callback_data="qteam_Team Alpha"), 
                   InlineKeyboardButton("Beta", callback_data="qteam_Team Beta"), 
                   InlineKeyboardButton("Gamma", callback_data="qteam_Team Gamma"))
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
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    team = call.data.split("_")[1]
    name = user_state.get(tg_id, {}).get('mod_name', str(tg_id))
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO kbkh_qna_moderators (telegram_id, mod_name, team_name, is_active) 
            VALUES (%s, %s, %s, TRUE) 
            ON CONFLICT (telegram_id) DO UPDATE 
            SET is_active = TRUE, mod_name = %s, team_name = %s
        """, (tg_id, name, team, name, team))
        conn.commit()
        
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(call.message.chat.id, "Welcome Sir❤️\nYou are now in QnA Marking Team!", reply_markup=qna_marking_menu())
    finally:
        conn.close()
    user_state.pop(tg_id, None)

# ==========================================
# 🟢 SUBMIT QnA FLOW (General Members)
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Submit QnA")
def start_qna_submit(message):
    tg_id = message.from_user.id
    user = check_member_registration(tg_id)
    if not user:
        return
        
    user_state[tg_id] = {'flow': 'wait_q', 'q_dict': None, 'a_dict': None}
    bot.send_message(message.chat.id, "Please submit the question:", reply_markup=get_inline_cancel())

def send_qna_preview(chat_id, q_dict, a_dict, markup=None):
    q_txt = q_dict.get('text', '')
    q_pic = q_dict.get('photo')
    a_txt = a_dict.get('text', '')
    a_pic = a_dict.get('photo')
    
    if q_pic and not a_pic:
        bot.send_photo(chat_id, q_pic, caption=f"{q_txt}\n\nAnswer: {a_txt}"[:1024], reply_markup=markup)
    elif not q_pic and a_pic:
        bot.send_photo(chat_id, a_pic, caption=f"{q_txt}\n\nAnswer: {a_txt}"[:1024], reply_markup=markup)
    elif q_pic and a_pic:
        bot.send_photo(chat_id, q_pic, caption=q_txt)
        bot.send_photo(chat_id, a_pic, caption=f"Answer: {a_txt}"[:1024], reply_markup=markup)
    else:
        bot.send_message(chat_id, f"{q_txt}\n\nAnswer: {a_txt}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "qna_final_submit")
def process_qna_submit(call):
    tg_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    state = user_state.get(tg_id)
    if not state or state.get('flow') != 'qna_preview':
        return
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        mod_id = get_least_loaded_qna_mod()
        
        q_json = json.dumps(state['q_dict'], ensure_ascii=False)
        a_json = json.dumps(state['a_dict'], ensure_ascii=False)
        
        cursor.execute("INSERT INTO kbkh_qna_submissions (telegram_id, q_dict, a_dict, assigned_grader) VALUES (%s, %s, %s, %s)", (tg_id, q_json, a_json, mod_id))
        
        if mod_id:
            cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (mod_id,))
            
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
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Yes", callback_data="qna_res_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "⚠️Are you sure you want to resign?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "qna_res_yes")
def confirm_qna_resign(call):
    tg_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("UPDATE kbkh_qna_moderators SET is_active = FALSE, resign_count = resign_count + 1 WHERE telegram_id = %s", (tg_id,))
        cursor.execute("SELECT id FROM kbkh_qna_submissions WHERE assigned_grader = %s AND status = 'Pending'", (tg_id,))
        pending = cursor.fetchall()
        
        for p in pending:
            new_mod = get_least_loaded_qna_mod()
            cursor.execute("UPDATE kbkh_qna_submissions SET assigned_grader = %s WHERE id = %s", (new_mod, p['id']))
            if new_mod:
                cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                
        conn.commit()
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        
        user = check_member_registration(tg_id)
        if user:
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
        if not mod or not mod['is_active']:
            return
        
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
            if r['team_name'] in teams:
                teams[r['team_name']].append(r)
            
        markup = InlineKeyboardMarkup(row_width=1)
        exp_team = admin_state.get(tg_id, {}).get('qna_exp_team')
        
        for team in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if exp_team == team:
                markup.add(InlineKeyboardButton(f"🔺--{team}--🔺", callback_data=f"qna_tg_{team}"))
                for m in teams[team]:
                    markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"qna_user_{m['telegram_id']}"))
            else:
                markup.add(InlineKeyboardButton(f"🔻--{team}--🔻", callback_data=f"qna_tg_{team}"))
                
        markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        bot.send_message(message.chat.id, "Pending QnA List:", reply_markup=markup)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("qna_tg_"))
def toggle_qna_team(call):
    tg_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    team = call.data.split("_")[2]
    if tg_id not in admin_state:
        admin_state[tg_id] = {}
        
    current = admin_state[tg_id].get('qna_exp_team')
    admin_state[tg_id]['qna_exp_team'] = None if current == team else team
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
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
            if r['team_name'] in teams:
                teams[r['team_name']].append(r)
            
        markup = InlineKeyboardMarkup(row_width=1)
        exp_team = admin_state[tg_id]['qna_exp_team']
        
        for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if exp_team == t:
                markup.add(InlineKeyboardButton(f"🔺--{t}--🔺", callback_data=f"qna_tg_{t}"))
                for m in teams[t]:
                    markup.add(InlineKeyboardButton(f"{m['fb_name']} - {m['total']}", callback_data=f"qna_user_{m['telegram_id']}"))
            else:
                markup.add(InlineKeyboardButton(f"🔻--{t}--🔻", callback_data=f"qna_tg_{t}"))
                
        markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except:
            pass
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("qna_user_"))
def fetch_user_qna(call):
    mod_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    target_user = int(call.data.split("_")[2])
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    
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
            markup = get_qna_grading_kb(sub['id'])
            send_qna_preview(call.message.chat.id, q_dict, a_dict, markup)
    finally:
        conn.close()

def get_qna_grading_kb(sub_id, mark=None):
    markup = InlineKeyboardMarkup(row_width=7)
    btns = []
    for i in range(1, 7):
        btns.append(InlineKeyboardButton(f"{i}✅" if str(mark)==str(i) else str(i), callback_data=f"qm_sel_{sub_id}_{i}"))
    btns.append(InlineKeyboardButton("❌✅" if str(mark)=="0" else "❌", callback_data=f"qm_sel_{sub_id}_0"))
    
    markup.add(*btns)
    markup.row(InlineKeyboardButton("Submit&Feedback", callback_data=f"qm_subfb_{sub_id}"), InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub_id}"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("qm_sel_") or call.data.startswith("qm_sub_") or call.data.startswith("qm_subfb_"))
def qna_grading_actions(call):
    mod_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    if mod_id not in admin_state:
        admin_state[mod_id] = {}
        
    parts = call.data.split("_")
    action = parts[1]
    sub_id = int(parts[2])
    
    if action == "sel":
        mark = parts[3]
        admin_state[mod_id][f'qmark_{sub_id}'] = mark
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_qna_grading_kb(sub_id, mark))
        except:
            pass
        
    elif action == "subfb":
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        if not mark:
            return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
            
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
            
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, process_qna_feedback, sub_id)
        
    elif action == "sub":
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        if not mark:
            return bot.answer_callback_query(call.id, "Please select a mark first!", show_alert=True)
            
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
            
        finalize_qna_grading(sub_id, mark, None, mod_id)

def process_qna_feedback(message, sub_id):
    mod_id = message.from_user.id
    admin_state[mod_id][f'qfbk_{sub_id}'] = message.text
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kbkh_qna_submissions WHERE id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        q_dict = json.loads(sub['q_dict'])
        a_dict = json.loads(sub['a_dict'])
        
        mark = admin_state[mod_id].get(f'qmark_{sub_id}')
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit", callback_data=f"qm_sub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        cap_extra = f"\n\n✔️Marks Obtained - {mark}\n◀️Feedback: {message.text}"
        a_dict['text'] = a_dict.get('text', '') + cap_extra
        
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
        
        if feedback:
            cap_extra += f"\n\n◀️Feedback: {feedback}"
            
        a_dict['text'] = a_dict.get('text', '') + cap_extra
        
        try:
            send_qna_preview(sub['telegram_id'], q_dict, a_dict)
        except:
            pass
            
    finally:
        conn.close()
    
    if mod_id in admin_state:
        admin_state[mod_id].pop(f'qmark_{sub_id}', None)
        admin_state[mod_id].pop(f'qfbk_{sub_id}', None)

# ==========================================
# 📊 STATUS PANELS (Month Selector)
# ==========================================
def get_months_kb(prefix):
    markup = InlineKeyboardMarkup(row_width=3)
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    btns = []
    for m in months:
        btns.append(InlineKeyboardButton(m[:3], callback_data=f"{prefix}_{m}"))
    markup.add(*btns)
    markup.add(InlineKeyboardButton("Close", callback_data="cancel_action"))
    return markup

@bot.message_handler(func=lambda msg: msg.text in ["My Task Status", "Members Status"])
def status_selectors(message):
    tg_id = message.from_user.id
    if message.text == "My Task Status":
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("myts"))
    else:
        bot.send_message(message.chat.id, "🗓️Please Select Month:", reply_markup=get_months_kb("modst"))

@bot.callback_query_handler(func=lambda call: call.data.startswith("myts_") or call.data.startswith("modst_") or call.data.startswith("modstuser_") or call.data == "back_modst")
def status_callbacks(call):
    tg_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    if call.data == "back_modst":
        try:
            bot.edit_message_text("🗓️Please Select Month:", call.message.chat.id, call.message.message_id, reply_markup=get_months_kb("modst"))
        except:
            pass
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
            
            text = f"🗓️ Month - {month}\n\nSpecial Task- {tdone}/{ttot}\nQnA Mark - {qmark}"
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_inline_cancel())
            except:
                pass
        finally:
            conn.close()
            
    elif action == "modst":
        month = parts[1]
        if tg_id not in admin_state:
            admin_state[tg_id] = {}
        admin_state[tg_id]['modst_month'] = month
        admin_state[tg_id]['modst_exp'] = None 
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, month)
        
    elif action == "modstuser":
        u_id = int(parts[1])
        if tg_id not in admin_state:
            admin_state[tg_id] = {}
        current = admin_state[tg_id].get('modst_exp')
        admin_state[tg_id]['modst_exp'] = None if current == u_id else u_id
        render_members_status_list(call.message.chat.id, call.message.message_id, tg_id, admin_state[tg_id].get('modst_month'))

def render_members_status_list(chat_id, message_id, mod_id, month):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT telegram_id, fb_name, team_name FROM members WHERE status = 'Approved' ORDER BY team_name, fb_name")
        members = cursor.fetchall()
        
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for m in members:
            if m['team_name'] in teams:
                teams[m['team_name']].append(m)
                
        expanded_u = admin_state.get(mod_id, {}).get('modst_exp')
        text = f"🗓️ Month - {month}\n\n"
        
        markup = InlineKeyboardMarkup(row_width=1)
        for t in ['Team Alpha', 'Team Beta', 'Team Gamma']:
            if not teams[t]:
                continue
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
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            pass
    finally:
        conn.close()

# ==========================================
# 👑 MAIN ADMIN: MODERATORS PANEL
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Moderators")
def admin_moderators_panel(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        return
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
                if m['team_name'] in teams:
                    teams[m['team_name']].append(m)
            
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
            try:
                bot.edit_message_text("Admin Moderators Panel:", chat_id, message_id, reply_markup=markup)
            except:
                pass
        else:
            bot.send_message(chat_id, "Admin Moderators Panel:", reply_markup=markup)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("amod_") or call.data.startswith("amodblk_") or call.data.startswith("amodkck_"))
def admin_mod_actions(call):
    if str(call.from_user.id) != ADMIN_CHAT_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    if call.data == "amod_qna":
        if ADMIN_CHAT_ID not in admin_state:
            admin_state[ADMIN_CHAT_ID] = {}
        curr = admin_state[ADMIN_CHAT_ID].get('admin_mod_exp')
        admin_state[ADMIN_CHAT_ID]['admin_mod_exp'] = None if curr == 'qna' else 'qna'
        render_main_admin_mods(call.message.chat.id, call.message.message_id)
        
    elif call.data.startswith("amodblk_"):
        tg = int(call.data.split("_")[1])
        if ADMIN_CHAT_ID not in admin_state:
            admin_state[ADMIN_CHAT_ID] = {}
        admin_state[ADMIN_CHAT_ID]['mod_target'] = {'id': tg, 'action': 'block'}
        try:
            bot.answer_callback_query(call.id, "Block selected. Press Submit.", show_alert=True)
        except:
            pass
        
    elif call.data.startswith("amodkck_"):
        tg = int(call.data.split("_")[1])
        if ADMIN_CHAT_ID not in admin_state:
            admin_state[ADMIN_CHAT_ID] = {}
        admin_state[ADMIN_CHAT_ID]['mod_target'] = {'id': tg, 'action': 'kick'}
        try:
            bot.answer_callback_query(call.id, "Kick selected. Press Submit.", show_alert=True)
        except:
            pass
        
    elif call.data == "amod_sub":
        target = admin_state.get(ADMIN_CHAT_ID, {}).get('mod_target')
        if not target:
            return bot.answer_callback_query(call.id, "Select action first!", show_alert=True)
        
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
                    if new_mod:
                        cursor.execute("UPDATE kbkh_qna_moderators SET total_assigned = total_assigned + 1 WHERE telegram_id = %s", (new_mod,))
                try:
                    bot.send_message(target['id'], "You are not registered!❌", reply_markup=ReplyKeyboardRemove())
                except:
                    pass
            conn.commit()
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            bot.send_message(call.message.chat.id, "Action executed successfully!✅")
        finally:
            conn.close()
        admin_state[ADMIN_CHAT_ID].pop('mod_target', None)

# ==========================================
# 🟢 GENERAL TASK HANDLERS (Assignments & Processing)
# ==========================================
@bot.message_handler(content_types=['text', 'photo'])
def handle_general_content(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID:
        return
        
    menu_items = ["Task", "Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "QnAKEY22", "PublisherKEY22", "ADMINKEY22"]
    if message.content_type == 'text' and message.text in menu_items:
        return
        
    if tg_id in user_state and user_state[tg_id].get('waiting_btn'):
        bot.send_message(message.chat.id, "অনুগ্রহ করে পূর্বের মেসেজ এ \"Yes, No বা Cancel\" চেপে কমান্ড প্রদান করে পরবর্তী ধাপের কাজ করুন।")
        return
    
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
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Submit", callback_data="qna_final_submit"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        send_qna_preview(message.chat.id, user_state[tg_id]['q_dict'], user_state[tg_id]['a_dict'], markup)
        return

    # Normal Tasks Check
    user = check_member_registration(tg_id)
    if not user:
        return
        
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
            bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
            return
        check_and_process_task_question(message, caption, is_photo=True, photo_id=message.photo[-1].file_id)
        
    elif active_task == 3 and message.content_type == 'photo':
        caption = message.caption
        if not caption or not re.search(r'http[s]?://', caption):
            bot.send_message(message.chat.id, "আপনি যে Article এর ওপর ভিত্তি করে Photocard তৈরি করেছেন, অনুগ্রহ করে ক্যাপশন হিসাবে উক্ত আর্টিকেল লিঙ্ক যুক্ত করে দিন। অন্যথায় টাস্ক গ্রহণ হবে না।❌")
            return
            
        user_state[tg_id]['single_sub'] = {'photo': message.photo[-1].file_id, 'caption': caption}
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_photo(message.chat.id, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        
    elif active_task not in [1, 2, 3]:
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['single_sub'] = {'photo': photo_id, 'caption': caption}
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        
        if photo_id:
            bot.send_photo(message.chat.id, photo_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, caption, reply_markup=markup)

def check_and_process_task_question(message, question_text, is_photo=False, photo_id=None):
    tg_id = message.from_user.id
    month_name = get_bd_time().strftime("%B")
    conn = get_db_connection()
    match = None
    matched_line = ""
    
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
                match = res
                matched_line = line
                break
                
        if not match and len(lines) == 0:
            cursor.execute("""
                SELECT question_text, similarity(question_text, %s) as sim 
                FROM kbkh_question_bank 
                WHERE month = %s AND similarity(question_text, %s) > 0.35 
                ORDER BY sim DESC LIMIT 1
            """, (question_text, month_name, question_text))
            res = cursor.fetchone()
            if res:
                match = res
                matched_line = question_text
    finally:
        conn.close()
    
    if match:
        user_state[tg_id]['temp_hold'] = {'q': question_text, 'p': photo_id}
        warn_msg = (f"↗️Your Question: {matched_line}\n\n"
                    f"↘️ Previously Submitted Question:\n{match['question_text']}\n\n"
                    f"⚠️দুইটি প্রশ্নের মধ্যে অনেকটা মিল পাওয়া গিয়েছে। তাই এটি পোস্ট করা যাবে না। "
                    f"আপনার যদি মনে হয় Ai ভুল করছে তাহলে 'Submit Anyway' Button চেপে সাবমিট করতে পারবেন।")
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Submit Anyway", callback_data="force_add_q"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, warn_msg, reply_markup=markup)
    else:
        add_task_question_to_state(message.chat.id, tg_id, question_text, photo_id)

def add_task_question_to_state(chat_id, tg_id, text, photo_id=None):
    user_state[tg_id]['collected'].append({'text': text, 'photo': photo_id})
    user_state[tg_id]['waiting_btn'] = True 
    
    items = user_state[tg_id]['collected']
    for i in items:
        if i['photo']:
            bot.send_photo(chat_id, i['photo'], caption=i['text'])
        else:
            bot.send_message(chat_id, i['text'])
            
    markup = InlineKeyboardMarkup(row_width=3)
    markup.row(InlineKeyboardButton("Yes", callback_data="add_more_q"), InlineKeyboardButton("No", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(chat_id, "Would you like to add any more questions?", reply_markup=markup)

def handle_next_task_question(message):
    tg_id = message.from_user.id
    if tg_id not in user_state:
        return
        
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
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    if tg_id in user_state:
        user_state[tg_id]['waiting_btn'] = False 
        
    if call.data == "force_add_q":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        temp = user_state[tg_id].pop('temp_hold', None)
        if temp:
            add_task_question_to_state(call.message.chat.id, tg_id, temp['q'], temp['p'])
            
    elif call.data == "add_more_q":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        msg_box = bot.send_message(call.message.chat.id, "Please add the next question:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, handle_next_task_question)
        
    elif call.data == "final_submit_task":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
            
        state = user_state.get(tg_id, {})
        t_num = state.get('task_num')
        if not t_num:
            return
            
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            month_name = get_bd_time().strftime("%B")
            
            if 'single_sub' in state:
                cursor.execute("INSERT INTO kbkh_submissions (telegram_id, task_num, content_text, photo_id) VALUES (%s, %s, %s, %s)", (tg_id, t_num, state['single_sub']['caption'], state['single_sub']['photo']))
            elif 'collected' in state:
                full_content = json.dumps(state['collected'], ensure_ascii=False)
                cursor.execute("INSERT INTO kbkh_submissions (telegram_id, task_num, content_text) VALUES (%s, %s, %s)", (tg_id, t_num, full_content))
                for q in state['collected']:
                    cursor.execute("INSERT INTO kbkh_question_bank (telegram_id, task_num, question_text, month) VALUES (%s, %s, %s, %s)", (tg_id, t_num, q['text'], month_name))
                    
            cursor.execute("INSERT INTO kbkh_user_task_status (telegram_id, task_num, completed) VALUES (%s, %s, TRUE) ON CONFLICT (telegram_id, task_num) DO UPDATE SET completed = TRUE", (tg_id, t_num))
            conn.commit()
        finally:
            conn.close()
            
        user_state.pop(tg_id, None)
        bot.send_message(call.message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")

# ==========================================
# 👑 ADMIN: TASK REVIEW (FLAT LIST) & LOGIC
# ==========================================
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
            else:
                bot.send_message(chat_id, msg, reply_markup=get_inline_cancel())
            return
            
        teams = {'Team Alpha': [], 'Team Beta': [], 'Team Gamma': []}
        for r in records:
            t_name = r.get('team_name', 'Team Alpha')
            if t_name in teams:
                teams[t_name].append(r)
            
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

@bot.callback_query_handler(func=lambda call: call.data in ["adm_tsub", "adm_tcomp", "adm_back"] or call.data.startswith("grd_") or call.data.startswith("gact_") or call.data.startswith("gfbk_") or call.data.startswith("gsub_") or call.data == "ignore")
def admin_grading_actions(call):
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
        
    if call.data == "ignore":
        return
    
    if call.data == "adm_back":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Task Submitted", callback_data="adm_tsub"), InlineKeyboardButton("Task Completed", callback_data="adm_tcomp"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        try:
            bot.edit_message_text("Task Menu:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except:
            pass
        
    elif call.data in ["adm_tsub", "adm_tcomp"]:
        is_completed = (call.data == "adm_tcomp")
        if ADMIN_CHAT_ID not in admin_state:
            admin_state[ADMIN_CHAT_ID] = {}
        render_admin_submission_list(call.message.chat.id, call.message.message_id, is_completed)
        
    elif call.data.startswith("grd_"):
        sub_id = int(call.data.split("_")[1])
        conn = get_db_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return
            
            if ADMIN_CHAT_ID not in admin_state:
                admin_state[ADMIN_CHAT_ID] = {}
            admin_state[ADMIN_CHAT_ID]['grading_sub'] = sub_id
            admin_state[ADMIN_CHAT_ID]['action'] = None
            
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            
            try:
                items = json.loads(sub['content_text'])
                for item in items:
                    if item.get('photo'):
                        bot.send_photo(call.message.chat.id, item['photo'], caption=item.get('text', ''))
                    else:
                        bot.send_message(call.message.chat.id, item.get('text', ''))
            except:
                if sub['photo_id']:
                    bot.send_photo(call.message.chat.id, sub['photo_id'], caption=sub['content_text'])
                else:
                    bot.send_message(call.message.chat.id, sub['content_text'])
                
            info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}"
            markup = get_admin_grading_kb(sub_id)
            bot.send_message(call.message.chat.id, info_text, reply_markup=markup)
        finally:
            conn.close()
        
    elif call.data.startswith("gact_"):
        parts = call.data.split("_")
        sub_id, act = int(parts[1]), parts[2]
        admin_state[ADMIN_CHAT_ID]['action'] = act
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_grading_kb(sub_id, act))
        except:
            pass
        
    elif call.data.startswith("gfbk_"):
        sub_id = int(call.data.split("_")[1])
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        msg_box = bot.send_message(call.message.chat.id, "Please write feedback:", reply_markup=get_inline_cancel())
        bot.register_next_step_handler(msg_box, process_admin_feedback, sub_id)
        
    elif call.data.startswith("gsub_"):
        sub_id = int(call.data.split("_")[1])
        act = admin_state.get(ADMIN_CHAT_ID, {}).get('action')
        feedback = admin_state.get(ADMIN_CHAT_ID, {}).get('feedback')
        
        if not act:
            return bot.answer_callback_query(call.id, "Select Approve or Reject!", show_alert=True)
            
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        finalize_grading(sub_id, act, feedback, call.message.chat.id)

def get_admin_grading_kb(sub_id, action=None):
    markup = InlineKeyboardMarkup(row_width=2)
    ap_btn = "Approve✅" if action == "approve" else "Approve"
    rj_btn = "Reject✅" if action == "reject" else "Reject"
    markup.row(InlineKeyboardButton(ap_btn, callback_data=f"gact_{sub_id}_approve"), InlineKeyboardButton(rj_btn, callback_data=f"gact_{sub_id}_reject"))
    markup.add(InlineKeyboardButton("- Feedback -", callback_data=f"gfbk_{sub_id}"))
    markup.row(InlineKeyboardButton("Submit", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    return markup

def process_admin_feedback(message, sub_id):
    admin_state[ADMIN_CHAT_ID]['feedback'] = message.text
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        info_text = f"Name: {sub['fb_name']}\nTeam: {sub['team_name']}\n◀️Feedback: {message.text}"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("Send", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, info_text, reply_markup=markup)
    finally:
        conn.close()

def finalize_grading(sub_id, status_act, feedback, admin_chat_id):
    # Fixed Memory Leak
    if ADMIN_CHAT_ID in admin_state:
        admin_state[ADMIN_CHAT_ID].pop('feedback', None) 
        admin_state[ADMIN_CHAT_ID].pop('action', None)
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM kbkh_submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
        sub = cursor.fetchone()
        
        try:
            items = json.loads(sub['content_text'])
            cap = "\n\n".join([i['text'] for i in items])
        except:
            cap = sub['content_text']

        if status_act == "approve":
            cursor.execute("UPDATE kbkh_submissions SET status = 'Approved' WHERE id = %s", (sub_id,))
            
            if feedback:
                user_msg = f"{cap}\n\n🔺Task Status: Complete✅\n\n◀️Feedback: {feedback}"
                if sub['photo_id']:
                    bot.send_photo(sub['telegram_id'], sub['photo_id'], caption=user_msg)
                else:
                    bot.send_message(sub['telegram_id'], user_msg)
            else:
                bot.send_message(sub['telegram_id'], "Your task has been successfully reviewed and marked as completed!✅")
                
            if sub['task_num'] == 3:
                fwd_cap = f"{cap}\nName: {sub['fb_name']}"
                try:
                    if sub['photo_id']:
                        bot.send_photo(PRIVATE_GROUP_ID, sub['photo_id'], caption=fwd_cap)
                    else:
                        bot.send_message(PRIVATE_GROUP_ID, fwd_cap)
                except Exception as e:
                    print("Forward Error:", e)
        else:
            cursor.execute("DELETE FROM kbkh_submissions WHERE id = %s", (sub_id,))
            cursor.execute("UPDATE kbkh_user_task_status SET completed = FALSE WHERE telegram_id = %s AND task_num = %s", (sub['telegram_id'], sub['task_num']))
            user_msg = f"{cap}\n\n🔺Task Status: Failed❌\n\n"
            if feedback:
                user_msg += f"◀️Feedback: {feedback}"
            else:
                user_msg += "Please try again. If the issue persists, contact a senior team member for assistance."
                
            if sub['photo_id']:
                bot.send_photo(sub['telegram_id'], sub['photo_id'], caption=user_msg)
            else:
                bot.send_message(sub['telegram_id'], user_msg)
        
        conn.commit()
        render_admin_submission_list(admin_chat_id, None, False)
        
        # Realtime Auto-End Check
        if status_act == "approve":
            cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (sub['team_name'],))
            total_m = cursor.fetchone()['count']
            
            cursor.execute("""
                SELECT COUNT(DISTINCT s.telegram_id) FROM kbkh_submissions s
                JOIN members m ON s.telegram_id = m.telegram_id
                WHERE m.team_name = %s AND s.task_num = %s AND s.status = 'Approved'
            """, (sub['team_name'], sub['task_num']))
            done_m = cursor.fetchone()['count']
            
            if total_m > 0 and done_m >= total_m:
                cursor.execute("DELETE FROM kbkh_active_assignments WHERE team_name = %s AND task_num = %s", (sub['team_name'], sub['task_num']))
                cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (sub['team_name'],))
                for u in cursor.fetchall():
                    try:
                        bot.send_message(u['telegram_id'], "Task END!\nThank you dear member♥️")
                    except:
                        pass
                conn.commit()
                
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data == "cancel_action")
def simple_cancel(call):
    tg_id = call.from_user.id
    user_state.pop(tg_id, None)
    if tg_id in admin_state:
        admin_state[tg_id].pop('feedback', None) 
        admin_state[tg_id].pop('action', None)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except:
        pass

# ==========================================
# ⏰ BACKGROUND AUTO-TIMER
# ==========================================
def auto_task_timer():
    while True:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM kbkh_active_assignments")
            assignments = cursor.fetchall()
            now = get_bd_time()
            
            for assign in assignments:
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
                        for u in cursor.fetchall():
                            try:
                                bot.send_message(u['telegram_id'], task_msgs['msg_1'])
                            except:
                                pass
                    continue
                
                if not is_st:
                    continue 
                
                cursor.execute("SELECT COUNT(*) FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                total_members = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(DISTINCT telegram_id) FROM kbkh_submissions WHERE team_name = %s AND task_num = %s AND status = 'Approved'", (team, t_num))
                done_members = cursor.fetchone()['count']
                
                diff_hours = (now - sched).total_seconds() / 3600
                
                # Check Auto-End on Timeout (72h) or 100% completion
                if (total_members > 0 and done_members >= total_members) or (diff_hours >= 72):
                    cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s AND status = 'Approved'", (team,))
                    for u in cursor.fetchall():
                        try:
                            bot.send_message(u['telegram_id'], "Task END!\nThank you dear member♥️")
                        except:
                            pass
                    cursor.execute("DELETE FROM kbkh_active_assignments WHERE id = %s", (assign['id'],))
                    continue

                cursor.execute("SELECT msg_2, msg_3 FROM kbkh_tasks WHERE task_num = %s", (t_num,))
                t_msgs = cursor.fetchone()
                
                cursor.execute("""
                    SELECT m.telegram_id FROM members m 
                    LEFT JOIN kbkh_user_task_status uts ON m.telegram_id = uts.telegram_id AND uts.task_num = %s
                    WHERE m.team_name = %s AND m.status = 'Approved' AND (uts.completed IS NULL OR uts.completed = FALSE)
                """, (t_num, team))
                pending_users = cursor.fetchall()

                if diff_hours >= 24 and msg_lvl == 1 and t_msgs and t_msgs['msg_2']:
                    for u in pending_users:
                        try:
                            bot.send_message(u['telegram_id'], t_msgs['msg_2'])
                        except:
                            pass
                    cursor.execute("UPDATE kbkh_active_assignments SET current_msg = 2 WHERE id = %s", (assign['id'],))
                    
                elif diff_hours >= 48 and msg_lvl == 2 and t_msgs and t_msgs['msg_3']:
                    for u in pending_users:
                        try:
                            bot.send_message(u['telegram_id'], t_msgs['msg_3'])
                        except:
                            pass
                    cursor.execute("UPDATE kbkh_active_assignments SET current_msg = 3 WHERE id = %s", (assign['id'],))
                    
            conn.commit()
        except Exception as e:
            print("Timer Error:", e)
        finally: 
            if conn:
                conn.close()
        time.sleep(60)

# 🚧 COMING SOON
@bot.message_handler(func=lambda msg: msg.text in ["Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "Moderators"])
def coming_soon(message):
    bot.send_message(message.chat.id, "⏳ This feature is Coming Soon!")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_task_timer, daemon=True).start()
    print("🤖 KBKh Task Bot is Fast, Secure, and Fully Isolated...")
    try:
        bot.remove_webhook()
        time.sleep(2)
    except:
        pass
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(e)
            time.sleep(5)
