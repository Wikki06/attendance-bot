import requests
import csv
import time
import json
import os
import threading
from datetime import datetime

# Telegram Bot Token
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# File paths
CSV_FILE = "students.csv"
DATA_FILE = "attendance_data.json"
OFFSET_FILE = "offset.txt"
CHAT_HISTORY_FILE = "chat_history.csv"
HIGHLIGHTED_SUBJECTS = ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"]

# Admin
admin_chat_id = "1718437414"
broadcast_mode = {}
pending_usernames = {}
pending_passwords = {}
changing_password = {}

# Attendance API endpoint
API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"


# ===============================
# Helper Functions
# ===============================
def normalize_id(x):
    try:
        return str(x).strip()
    except Exception:
        return ""


def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return None
    return None


def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"❌ Failed to send message: {e}")


def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=110)
        data = response.json().get("result", [])
        if data:
            offset = data[-1]["update_id"] + 1
            save_offset(offset)
        return data, offset
    except Exception as e:
        print(f"❌ Error in get_updates: {e}")
        return [], offset


def log_chat(chat_id, username, message_text):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        file_exists = os.path.isfile(CHAT_HISTORY_FILE)
        with open(CHAT_HISTORY_FILE, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "chat_id", "username", "message"])
            writer.writerow([timestamp, chat_id, username, message_text])
    except Exception as e:
        print(f"⚠️ Error logging chat: {e}")


# ===============================
# CSV Functions
# ===============================
def load_students():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["username", "password", "name", "chat_id"])
            writer.writeheader()
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "password", "name", "chat_id"])
        writer.writeheader()
        writer.writerows(students)


def get_student_by_chat_id(chat_id):
    chat_id = normalize_id(chat_id)
    for s in load_students():
        if normalize_id(s.get("chat_id")) == chat_id:
            return s
    return None


def add_or_update_student(chat_id, username, password, name):
    students = load_students()
    updated = False
    for s in students:
        if s["username"] == username:
            s["password"] = password
            s["chat_id"] = chat_id
            s["name"] = name
            updated = True
    if not updated:
        students.append({"username": username, "password": password, "name": name, "chat_id": chat_id})
    save_students(students)
    send_message(chat_id, f"✅ Registered successfully, {name}!")


def change_password(chat_id, new_password):
    students = load_students()
    for s in students:
        if normalize_id(s["chat_id"]) == normalize_id(chat_id):
            s["password"] = new_password
            save_students(students)
            send_message(chat_id, "🔑 Password changed successfully!")
            return
    send_message(chat_id, "⚠️ Not registered. Use /start to register.")


# ===============================
# Attendance Fetcher (API)
# ===============================
def fetch_attendance(username):
    """Fetches attendance using API (no Selenium)."""
    try:
        payload = {"register_num": username, "function": "sva"}
        r = requests.post(API_URL, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"❌ API HTTP {r.status_code}")
            return None
        data = r.json()
        if not data.get("success"):
            print(f"❌ API error: {data.get('message')}")
            return None

        result = data.get("result", {}).get("attendance", [])
        att = {item["sub_code"]: float(item["attendance_percentage"]) for item in result}
        if att:
            overall = sum(att.values()) / len(att)
            att["OVERALL"] = round(overall, 2)
        return att
    except Exception as e:
        print(f"❌ Error fetching attendance: {e}")
        return None


