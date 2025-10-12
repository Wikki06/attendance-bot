import json
import os
import threading
import time
from datetime import datetime
import requests

from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext

# ------------------- CONFIG -------------------
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
DATA_FILE = "attendance_data.json"
OFFSET_FILE = "offset.txt"
STUDENTS_FILE = "students.json"
HIGHLIGHTED_SUBJECTS = ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"]
ADMIN_CHAT_ID = "1718437414"  # your admin chat_id
CHECK_INTERVAL = 600  # 10 mins
# ----------------------------------------------

# ------------------- UTILITIES ----------------
def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

def send_message(chat_id, text, context=None):
    if context:
        context.bot.send_message(chat_id=chat_id, text=text)

# ------------------- STUDENT MANAGEMENT ----------------
def register_student(chat_id, reg_no):
    students = load_json(STUDENTS_FILE)
    chat_id = str(chat_id)
    students[chat_id] = {"reg_no": reg_no}
    save_json(STUDENTS_FILE, students)

def get_student(chat_id):
    students = load_json(STUDENTS_FILE)
    return students.get(str(chat_id))

# ------------------- FETCH ATTENDANCE ----------------
def fetch_attendance(reg_no):
    """
    Fetch attendance from CARE CRM API.
    Returns a dict like {"CBM348": 96.97, "GE3791": 90.91, ..., "OVERALL": 92.25}
    """
    try:
        payload = {"register_num": reg_no, "function": "sva"}
        url = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"  # replace with actual API
        response = requests.post(url, json=payload, timeout=20)
        data = response.json()
        if data.get("success"):
            attendance = data["result"].get("attendance", [])
            att_dict = {}
            for a in attendance:
                code = a.get("sub_code")
                perc = float(a.get("attendance_percentage", 0))
                if code:
                    att_dict[code] = perc
            # Calculate OVERALL from highlighted subjects
            overall = sum([att_dict.get(s, 0) for s in HIGHLIGHTED_SUBJECTS]) / len(HIGHLIGHTED_SUBJECTS)
            att_dict["OVERALL"] = round(overall, 2)
            return att_dict
        else:
            return {}
    except Exception as e:
        print(f"Error fetching attendance for {reg_no}: {e}")
        return {}

# ------------------- ATTENDANCE MONITOR ----------------
def attendance_monitor(updater):
    while True:
        print("⏱️ Checking attendance...")
        old_data = load_json(DATA_FILE)
        students = load_json(STUDENTS_FILE)
        for chat_id, info in students.items():
            reg_no = info["reg_no"]
            attendance = fetch_attendance(reg_no)
            if not attendance:
                continue

            dropped_subjects = []
            for code in HIGHLIGHTED_SUBJECTS:
                old_val = old_data.get(reg_no, {}).get(code)
                new_val = attendance.get(code)
                if old_val is not None and new_val is not None and new_val < old_val:
                    dropped_subjects.append(f"{code}: {old_val:.2f}% → {new_val:.2f}%")

            overall = attendance.get("OVERALL", 100)
            messages = []
            if overall <= 75:
                messages.append(f"🚨 Your overall attendance is below 75%: {overall:.2f}%")
            elif overall <= 80:
                messages.append(f"⚠️ Your overall attendance is near 75%: {overall:.2f}%")

            if dropped_subjects:
                messages.append("📉 Attendance dropped in:")
                messages.extend([f"• {s}" for s in dropped_subjects])
                messages.append(f"📊 Overall: {overall:.2f}%")

            if messages:
                messages.insert(0, f"Dear Student ({reg_no}),")
                send_message(chat_id, "\n".join(messages), context=updater.bot)

            old_data[reg_no] = attendance
        save_json(DATA_FILE, old_data)
        print("⏱️ Attendance check complete. Sleeping 10 mins...")
        time.sleep(CHECK_INTERVAL)

# ------------------- TELEGRAM HANDLERS ----------------
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    send_message(chat_id, "Hi! Please enter your CARE register number to subscribe for attendance alerts.")

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    student = get_student(chat_id)
    if not student:
        if text.startswith("8107"):  # register number format
            register_student(chat_id, text)
            send_message(chat_id, "✅ You are subscribed for attendance alerts!")
        else:
            send_message(chat_id, "⚠️ Invalid register number. Must start with 8107.")
        return

def attendance_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    student = get_student(chat_id)
    if not student:
        send_message(chat_id, "⚠️ You are not registered yet. Use /start to subscribe first.")
        return
    reg_no = student["reg_no"]
    attendance = fetch_attendance(reg_no)
    if not attendance:
        send_message(chat_id, "⚠️ Could not fetch attendance. Try again later.")
        return
    overall = attendance.get("OVERALL", 100)
    messages = []
    if overall <= 75:
        messages.append(f"🚨 Your overall attendance is below 75%: {overall:.2f}%")
    elif overall <= 80:
        messages.append(f"⚠️ Your overall attendance is near 75%: {overall:.2f}%")
    # Check drops
    old_data = load_json(DATA_FILE)
    dropped_subjects = []
    for code in HIGHLIGHTED_SUBJECTS:
        old_val = old_data.get(reg_no, {}).get(code)
        new_val = attendance.get(code)
        if old_val is not None and new_val is not None and new_val < old_val:
            dropped_subjects.append(f"{code}: {old_val:.2f}% → {new_val:.2f}%")
    if dropped_subjects:
        messages.append("📉 Attendance dropped in:")
        messages.extend([f"• {s}" for s in dropped_subjects])
    messages.append(f"📊 Overall: {overall:.2f}%")
    send_message(chat_id, "\n".join(messages), context=context)

# ------------------- MAIN ----------------
if __name__ == "__main__":
    updater = Updater(token=BOT_TOKEN)
    dp = updater.dispatcher

    # Commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("attendance", attendance_command))

    # Handle user messages (register number input)
    dp.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start attendance monitor in background
    threading.Thread(target=attendance_monitor, args=(updater,), daemon=True).start()

    # Start Telegram bot
    print("📡 Bot live! Listening for commands...")
    updater.start_polling()
    updater.idle()
