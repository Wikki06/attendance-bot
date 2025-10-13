import requests
import csv
import time
import json
import os
import threading
from datetime import datetime

# ------------------ Config ------------------
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
CSV_FILE = "students.csv"
DATA_FILE = "attendance.json"
OFFSET_FILE = "offset.txt"
HIGHLIGHTED_SUBJECTS = ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"]
admin_chat_id = "1718437414"

# ------------------ State ------------------
pending_usernames = {}
broadcast_mode = {}

# ------------------ Helpers ------------------
def normalize_id(x):
    return str(x).strip()

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

def log_chat_interaction(chat_id, username, message_text):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        file_exists = os.path.isfile("chat_history.csv")
        with open("chat_history.csv", mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "chat_id", "username", "message_text"])
            writer.writerow([timestamp, chat_id, username, message_text])
    except:
        pass

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def load_students():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id"])
            writer.writeheader()
    students = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append({
                "username": (row.get("username") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "chat_id": (row.get("chat_id") or "").strip()
            })
    return students

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id"])
        writer.writeheader()
        writer.writerows(students)

def get_student_by_chat_id(chat_id):
    nid = normalize_id(chat_id)
    for s in load_students():
        if normalize_id(s.get("chat_id", "")) == nid and nid != "":
            return s
    return None

def add_or_update_student(chat_id, username, name):
    students = load_students()
    username = username.strip()
    chat_id = normalize_id(chat_id)
    updated = False
    for s in students:
        if s["username"] == username:
            s["chat_id"] = chat_id
            s["name"] = name
            updated = True
            break
    if not updated:
        students.append({"username": username, "name": name, "chat_id": chat_id})
    save_students(students)
    send_message(chat_id, f"✅ You are subscribed for attendance alerts, {name}!")

# ------------------ Attendance ------------------
def load_old_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_new_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def fetch_attendance(username):
    try:
        url = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"
        payload = {"register_num": username, "function": "sva"}
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        data = response.json()
        if data.get("success"):
            attendance_list = data["result"]["attendance"]
            attendance_dict = {}
            for sub in attendance_list:
                sub_code = sub["sub_code"]
                perc = float(sub["attendance_percentage"])
                attendance_dict[sub_code] = perc
            overall_list = [attendance_dict[s] for s in HIGHLIGHTED_SUBJECTS if s in attendance_dict]
            attendance_dict["OVERALL"] = sum(overall_list) / len(overall_list) if overall_list else 100.0
            return attendance_dict
        else:
            return {}
    except:
        return {}

# ------------------ Admin Broadcast ------------------
def broadcast_to_all(message):
    students = load_students()
    sent_to = set()
    for student in students:
        chat_id = normalize_id(student.get("chat_id", ""))
        if chat_id and chat_id not in sent_to:
            send_message(chat_id, f"📢 Admin message: {message}")
            sent_to.add(chat_id)

# ------------------ Telegram Listener ------------------
def telegram_listener():
    offset = load_offset()
    while True:
        updates, offset = get_updates(offset)
        for update in updates:
            message = update.get("message", {})
            text = (message.get("text") or "").strip()
            chat_id = normalize_id(message.get("chat", {}).get("id", ""))
            name = message.get("chat", {}).get("first_name", "User")

            log_chat_interaction(chat_id, name, text)

            # ------------------ Delete wrong username (Admin only) ------------------
            if text.startswith("/remove_user"):
                if chat_id != admin_chat_id:
                    send_message(chat_id, "❌ You are not authorized to use this command.")
                    continue
                try:
                    # Example usage: /remove_user wrongusername
                    username_to_delete = text.split()[1]
                    students = load_students()
                    if username_to_delete not in [s["username"] for s in students]:
                        send_message(chat_id, f"❌ Username '{username_to_delete}' not found!")
                    else:
                        students = [s for s in students if s["username"] != username_to_delete]
                        save_students(students)
                        send_message(chat_id, f"✅ Username '{username_to_delete}' has been removed successfully!")
                except IndexError:
                    send_message(chat_id, "⚠️ Usage: /remove_user <username>")
                continue

            # Admin broadcast
            if chat_id == admin_chat_id:
                if text == "/broadcast":
                    send_message(chat_id, "📢 Enter the message to broadcast to all users:")
                    broadcast_mode[chat_id] = True
                    continue
                elif broadcast_mode.get(chat_id):
                    broadcast_to_all(text)
                    send_message(chat_id, "✅ Broadcast sent successfully.")
                    broadcast_mode.pop(chat_id, None)
                    continue
            elif text == "/broadcast":
                send_message(chat_id, "❌ You are not authorized.")
                continue

            # /start registration
            if text == "/start":
                existing = get_student_by_chat_id(chat_id)
                if existing:
                    send_message(chat_id, f"✅ Already registered, {existing.get('name','User')}!")
                    continue
                send_message(chat_id, f"Hi {name}! Please enter your CARE register number:")
                pending_usernames[chat_id] = True
                continue

            # Handle register number input
            if pending_usernames.get(chat_id):
                if text.startswith("8107") and len(text) >= 6:
                    pending_usernames.pop(chat_id, None)
                    add_or_update_student(chat_id, text, name)
                else:
                    send_message(chat_id, "⚠️ Invalid register number. Must start with 8107.")
                continue

            # /attendance
            if text == "/attendance":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ You are not registered. Use /start first.")
                    continue
                send_message(chat_id, "⏳ Fetching your attendance...")
                attendance_data = fetch_attendance(student["username"])
                if not attendance_data:
                    send_message(chat_id, "⚠️ Could not fetch attendance. Try later.")
                    continue
                overall = attendance_data.get("OVERALL")
                dropped_subjects = []
                old_data = load_old_data()
                for code in HIGHLIGHTED_SUBJECTS:
                    old_val = old_data.get(student["username"], {}).get(code)
                    new_val = attendance_data.get(code)
                    if old_val is not None and new_val is not None and new_val < old_val:
                        dropped_subjects.append(f"{code}: {old_val:.2f}% → {new_val:.2f}%")

                lines = [f"Dear {student['name']},"]

                if overall is not None:
                    if overall < 75:
                        lines.append(f"🚨 Your overall attendance is below 75% ({overall:.2f}%). Please improve.")
                    elif overall < 80:
                        lines.append(f"⚠️ Warning! Your overall attendance is near 75% ({overall:.2f}%).")
                    else:
                        lines.append(f"✅ Your overall attendance is {overall:.2f}%.")

                if dropped_subjects:
                    lines.append("📉 Attendance dropped in:")
                    lines.extend([f"• {s}" for s in dropped_subjects])

                message = "\n".join(lines)
                send_message(chat_id, message)
                continue

            # Unknown command
            if text.startswith("/"):
                send_message(chat_id, "⚠️ Unknown command.")
                continue

            # Non-command message
            send_message(chat_id, "⚠️ Don’t send unwanted messages. You are being monitored.")

# ------------------ Attendance Monitor ------------------
def attendance_monitor():
    while True:
        old_data = load_old_data()
        students = load_students()
        for student in students:
            username = student["username"]
            chat_id = student["chat_id"]
            name = student["name"]
            if not chat_id or not username:
                continue
            attendance = fetch_attendance(username)
            if not attendance:
                continue

            dropped_subjects = []
            for code in HIGHLIGHTED_SUBJECTS:
                old_val = old_data.get(username, {}).get(code)
                new_val = attendance.get(code)
                if old_val is not None and new_val is not None and new_val < old_val:
                    dropped_subjects.append(f"{code}: {old_val:.2f}% → {new_val:.2f}%")

            overall = attendance.get("OVERALL", 100)
            if overall < 80 or dropped_subjects:
                lines = [f"Dear {name},"]

                if overall < 75:
                    lines.append(f"🚨 Overall attendance below 75% ({overall:.2f}%).")
                elif overall < 80:
                    lines.append(f"⚠️ Overall attendance near 75% ({overall:.2f}%).")

                if dropped_subjects:
                    lines.append("📉 Attendance dropped in:")
                    lines.extend([f"• {s}" for s in dropped_subjects])

                lines.append(f"📊 Overall: {overall:.2f}%")
                send_message(chat_id, "\n".join(lines))

            old_data[username] = attendance
        save_new_data(old_data)
        time.sleep(600)  # check every 10 minutes

# ------------------ Telegram getUpdates ------------------
def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=110)
        data = response.json().get("result", [])
        if data:
            offset = data[-1]["update_id"] + 1
            save_offset(offset)
        return data, offset
    except:
        return [], offset

# ------------------ Main ------------------
if __name__ == "__main__":
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=attendance_monitor, daemon=True).start()
    while True:
        time.sleep(10)