# ===============================
# Attendance Monitor Thread
# ===============================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def attendance_monitor():
    while True:
        print("⏱️ Checking attendance...")
        old_data = load_data()
        for student in load_students():
            username = student["username"]
            chat_id = student["chat_id"]
            name = student["name"]

            attendance = fetch_attendance(username)
            if not attendance:
                continue

            old_att = old_data.get(username, {})
            drops = []
            for sub in HIGHLIGHTED_SUBJECTS:
                old = old_att.get(sub)
                new = attendance.get(sub)
                if old is not None and new is not None and new < old:
                    drops.append(f"{sub}: {old:.2f}% → {new:.2f}%")

            overall = attendance.get("OVERALL", 100)
            if overall < 80 or drops:
                msg = [f"Dear {name},"]
                if overall < 75:
                    msg.append("🚨 Your overall attendance is below 75%!")
                elif overall < 80:
                    msg.append("⚠️ Warning! Attendance near 75%.")
                if drops:
                    msg.append("📉 Attendance dropped in:")
                    msg += [f"• {d}" for d in drops]
                msg.append(f"📊 Overall: {overall:.2f}%")
                send_message(chat_id, "\n".join(msg))

            old_data[username] = attendance
        save_data(old_data)
        print("✅ Attendance check complete. Sleeping 10 mins...")
        time.sleep(600)


# ===============================
# Telegram Listener Thread
# ===============================
def telegram_listener():
    print("📡 Bot live! Listening for commands...")
    offset = load_offset()
    while True:
        updates, offset = get_updates(offset)
        for update in updates:
            message = update.get("message", {})
            text = (message.get("text") or "").strip()
            chat_id = normalize_id(message.get("chat", {}).get("id", ""))
            name = message.get("chat", {}).get("first_name", "User")

            log_chat(chat_id, name, text)

            # Admin broadcast
            if chat_id == admin_chat_id:
                if text == "/broadcast":
                    send_message(chat_id, "📢 Enter broadcast message:")
                    broadcast_mode[chat_id] = True
                    continue
                elif broadcast_mode.get(chat_id):
                    msg = text
                    for s in load_students():
                        if s["chat_id"]:
                            send_message(s["chat_id"], f"📢 Admin Message:\n{msg}")
                    send_message(chat_id, "✅ Broadcast sent.")
                    broadcast_mode.pop(chat_id)
                    continue

            # /start
            if text == "/start":
                if get_student_by_chat_id(chat_id):
                    send_message(chat_id, f"✅ You’re already registered, {name}!")
                    continue
                send_message(chat_id, "👋 Enter your register number (starts with 8107):")
                pending_usernames[chat_id] = True
                continue

            # username input
            if pending_usernames.get(chat_id):
                if text.startswith("8107"):
                    pending_usernames.pop(chat_id)
                    pending_passwords[chat_id] = text
                    send_message(chat_id, "🔑 Now enter your password:")
                else:
                    send_message(chat_id, "⚠️ Invalid register number.")
                continue

            # password input
            if pending_passwords.get(chat_id):
                username = pending_passwords.pop(chat_id)
                password = text
                add_or_update_student(chat_id, username, password, name)
                continue

            # /changepass
            if text == "/changepass":
                if not get_student_by_chat_id(chat_id):
                    send_message(chat_id, "⚠️ Not registered. Use /start first.")
                    continue
                send_message(chat_id, "🔒 Enter your new password:")
                changing_password[chat_id] = True
                continue

            if changing_password.get(chat_id):
                new_pw = text
                changing_password.pop(chat_id)
                change_password(chat_id, new_pw)
                continue

            # /attendance
            if text == "/attendance":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ Not registered. Use /start first.")
                    continue
                send_message(chat_id, "⏳ Fetching your current attendance...")
                attendance = fetch_attendance(student["username"])
                if not attendance:
                    send_message(chat_id, "⚠️ Could not fetch attendance. Try later.")
                    continue
                overall = attendance.get("OVERALL")
                if overall:
                    send_message(chat_id, f"✅ Your overall attendance is {overall:.2f}%")
                else:
                    send_message(chat_id, "⚠️ Attendance not found.")
                continue

            # Default
            send_message(chat_id, "⚠️ Unknown command or message.")


# ===============================
# Main
# ===============================
if __name__ == "__main__":
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=attendance_monitor, daemon=True).start()
    while True:
        time.sleep(10)
