#!/usr/bin/env python3
import os
import csv
import json
import time
import threading
import requests
from datetime import datetime

# ================= CONFIG =================
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"   # 🔴 Replace this
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
            writer = csv.DictWriter(
                f, fieldnames=["regno", "name", "chat_id"]
            )
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["regno", "name", "chat_id"]
        )
        writer.writeheader()
        writer.writerows(students)

def get_student(chat_id):
    for s in load_students():
        if s["chat_id"] == str(chat_id):
            return s
    return None

def add_student(chat_id, regno, name):
    students = load_students()
    students.append({
        "regno": regno,
        "name": name,
        "chat_id": str(chat_id)
    })
    save_students(students)

def update_regno(chat_id, new_regno):
    students = load_students()
    for s in students:
        if s["chat_id"] == str(chat_id):
            s["regno"] = new_regno
            save_students(students)
            return True
    return False

# ================= CACHE =================
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ================= ATTENDANCE API =================
def fetch_attendance(regno):
    payload = {
        "register_num": regno,
        "college_code": 8107,
        "function": "sva"
    }

    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        data = r.json()
        return data.get("result", {}).get("attendance", [])
    except Exception as e:
        log(f"Attendance API error: {e}")
        return []

def format_attendance(name, att):
    msg = [
        "📊 *Attendance Report*",
        f"👤 {name}",
        "-" * 30
    ]

    for a in att:
        percent = a.get("attendance_percentage", "N/A")
        msg.append(f"✅ {a.get('sub_code')} → {percent}%")

    msg.append("\n🤖 Automated and Sent with ❤️ by  Vignesh and Tamil Tharshini")
    return "\n".join(msg)

# ================= RESULT API =================
def fetch_results(regno):
    payload = {
        "register_num": regno,
        "college_code": 8107,
        "function": "sver"
    }

    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        data = r.json()
        return data.get("result", {}).get("exam_result", [])
    except Exception as e:
        log(f"Result API error: {e}")
        return []

def format_result(name, results):
    msg = [
        "🎓✨ END SEMESTER RESULT ✨🎓",
        f"Hey {name} 👋",
        "-" * 30
    ]

    for r in results:
        msg.append(
            f"🏆 *{r['sub_name']}*\n"
            f"🆔 {r['sub_code']} | Sem {r['semester']}\n"
            f"🎯 Grade: *{r['grade']}*\n"
        )

    msg.append("🤖 Automated and Sent with ❤️ By Vignesh and Tamil Tharshini")
    return "\n".join(msg)

# ================= AUTO SEM7 MONITOR =================
def result_monitor():
    log("📡 Result monitor started")
    cache = load_cache()

    while True:
        for s in load_students():
            regno = s["regno"]

            if cache.get(regno, {}).get("sem7_sent"):
                continue

            results = fetch_results(regno)
            sem7 = [r for r in results if r.get("semester") == 7]

            if sem7:
                send_message(s["chat_id"], format_result(s["name"], sem7))
                cache[regno] = {"sem7_sent": True}
                save_cache(cache)

        time.sleep(CHECK_INTERVAL)

# ================= TELEGRAM LISTENER =================
pending = {}

def telegram_listener():
    offset = None
    log("💬 Telegram listener started")

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"timeout": 100, "offset": offset},
                timeout=120
            )

            updates = r.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                name = msg["chat"].get("first_name", "Student")
                text = msg.get("text", "").strip()

                # ---------- START ----------
                if text == "/start":
                    if get_student(chat_id):
                        send_message(chat_id, "✅ Already registered.\nUse /attendance or /result")
                    else:
                        pending[chat_id] = "register"
                        send_message(chat_id, "👋 Welcome!\nEnter your *Register Number*:")
                    continue

                # ---------- REGISTER ----------
                if chat_id in pending and pending[chat_id] == "register":
                    add_student(chat_id, text, name)
                    pending.pop(chat_id)

                    send_message(
                        chat_id,
                        "🎉 *Registered successfully!*\n\n"
                        "Please use:\n"
                        "📊 /attendance – Check Attendance\n"
                        "🎓 /result – Check Result"
			"❗ /update_regno - To update your register Number
                    )
                    continue

                # ---------- UPDATE REGNO ----------
                if text == "/update_regno":
                    if not get_student(chat_id):
                        send_message(chat_id, "⚠️ Use /start first.")
                    else:
                        pending[chat_id] = "update"
                        send_message(chat_id, "✏️ Enter your correct Register Number:")
                    continue

                if chat_id in pending and pending[chat_id] == "update":
                    update_regno(chat_id, text)
                    pending.pop(chat_id)
                    send_message(chat_id, "✅ Register number updated successfully!")
                    continue

                # ---------- ATTENDANCE ----------
                if text == "/attendance":
                    student = get_student(chat_id)
                    if not student:
                        send_message(chat_id, "⚠️ Register first using /start")
                        continue

                    send_message(chat_id, "⏳ Fetching attendance...")
                    att = fetch_attendance(student["regno"])

                    if not att:
                        send_message(chat_id, "❌ Attendance not available.")
                    else:
                        send_message(chat_id, format_attendance(student["name"], att))
                    continue

                # ---------- RESULT ----------
                if text == "/result":
                    student = get_student(chat_id)
                    if not student:
                        send_message(chat_id, "⚠️ Register first using /start")
                        continue

                    send_message(chat_id, "⏳ Fetching result...")
                    results = fetch_results(student["regno"])

                    if not results:
                        send_message(chat_id, "❌ Result not available.")
                    else:
                        send_message(chat_id, format_result(student["name"], results))
                    continue

                # ---------- UNWANTED MSG ----------
                send_message(
                    chat_id,
                    "⚠️ Don’t send unwanted messages, you are being monitored!"
                )

        except Exception as e:
            log(f"Listener error: {e}")
            time.sleep(5)

# ================= MAIN =================
if __name__ == "__main__":
    threading.Thread(target=result_monitor, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()

    log("🚀 Bot is running...")
    while True:
        time.sleep(10)
