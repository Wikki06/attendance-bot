#!/usr/bin/env python3
import os
import csv
import json
import time
import threading
import requests
from datetime import datetime

# ================= CONFIG =================
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"

CSV_FILE = "students.csv"
CACHE_FILE = "cache.json"

CHECK_INTERVAL = 30 * 60  # 30 minutes

# ================= UTIL =================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def send_message(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        },
        timeout=10
    )

# ================= STORAGE =================
def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["regno", "name", "chat_id"])
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["regno", "name", "chat_id"])
        writer.writeheader()
        writer.writerows(students)

def get_student(chat_id):
    for s in load_students():
        if s["chat_id"] == str(chat_id):
            return s
    return None

def add_student(chat_id, regno, name):
    students = load_students()
    students.append({"regno": regno, "name": name, "chat_id": str(chat_id)})
    save_students(students)

def update_regno(chat_id, new_regno):
    students = load_students()
    for s in students:
        if s["chat_id"] == str(chat_id):
            s["regno"] = new_regno
            save_students(students)
            return True
    return False

# ================= ATTENDANCE API =================
def fetch_attendance(regno):
    payload = {"register_num": regno, "college_code": 8107, "function": "sva"}
    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        return r.json().get("result", {}).get("attendance", [])
    except:
        return []

def format_attendance(name, att):
    msg = ["📊 *Attendance Report*", f"👤 {name}", "-" * 30]
    for a in att:
        msg.append(f"✅ {a.get('sub_code')} → {a.get('attendance_percentage', 'N/A')}%")
    msg.append("\n🤖 Automated and Sent by Vignesh and Tamil Tharshini")
    return "\n".join(msg)

# ================= RESULT API =================
def fetch_results(regno):
    payload = {"register_num": regno, "college_code": 8107, "function": "sver"}
    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        return r.json().get("result", {}).get("exam_result", [])
    except:
        return []

def format_result(name, results):
    msg = ["🎓✨ END SEMESTER RESULT ✨🎓", f"Hey {name} 👋", "-" * 30]
    for r in results:
        msg.append(
            f"🏆 *{r['sub_name']}*\n"
            f"🆔 {r['sub_code']} | Sem {r['semester']}\n"
            f"🎯 Grade: *{r['grade']}*\n"
        )
    msg.append("🤖 Automated and Sent by Vignesh and Tamil Tharshini")
    return "\n".join(msg)

# ================= TELEGRAM LISTENER =================
pending = {}

def telegram_listener():
    offset = None
    log("💬 Telegram listener started")

    while True:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"timeout": 100, "offset": offset},
            timeout=120
        )

        updates = r.json().get("result", [])

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            chat_id = msg["chat"]["id"]
            name = msg["chat"].get("first_name", "Student")
            text = msg.get("text", "").strip()

            # ---- START ----
            if text == "/start":
                if get_student(chat_id):
                    send_message(chat_id, "✅ Already registered.\nUse /attendance or /result")
                else:
                    pending[chat_id] = "register"
                    send_message(chat_id, "👋 Welcome!\nEnter your Register Number:")
                continue

            # ---- REGISTER ----
            if chat_id in pending and pending[chat_id] == "register":
                add_student(chat_id, text, name)
                pending.pop(chat_id)

                send_message(
                    chat_id,
                    "🎉 *Registered successfully!*\n\n"
                    "Please use these commands 👇\n\n"
                    "📊 /attendance – Check Attendance\n"
                    "🎓 /result – Check Result\n"
                    "❗ /update_regno – Update Register Number"
                )
                continue

            # ---- UPDATE REGNO ----
            if text == "/update_regno":
                pending[chat_id] = "update"
                send_message(chat_id, "✏️ Enter your correct Register Number:")
                continue

            if chat_id in pending and pending[chat_id] == "update":
                update_regno(chat_id, text)
                pending.pop(chat_id)
                send_message(chat_id, "✅ Register number updated successfully!")
                continue

            # ---- ATTENDANCE ----
            if text == "/attendance":
                student = get_student(chat_id)
                att = fetch_attendance(student["regno"])
                send_message(chat_id, format_attendance(student["name"], att))
                continue

            # ---- RESULT ----
            if text == "/result":
                student = get_student(chat_id)
                results = fetch_results(student["regno"])
                send_message(chat_id, format_result(student["name"], results))
                continue

            # ---- UNWANTED ----
            send_message(chat_id, "⚠️ Don’t send unwanted messages, you are being monitored!")

# ================= MAIN =================
if __name__ == "__main__":
    threading.Thread(target=telegram_listener, daemon=True).start()
    log("🚀 Bot is running...")
    while True:
        time.sleep(10)
