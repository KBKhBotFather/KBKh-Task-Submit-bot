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

# ⚙️ Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8868042763:AAHHKMQCQ8yFrF6OkrywTNoV4urwWFUdWys").strip()
DB_URI = os.environ.get("DATABASE_URL", "postgresql://postgres.knktfswiljvqttbnlufg:%23%23RoKy5502%23%23@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_ID", "8383532004").strip()
PRIVATE_GROUP_ID = -1004465038452

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=10)
app = Flask(__name__)

@app.route('/')
def home(): return "KBKh Task Bot (5 Doors) is Alive!", 200
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

def get_bd_time(): return datetime.utcnow() + timedelta(hours=6)
def get_db_connection(): return psycopg2.connect(DB_URI)

# 🛠️ Database Setup (Merged with BKLn structures)
def init_db():
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_assignments (
                id SERIAL PRIMARY KEY, team_name TEXT, task_num INT, 
                scheduled_for TIMESTAMP, is_started BOOLEAN DEFAULT FALSE, current_msg INT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, content_type TEXT,
                content_text TEXT, photo_id TEXT, status TEXT DEFAULT 'Pending',
                feedback TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY, task_num INT UNIQUE, msg_1 TEXT, msg_2 TEXT, msg_3 TEXT
            );
            CREATE TABLE IF NOT EXISTS organized_tasks (
                id SERIAL PRIMARY KEY, sequence TEXT
            );
            CREATE TABLE IF NOT EXISTS custom_instructions (
                id INT PRIMARY KEY, instruction_text TEXT
            );
            CREATE TABLE IF NOT EXISTS question_bank (
                id SERIAL PRIMARY KEY, telegram_id BIGINT, task_num INT, 
                question_text TEXT, month TEXT
            );
            CREATE TABLE IF NOT EXISTS user_task_status (
                telegram_id BIGINT, task_num INT, completed BOOLEAN DEFAULT FALSE, UNIQUE(telegram_id, task_num)
            );
        """)
        conn.close()
    except Exception as e: print(f"DB Init Error: {e}")

init_db()
user_state = {}
admin_state = {}

# ==========================================
# 🎹 KEYBOARDS
# ==========================================
def member_main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Task"))
    markup.add(KeyboardButton("Submit QnA"), KeyboardButton("Submit Article"))
    markup.add(KeyboardButton("My Task Status"))
    return markup

def primary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Task"), KeyboardButton("Task Assign"))
    markup.add(KeyboardButton("Edit Instructions"), KeyboardButton("Triggered Task"))
    markup.add(KeyboardButton("Reset Task Data"), KeyboardButton("Moderators"))
    return markup

def qna_marking_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Pending QnA"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def article_publish_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Pending Articles"), KeyboardButton("Members Status"))
    markup.add(KeyboardButton("Resign⚠️"))
    return markup

def secondary_admin_menu():
    markup = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(KeyboardButton("Members Status"))
    return markup

def get_inline_cancel(): return InlineKeyboardMarkup().add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))

# ==========================================
# 🚪 MULTI-DOOR LOGIN & CHECK
# ==========================================
def check_member_registration(tg_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT fb_name, team_name, status FROM members WHERE telegram_id = %s AND status = 'Approved' AND is_blocked = FALSE AND is_removed = FALSE", (tg_id,))
    user = cursor.fetchone()
    conn.close()
    return user

@bot.message_handler(commands=['start'])
def send_welcome(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Primary Admin Panel!", reply_markup=primary_admin_menu())
        return
        
    user = check_member_registration(tg_id)
    if user:
        bot.send_message(message.chat.id, f"Welcome to KBKh Bot Ecosystem, {user['fb_name']}!\nYou are in {user['team_name']}.", reply_markup=member_main_menu())
    else:
        bot.send_message(message.chat.id, "You are not registered yet❌\nPlease register from the Registration Bot first.", reply_markup=ReplyKeyboardRemove())

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
    
    if key == "QnAKEY22": bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in QnA Marking Team!", reply_markup=qna_marking_menu())
    elif key == "PublisherKEY22": bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Article Publish Team!", reply_markup=article_publish_menu())
    elif key == "ADMINKEY22": bot.send_message(message.chat.id, "Welcome Sir❤️\nYou are now in the Secondary Admin Panel!", reply_markup=secondary_admin_menu())
    user_state.pop(tg_id, None)

# ==========================================
# 📝 GENERAL MEMBER: TASK SYSTEM (1, 2, 3 & Normal)
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Task")
def handle_task_button(message):
    tg_id = message.from_user.id
    user = check_member_registration(tg_id)
    if not user: return
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT task_num, current_msg FROM active_assignments WHERE team_name = %s AND is_started = TRUE", (user['team_name'],))
    assign = cursor.fetchone()
    
    if not assign:
        bot.send_message(message.chat.id, "No Task available at this moment!")
    else:
        cursor.execute("SELECT completed FROM user_task_status WHERE telegram_id = %s AND task_num = %s", (tg_id, assign['task_num']))
        uts = cursor.fetchone()
        if uts and uts['completed']:
            cursor.execute("SELECT status FROM submissions WHERE telegram_id = %s AND task_num = %s ORDER BY id DESC LIMIT 1", (tg_id, assign['task_num']))
            sub_status = cursor.fetchone()
            if sub_status and sub_status['status'] == 'Pending':
                bot.send_message(message.chat.id, "Task submitted successfully!\nPlease wait for confirmation.")
            else:
                bot.send_message(message.chat.id, "Your task has been successfully reviewed and marked as completed!✅")
        else:
            cursor.execute("SELECT msg_1, msg_2, msg_3 FROM tasks WHERE task_num = %s", (assign['task_num'],))
            t_data = cursor.fetchone()
            msgs = []
            if t_data['msg_1'] and assign['current_msg'] >= 1: msgs.append(t_data['msg_1'])
            if t_data['msg_2'] and assign['current_msg'] >= 2: msgs.append(t_data['msg_2'])
            if t_data['msg_3'] and assign['current_msg'] >= 3: msgs.append(t_data['msg_3'])
            bot.send_message(message.chat.id, "\n\n".join(msgs))
    conn.close()

@bot.message_handler(content_types=['text', 'photo'])
def handle_general_submissions(message):
    tg_id = message.from_user.id
    if str(tg_id) == ADMIN_CHAT_ID: return
    if message.content_type == 'text' and message.text in ["Task", "Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles"]: return
    
    user = check_member_registration(tg_id)
    if not user: return
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT task_num FROM active_assignments WHERE team_name = %s AND is_started = TRUE", (user['team_name'],))
    assign = cursor.fetchone()
    
    if not assign:
        conn.close()
        return bot.send_message(message.chat.id, "No Task available at this moment!")
        
    active_task = assign['task_num']
    cursor.execute("SELECT completed FROM user_task_status WHERE telegram_id = %s AND task_num = %s", (tg_id, active_task))
    uts = cursor.fetchone()
    conn.close()
    
    if uts and uts['completed']:
        return bot.send_message(message.chat.id, "You have already submitted the task once. Please wait for confirmation from the admin panel!")

    user_state[tg_id] = {'task_num': active_task, 'collected': []}
    
    # Task 1: Text Questions
    if active_task == 1 and message.content_type == 'text':
        text = message.text.strip()
        if not re.match(r'^[\d১-৯][\.\/]', text): return bot.send_message(message.chat.id, "দয়াকরে 1,2,3 এভাবে সিরিয়াল এ করে দিন")
        check_and_process_question(message, text, is_photo=False)
        
    # Task 2: Photo Questions
    elif active_task == 2 and message.content_type == 'photo':
        caption = message.caption
        if not caption: return bot.send_message(message.chat.id, "ছবি এর সাথে ক্যাপশন হিসাবে আপনার তৈরি করা প্রশ্নটি যুক্ত করতে হবে। অন্যথায় গ্রহণযোগ্য হবে না।❌")
        check_and_process_question(message, caption, is_photo=True, photo_id=message.photo[-1].file_id)

    # Task 3: Photocard + Link
    elif active_task == 3 and message.content_type == 'photo':
        caption = message.caption
        if not caption or not re.search(r'http[s]?://', caption):
            return bot.send_message(message.chat.id, "আপনি যে Article এর ওপর ভিত্তি করে Photocard তৈরি করেছেন, অনুগ্রহ করে ক্যাপশন হিসাবে উক্ত আর্টিকেল লিঙ্ক যুক্ত করে দিন। অন্যথায় টাস্ক গ্রহণ হবে না।❌")
        
        user_state[tg_id]['single_sub'] = {'photo': message.photo[-1].file_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_photo(message.chat.id, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        
    # Normal Tasks
    elif active_task not in [1, 2, 3]:
        photo_id = message.photo[-1].file_id if message.content_type == 'photo' else None
        caption = message.caption if message.content_type == 'photo' else message.text
        user_state[tg_id]['single_sub'] = {'photo': photo_id, 'caption': caption}
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Task", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        if photo_id: bot.send_photo(message.chat.id, photo_id, caption=caption, reply_markup=markup)
        else: bot.send_message(message.chat.id, caption, reply_markup=markup)

def check_and_process_question(message, question_text, is_photo=False, photo_id=None):
    tg_id = message.from_user.id
    month_name = get_bd_time().strftime("%B")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT question_text, similarity(question_text, %s) as sim FROM question_bank WHERE month = %s AND similarity(question_text, %s) > 0.75 ORDER BY sim DESC LIMIT 1", (question_text, month_name, question_text))
    match = cursor.fetchone()
    conn.close()
    
    if match:
        user_state[tg_id]['temp_hold'] = {'q': question_text, 'p': photo_id}
        warn_msg = f"↗️Your Question: {question_text}\n\n↘️Previously Submitted Question:\n{match['question_text']}\n\n⚠️দুইটি প্রশ্নের মধ্যে প্রায় ৮০% মিল পাওয়া গিয়েছে। তাই এটি পোস্ট করা যাবে না। আপনার যদি মনে হয় Ai ভুল করছে তাহলে 'Submit Anyway' Button চেপে সাবমিট করতে পারবেন।"
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Submit Anyway", callback_data="force_add_q"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.send_message(message.chat.id, warn_msg, reply_markup=markup)
    else:
        add_question_to_state(message.chat.id, tg_id, question_text, photo_id)

def add_question_to_state(chat_id, tg_id, text, photo_id=None):
    user_state[tg_id]['collected'].append({'text': text, 'photo': photo_id})
    items = user_state[tg_id]['collected']
    msg = ""
    for item in items:
        if item['photo']: msg += f"[ছবি]\n{item['text']}\n\n"
        else: msg += f"{item['text']}\n"
    msg += "Would you like to add any more questions?"
    markup = InlineKeyboardMarkup(row_width=3).row(InlineKeyboardButton("Yes", callback_data="add_more_q"), InlineKeyboardButton("No", callback_data="final_submit_task"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
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
        if not t_num: return
        
        conn = get_db_connection()
        cursor = conn.cursor()
        month_name = get_bd_time().strftime("%B")
        
        if 'single_sub' in state:
            cursor.execute("INSERT INTO submissions (telegram_id, task_num, content_text, photo_id) VALUES (%s, %s, %s, %s)", (tg_id, t_num, state['single_sub']['caption'], state['single_sub']['photo']))
        elif 'collected' in state:
            full_text = "\n\n".join([i['text'] for i in state['collected']])
            # Get the photo id of the first collected item (if it's task 2)
            first_photo = state['collected'][0]['photo'] if state['collected'] else None
            cursor.execute("INSERT INTO submissions (telegram_id, task_num, content_text, photo_id) VALUES (%s, %s, %s, %s)", (tg_id, t_num, full_text, first_photo))
            for q in state['collected']:
                cursor.execute("INSERT INTO question_bank (telegram_id, task_num, question_text, month) VALUES (%s, %s, %s, %s)", (tg_id, t_num, q['text'], month_name))
                
        cursor.execute("INSERT INTO user_task_status (telegram_id, task_num, completed) VALUES (%s, %s, TRUE) ON CONFLICT (telegram_id, task_num) DO UPDATE SET completed = TRUE", (tg_id, t_num))
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
# 👑 ADMIN: TASK ASSIGN, TRIGGER, RESET (From BKLn)
# ==========================================
@bot.message_handler(func=lambda msg: msg.text == "Task Assign")
def task_assign_menu(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Add Task", callback_data="ta_add"), InlineKeyboardButton("Task List", callback_data="ta_list"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "Task Assign Menu:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "Triggered Task")
def triggered_task_menu(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT team_name, task_num, is_started FROM active_assignments ORDER BY id ASC")
    assigns = cursor.fetchall()
    conn.close()
    
    if not assigns: return bot.send_message(message.chat.id, "No Task Triggered!")
    
    is_st = any(a['is_started'] for a in assigns)
    text = "".join([f"{a['team_name']} - Task {a['task_num']}\n" for a in assigns])
    text += f"\nTask Status: {'Started!🟢' if is_st else 'Not Assigned yet!🔴'}"
    
    markup = InlineKeyboardMarkup(row_width=2)
    if not is_st: markup.add(InlineKeyboardButton("Stop Task", callback_data="ta_stop"))
    else: markup.add(InlineKeyboardButton("End", callback_data="ta_force_end"))
    markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "Reset Task Data")
def reset_data_menu(message):
    if str(message.from_user.id) != ADMIN_CHAT_ID: return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Yes", callback_data="reset_task_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
    bot.send_message(message.chat.id, "Are you sure you want to reset all Task Data?", reply_markup=markup)

# Admin Action Callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith("ta_") or call.data == "reset_task_yes")
def admin_task_actions(call):
    adm_id = call.from_user.id
    if str(adm_id) != ADMIN_CHAT_ID: return
    try: bot.answer_callback_query(call.id)
    except: pass
    data = call.data
    
    if data == "reset_task_yes":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_task_status; DELETE FROM active_assignments; DELETE FROM submissions; DELETE FROM question_bank;")
        conn.commit()
        conn.close()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "All Data has been permanently reset!✅")
        
    elif data == "ta_list":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("Organize Task", callback_data="ta_org"), InlineKeyboardButton("Assign Task", callback_data="ta_assign"))
        markup.add(InlineKeyboardButton("Cancel", callback_data="cancel_action"))
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        
    elif data == "ta_assign":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM active_assignments")
        if cursor.fetchone()[0] > 0:
            conn.close()
            return bot.answer_callback_query(call.id, "Already assigned! Stop it first in Triggered Task.", show_alert=True)
            
        cursor.execute("SELECT * FROM organized_tasks")
        orgs = cursor.fetchall()
        
        # Auto assign the first available org sequence for simplicity in this V2
        if orgs:
            seq_str = orgs[0][1]
            tasks = seq_str.split(',')
            teams = ['Team Alpha', 'Team Beta', 'Team Gamma']
            now = get_bd_time()
            next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            
            for i, t_num in enumerate(tasks):
                if i < len(teams):
                    cursor.execute("INSERT INTO active_assignments (team_name, task_num, scheduled_for, is_started) VALUES (%s, %s, %s, FALSE)", (teams[i], int(t_num), next_midnight))
            conn.commit()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"Task: {seq_str} Assigned Successfully✅\nWill trigger at Midnight.")
        else:
            bot.send_message(call.message.chat.id, "No organized tasks found!")
        conn.close()
        
    elif data == "ta_stop":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_assignments WHERE is_started = FALSE")
        conn.commit()
        conn.close()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Task Assign Cancelled Successfully✅")
        
    elif data == "ta_force_end":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Yes", callback_data="ta_force_end_yes"), InlineKeyboardButton("No", callback_data="cancel_action"))
        bot.send_message(call.message.chat.id, "Are you sure you want to end the Task?", reply_markup=markup)
        
    elif data == "ta_force_end_yes":
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT team_name FROM active_assignments WHERE is_started = TRUE")
        teams = cursor.fetchall()
        
        for t in teams:
            cursor.execute("SELECT telegram_id FROM members WHERE team_name = %s", (t['team_name'],))
            for u in cursor.fetchall():
                try: bot.send_message(u['telegram_id'], "Task END!\nThank you dear member♥️")
                except: pass
                
        cursor.execute("DELETE FROM active_assignments WHERE is_started = TRUE")
        conn.commit()
        conn.close()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Task Successfully end!✅")

# ==========================================
# 👑 ADMIN: TASK REVIEW / GRADING
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
    cursor.execute("SELECT s.id, s.telegram_id, m.fb_name, m.team_name FROM submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.status = %s", (status_filter,))
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
        for m in members: markup.add(InlineKeyboardButton(f"{m['fb_name']}", callback_data=f"grd_{m['id']}"))
            
    markup.row(InlineKeyboardButton("Back", callback_data="ignore"), InlineKeyboardButton("Close" if is_completed else "Cancel", callback_data="cancel_action"))
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
        if not act: return bot.answer_callback_query(call.id, "Select Approve or Reject!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        finalize_grading(sub_id, act, feedback)

def process_admin_feedback(message, sub_id):
    admin_state[ADMIN_CHAT_ID]['feedback'] = message.text
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT s.*, m.fb_name, m.team_name FROM submissions s JOIN members m ON s.telegram_id = m.telegram_id WHERE s.id = %s", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    caption = f"{sub['content_text']}\nName: {sub['fb_name']}\nTeam: {sub['team_name']}\n◀️Feedback: {message.text}"
    markup = InlineKeyboardMarkup(row_width=2).row(InlineKeyboardButton("Send", callback_data=f"gsub_{sub_id}"), InlineKeyboardButton("Cancel", callback_data="cancel_action"))
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
        
        # Task 3 Forward Logic
        if sub['task_num'] == 3:
            fwd_cap = f"{sub['content_text']}\nName: Approved By Admin"
            try:
                if sub['photo_id']: bot.send_photo(PRIVATE_GROUP_ID, sub['photo_id'], caption=fwd_cap)
                else: bot.send_message(PRIVATE_GROUP_ID, fwd_cap)
            except Exception as e: print("Forward Error:", e)
    else:
        cursor.execute("DELETE FROM submissions WHERE id = %s", (sub_id,))
        user_msg = f"{sub['content_text']}\nTask Status: Failed❌\n"
        if feedback: user_msg += f"◀️Feedback: {feedback}"
        else: user_msg += "Please try again. If the issue persists, contact a senior team member for assistance."
        
    conn.commit()
    conn.close()
    try: bot.send_message(sub['telegram_id'], user_msg)
    except: pass

@bot.message_handler(func=lambda msg: msg.text in ["Submit QnA", "Submit Article", "My Task Status", "Pending QnA", "Members Status", "Resign⚠️", "Pending Articles", "Edit Instructions", "Moderators"])
def coming_soon(message):
    bot.send_message(message.chat.id, "⏳ This feature is Coming Soon!")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("🤖 KBKh Task Bot is running smoothly...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
