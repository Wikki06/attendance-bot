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
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
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

# ================= CACHE =================
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

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
        log(f"API error: {e}")
        return []

# ================= FORMAT =================
def format_result(name, results):
    passed = all(r["grade"] not in ["U", "RA", "AB"] for r in results)

    header = (
        "🎓✨ END SEMESTER RESULT ✨🎓\n\n"
        f"Hey {name} 👋\n"
    )

    if passed:
        header += (
            "🎉 Woohoo! Congratulations!\n"
            "You have successfully cleared your exams 💪🔥\n\n"
        )
    else:
        header += (
            "📢 Your exam results are available.\n"
            "Keep going — setbacks are part of success 💙\n\n"
        )

    body = []
    for r in results:
        emoji = "🏆" if r["grade"] in ["O", "A+"] else "✅"
        body.append(
            f"{emoji} *{r['sub_name']}*\n"
            f"🆔 {r['sub_code']} | Sem {r['semester']}\n"
            f"🎯 Grade: *{r['grade']}*"
        )

    footer = (
        "\n\n🌟 Keep pushing forward — your hard work shows!\n"
        "🤖 Automated and Sent with ❤️ By Vignesh and Tamil Tharshini"
    )

    return header + "\n\n".join(body) + footer



# ================= AUTO MONITOR =================
def result_monitor():
    log("📡 Result monitor started")
    cache = load_cache()

    while True:
        try:
            for s in load_students():
                regno = s["regno"]

                if cache.get(regno, {}).get("auto_sem7"):
                    continue

                results = fetch_results(regno)
                sem7 = [r for r in results if r.get("semester") == 7]

                if sem7:
                    send_message(
                        s["chat_id"],
                        format_result(s["name"], sem7)
                    )
                    cache[regno] = {"auto_sem7": True}
                    save_cache(cache)
                    log(f"✅ Auto result sent for {regno}")

        except Exception as e:
            log(f"Monitor error: {e}")

        time.sleep(CHECK_INTERVAL)

# ================= TELEGRAM LISTENER =================
pending = {}

def telegram_listener():
    offset = None
    log("💬 Telegram listener started")

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            r = requests.get(url, params={"timeout": 100, "offset": offset}, timeout=120)
            updates = r.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                name = msg.get("chat", {}).get("first_name", "Student")

                # ---------- START ----------
                if text == "/start":
                    if get_student(chat_id):
                        send_message(chat_id, "✅ Already registered.")
                    else:
                        pending[chat_id] = "regno"
                        send_message(chat_id, "Enter your Register Number:")
                    continue

                # ---------- REGISTER FLOW ----------
                if chat_id in pending:
                    add_student(chat_id, text, name)
                    pending.pop(chat_id)
                    send_message(chat_id, "🎉 Registered successfully!")
                    continue

                # ---------- MANUAL RESULT ----------
                if text == "/result":
                    student = get_student(chat_id)
                    if not student:
                        send_message(chat_id, "⚠️ Register first using /start")
                        continue

                    send_message(chat_id, "⏳ Fetching result...")
                    results = fetch_results(student["regno"])

                    if not results:
                        send_message(chat_id, "❌ Result not available.")
                        continue

                    send_message(
                        chat_id,
                        format_result(student["name"], results)
                    )
                    continue

        except Exception as e:
            log(f"Listener error: {e}")

# ================= MAIN =================
if __name__ == "__main__":
    threading.Thread(target=result_monitor, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()

    log("🚀 Bot is running...")
    while True:
        time.sleep(10)
