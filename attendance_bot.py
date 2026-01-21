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
ADMIN_CHAT_ID = "1718437414"

CSV_FILE = "students.csv"
DATA_FILE = "monitor.json"

MONITOR_INTERVAL = 30 * 60  # 30 minutes

API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"

# ================= UTIL =================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")

# ================= STORAGE =================
def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["username", "name", "chat_id", "department", "year"]
            )
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["username", "name", "chat_id", "department", "year"]
        )
        writer.writeheader()
        writer.writerows(students)

def get_student_by_chat_id(chat_id):
    for s in load_students():
        if s["chat_id"] == str(chat_id):
            return s
    return None

def add_student(chat_id, regno, name, dept, year):
    students = load_students()
    students.append({
        "username": regno,
        "name": name,
        "chat_id": str(chat_id),
        "department": dept,
        "year": year
    })
    save_students(students)

# ================= JSON CACHE =================
def load_json():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_json(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ================= RESULT API =================
def fetch_end_sem_result(regno):
    payload = {
        "register_num": regno,
        "college_code": 8107,
        "function": "sver"
    }

    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            return []

        return data.get("result", {}).get("exam_result", [])
    except Exception as e:
        log(f"Result API error: {e}")
        return []

# ================= FORMAT RESULT =================
def format_sem7_result(name, results):
    msg = [
        "🎓 END SEMESTER RESULT – SEM 7",
        f"👤 {name}",
        "-" * 35
    ]

    for r in results:
        msg.append(
            f"{r['sub_code']} | {r['grade']}\n"
            f"{r['sub_name']}"
        )

    return "\n\n".join(msg)

# ================= RESULT MONITOR =================
def result_monitor():
    log("📡 Result monitor started")
    cache = load_json()

    while True:
        try:
            students = load_students()
            for s in students:
                regno = s["username"]
                chat_id = s["chat_id"]

                if cache.get(regno, {}).get("sem7_sent"):
                    continue

                results = fetch_end_sem_result(regno)
                sem7 = [r for r in results if r.get("semester") == 7]

                if sem7:
                    message = format_sem7_result(s["name"], sem7)
                    send_message(chat_id, message)

                    cache[regno] = {"sem7_sent": True}
                    save_json(cache)

                    log(f"✅ Sem 7 result sent to {regno}")

        except Exception as e:
            log(f"Monitor error: {e}")

        time.sleep(MONITOR_INTERVAL)

# ================= TELEGRAM LISTENER =================
def telegram_listener():
    offset = None
    log("💬 Telegram listener started")

    while True:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"timeout": 100, "offset": offset}

        try:
            r = requests.get(url, params=params, timeout=120)
            updates = r.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                name = msg.get("chat", {}).get("first_name", "Student")

                if text == "/start":
                    if get_student_by_chat_id(chat_id):
                        send_message(chat_id, "✅ Already registered.")
                    else:
                        send_message(chat_id, "Send your Register Number:")
                        pending[chat_id] = {"step": "regno"}
                    continue

                if chat_id in pending:
                    state = pending[chat_id]

                    if state["step"] == "regno":
                        state["regno"] = text
                        state["step"] = "dept"
                        send_message(chat_id, "Enter Department:")
                        continue

                    if state["step"] == "dept":
                        state["dept"] = text.upper()
                        state["step"] = "year"
                        send_message(chat_id, "Enter Year (I/II/III/IV):")
                        continue

                    if state["step"] == "year":
                        add_student(
                            chat_id,
                            state["regno"],
                            name,
                            state["dept"],
                            text.upper()
                        )
                        send_message(chat_id, "🎉 Registered successfully!")
                        pending.pop(chat_id)
                        continue

        except Exception as e:
            log(f"Listener error: {e}")

# ================= MAIN =================
pending = {}

if __name__ == "__main__":
    threading.Thread(target=result_monitor, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()

    log("🚀 Bot running...")
    while True:
        time.sleep(10)
