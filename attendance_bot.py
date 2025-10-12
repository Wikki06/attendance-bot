import requests
import csv
import time
import json
import os
import threading
import logging
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext

# ==================== CONFIG ====================
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"
STUDENTS_FILE = "students.csv"
ATTENDANCE_FILE = "attendance.json"
OFFSET_FILE = "offset.txt"
CHECK_INTERVAL = 600  # 10 minutes

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ==================== CSV UTILS ====================
def load_students():
    if not os.path.exists(STUDENTS_FILE):
        return []
    with open(STUDENTS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_student(register_num, chat_id):
    file_exists = os.path.exists(STUDENTS_FILE)
    with open(STUDENTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["register_num", "chat_id"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({"register_num": register_num, "chat_id": chat_id})

# ==================== ATTENDANCE FETCH ====================
def fetch_attendance(register_num):
    payload = {"register_num": register_num, "function": "sva"}
    try:
        response = requests.post(API_URL, json=payload, timeout=15)
        data = response.json()

        if not data.get("success"):
            logging.error("❌ API Error: %s", data.get("message"))
            return None

        result = data["result"]["attendance"]
        overall = sum(float(x["attendance_percentage"]) for x in result) / len(result)
        attendance_dict = {sub["sub_code"]: float(sub["attendance_percentage"]) for sub in result}
        attendance_dict["OVERALL"] = round(overall, 2)
        return attendance_dict

    except Exception as e:
        logging.error(f"⚠️ Fetch failed: {e}")
        return None

# ==================== ALERT LOGIC ====================
def check_alerts(bot, chat_id, register_num, old_data, new_data):
    if not old_data or not new_data:
        return

    drops = []
    for subject, new_percent in new_data.items():
        if subject in old_data and new_percent < old_data[subject]:
            diff = old_data[subject] - new_percent
            drops.append(f"{subject}: dropped by {diff:.2f}%")

    overall = new_data.get("OVERALL", 0)
    if drops:
        bot.send_message(chat_id=chat_id, text=f"⚠️ Drop Alert for {register_num}\n" + "\n".join(drops))

    if overall <= 75:
        bot.send_message(chat_id=chat_id, text=f"🚨 Your overall attendance is {overall}%. You are below 75%! Please attend classes regularly.")
    elif overall <= 80:
        bot.send_message(chat_id=chat_id, text=f"⚠️ Your overall attendance is {overall}%. You are close to 75%. Be careful!")

# ==================== ATTENDANCE MONITOR ====================
def attendance_monitor():
    bot = Bot(BOT_TOKEN)
    logging.info("⏱️ Attendance monitor started...")

    while True:
        students = load_students()
        if not students:
            logging.info("🧾 No students subscribed yet.")
            time.sleep(CHECK_INTERVAL)
            continue

        if os.path.exists(ATTENDANCE_FILE):
            with open(ATTENDANCE_FILE, "r") as f:
                old_attendance = json.load(f)
        else:
            old_attendance = {}

        updated_data = {}

        for student in students:
            reg = student["register_num"]
            chat_id = student["chat_id"]

            logging.info(f"⏱️ Checking attendance for {reg}...")
            new_data = fetch_attendance(reg)

            if not new_data:
                logging.info(f"❌ Failed for {reg}")
                continue

            old_data = old_attendance.get(reg)
            check_alerts(bot, chat_id, reg, old_data, new_data)
            updated_data[reg] = new_data

        with open(ATTENDANCE_FILE, "w") as f:
            json.dump(updated_data, f, indent=4)

        logging.info("✅ Attendance check complete. Sleeping 10 mins...\n")
        time.sleep(CHECK_INTERVAL)

# ==================== TELEGRAM COMMANDS ====================
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Hey there! Please send your register number to subscribe for attendance alerts.\nExample: 810722104107")

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    if text.isdigit() and len(text) == 12:
        register_num = text
        students = load_students()
        if any(s["register_num"] == register_num for s in students):
            update.message.reply_text("✅ You are already subscribed for attendance alerts!")
        else:
            save_student(register_num, chat_id)
            update.message.reply_text(f"🎉 You are subscribed for attendance alerts, {register_num}!")
        return

    update.message.reply_text("❌ Invalid input. Please send your *register number* only.")

def attendance(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    students = load_students()
    student = next((s for s in students if str(s["chat_id"]) == str(chat_id)), None)

    if not student:
        update.message.reply_text("❌ You are not subscribed yet. Please send your register number first.")
        return

    reg = student["register_num"]
    update.message.reply_text("⏳ Fetching your current attendance...")
    data = fetch_attendance(reg)

    if not data:
        update.message.reply_text("⚠️ Could not fetch attendance. Try again later.")
        return

    overall = data.get("OVERALL", 0)
    if overall <= 75:
        msg = f"🚨 Your overall attendance is {overall}%. Below 75%! Please attend classes regularly."
    elif overall <= 80:
        msg = f"⚠️ Your overall attendance is {overall}%. Near 75%. Be careful!"
    else:
        msg = f"✅ Your overall attendance is {overall}%"

    update.message.reply_text(msg)

# ==================== MAIN ====================
def telegram_listener():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("attendance", attendance))
    dp.add_handler(MessageHandler(None, handle_message))

    updater.start_polling()
    updater.idle()

# ==================== RUN BOTH THREADS ====================
if __name__ == "__main__":
    t1 = threading.Thread(target=telegram_listener)
    t2 = threading.Thread(target=attendance_monitor)
    t1.start()
    t2.start()
