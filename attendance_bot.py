"""
Telegram Attendance Bot — Full Version with OTP (by Vignesh & Tamil Tharshini)
Features:
- Agreement before registration
- Student registration (/start) with RegNo + Mobile + OTP
- Dept & Year validation
- Attendance fetch (/attendance)
- Update own info (/updateinfo)
- Admin commands: /broadcast & /remove_user
- Background drop monitoring
"""

import os
import csv
import json
import time
import threading
import random
import requests
from datetime import datetime

# ---------------- CONFIG ----------------
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_CHAT_ID = "YOUR_ADMIN_CHAT_ID"
CSV_FILE = "students.csv"
DATA_FILE = "attendance.json"
OFFSET_FILE = "offset.txt"
MONITOR_INTERVAL = 10 * 60  # every 10 mins
OTP_EXPIRY = 300  # OTP valid for 5 mins

SUBJECT_MAP = {
    ("CSE", "IV"): ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"],
    ("CSE", "III"): ["CS3351", "CS3352", "CS3353"],
    ("ECE", "IV"): ["EC4001", "EC4002", "EC4003"],
}

VALID_DEPTS = {"CSE", "MECH", "ECE", "AIDS", "AI&DS"}
VALID_YEARS = {"I", "II", "III", "IV"}

# ---------------- UTILITIES ----------------
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def normalize_id(x):
    return str(x).strip()

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log(f"send_message error: {e}")

def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=110)
        r.raise_for_status()
        data = r.json().get("result", [])
        if data:
            offset = data[-1]["update_id"] + 1
        return data, offset
    except Exception as e:
        log(f"get_updates error: {e}")
        return [], offset

# ---------------- STUDENT STORAGE ----------------
def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id", "mobile", "department", "year"])
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id", "mobile", "department", "year"])
        writer.writeheader()
        writer.writerows(students)

def get_student_by_chat_id(chat_id):
    for s in load_students():
        if normalize_id(s.get("chat_id")) == normalize_id(chat_id):
            return s
    return None

def remove_user(identifier):
    students = load_students()
    new_students = [s for s in students if s["username"] != identifier and s["chat_id"] != identifier]
    save_students(new_students)
    return len(students) - len(new_students)

def add_or_update_student(chat_id, username, name, mobile, dept, year):
    students = load_students()
    for s in students:
        if s["username"] == username:
            s.update({"chat_id": chat_id, "name": name, "mobile": mobile, "department": dept, "year": year})
            save_students(students)
            return
    students.append({"username": username, "name": name, "chat_id": chat_id, "mobile": mobile, "department": dept, "year": year})
    save_students(students)
    log(f"Saved {username} | {name} | {mobile} | {dept} | {year}")

# ---------------- ATTENDANCE ----------------
CARE_API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"

def fetch_attendance(register_num):
    try:
        payload = {"register_num": register_num, "function": "sva"}
        r = requests.post(CARE_API_URL, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        att = {}
        for i in data.get("result", {}).get("attendance", []):
            code = i.get("sub_code", "")
            try:
                att[code] = float(i.get("attendance_percentage", 0))
            except:
                pass
        return att
    except Exception as e:
        log(f"fetch_attendance error: {e}")
        return {}

def avg_attendance(att, subjects):
    vals = [att[s] for s in subjects if s in att]
    return round(sum(vals) / len(vals), 2) if vals else None

# ---------------- MONITOR ----------------
def load_json():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def attendance_monitor():
    log("📡 Attendance monitor running...")
    while True:
        try:
            prev_data = load_json()
            for s in load_students():
                reg = s["username"]
                chat = s["chat_id"]
                name = s["name"]
                dept, year = s["department"], s["year"]
                subs = SUBJECT_MAP.get((dept, year), [])
                if not subs:
                    continue
                att = fetch_attendance(reg)
                if not att:
                    continue
                overall = avg_attendance(att, subs)
                att["OVERALL"] = overall
                drops = []
                for sub in subs:
                    old = prev_data.get(reg, {}).get(sub)
                    new = att.get(sub)
                    if old and new and new < old - 0.01:
                        drops.append(f"{sub}: {old:.2f}% → {new:.2f}%")
                if overall and (overall < 80 or drops):
                    msg = [f"Dear {name},"]
                    if overall < 75:
                        msg.append(f"🚨 Overall below 75% ({overall}%)")
                    elif overall < 80:
                        msg.append(f"⚠️ Overall near limit ({overall}%)")
                    if drops:
                        msg.append("📉 Drop detected:")
                        msg += [f"• {d}" for d in drops]
                    msg.append("\n📊 Subjects:")
                    for sub in subs:
                        if sub in att:
                            msg.append(f"• {sub}: {att[sub]:.2f}%")
                    send_message(chat, "\n".join(msg))
                prev_data[reg] = att
            save_json(prev_data)
        except Exception as e:
            log(f"monitor error: {e}")
        time.sleep(MONITOR_INTERVAL)

# ---------------- TELEGRAM LISTENER ----------------
pending = {}
otp_store = {}  # chat_id -> {"otp": 123456, "expires": timestamp}

def generate_otp():
    return random.randint(100000, 999999)

def telegram_listener():
    log("💬 Telegram listener running...")
    offset = None
    while True:
        updates, offset = get_updates(offset)
        for upd in updates:
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            name = msg.get("chat", {}).get("first_name", "Student")

            # ADMIN COMMANDS
            if chat_id == ADMIN_CHAT_ID and text.startswith("/broadcast "):
                message = text.replace("/broadcast ", "").strip()
                if not message:
                    send_message(chat_id, "⚠️ Usage: /broadcast <message>")
                    continue
                for s in load_students():
                    send_message(s["chat_id"], f"📢 *Announcement:*\n{message}")
                send_message(chat_id, "✅ Broadcast sent to all.")
                continue

            if chat_id == ADMIN_CHAT_ID and text.startswith("/remove_user "):
                ident = text.split(" ", 1)[1].strip()
                removed = remove_user(ident)
                send_message(chat_id, f"🗑️ Removed {removed} user(s) with ID/Reg: {ident}")
                continue

            # ---------------- START REGISTRATION ----------------
            if text == "/start":
                existing = get_student_by_chat_id(chat_id)
                if existing:
                    send_message(chat_id, f"✅ Already registered as {existing['name']}. Use /attendance.")
                    continue
                pending[chat_id] = {"step": "regno"}
                send_message(chat_id, f"Hi {name}! Enter your CARE Register Number (starts with 8107):")
                continue

            if chat_id in pending:
                state = pending[chat_id]
                step = state.get("step")

                if step == "regno":
                    regno_input = text.strip()
                    if not regno_input.startswith("8107"):
                        send_message(chat_id, "❌ Invalid register number. Try again (8107xxxx).")
                        continue
                    state["regno"] = regno_input
                    state["step"] = "mobile"
                    send_message(chat_id, "Enter your Mobile Number (10 digits):")
                    continue

                if step == "mobile":
                    mobile_input = text.strip()
                    if not mobile_input.isdigit() or len(mobile_input) != 10:
                        send_message(chat_id, "❌ Invalid mobile! Enter 10-digit number.")
                        continue
                    state["mobile"] = mobile_input
                    otp = generate_otp()
                    otp_store[chat_id] = {"otp": otp, "expires": time.time() + OTP_EXPIRY}
                    state["step"] = "otp"
                    send_message(chat_id, f"📩 Your OTP is: {otp}\nEnter it here to verify (valid 5 mins):")
                    continue

                if step == "otp":
                    try:
                        entered_otp = int(text.strip())
                    except:
                        send_message(chat_id, "❌ Enter numbers only for OTP.")
                        continue
                    otp_data = otp_store.get(chat_id)
                    if not otp_data or time.time() > otp_data["expires"]:
                        send_message(chat_id, "❌ OTP expired. Enter /start again.")
                        pending.pop(chat_id, None)
                        otp_store.pop(chat_id, None)
                        continue
                    if entered_otp != otp_data["otp"]:
                        send_message(chat_id, "❌ Wrong OTP. Try again.")
                        continue
                    state["step"] = "dept"
                    send_message(chat_id, "Enter your Department (CSE / MECH / ECE / AIDS / AI&DS):")
                    continue

                if step == "dept":
                    dept_input = text.upper().replace(" ", "")
                    if dept_input not in VALID_DEPTS:
                        send_message(chat_id, "❌ Invalid dept! CSE | MECH | ECE | AIDS | AI&DS")
                        continue
                    state["dept"] = dept_input
                    state["step"] = "year"
                    send_message(chat_id, "Enter your Year (I / II / III / IV):")
                    continue

                if step == "year":
                    year_input = text.upper()
                    if year_input not in VALID_YEARS:
                        send_message(chat_id, "❌ Invalid year! I | II | III | IV")
                        continue
                    state["year"] = year_input
                    add_or_update_student(chat_id, state["regno"], name, state["mobile"], state["dept"], state["year"])
                    send_message(chat_id, "🎉 Registration complete! Use /attendance anytime.")
                    pending.pop(chat_id, None)
                    otp_store.pop(chat_id, None)
                    continue

            # ---------------- UPDATE INFO ----------------
            if text == "/updateinfo":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ Not registered yet. Use /start first.")
                    continue
                pending[chat_id] = {"step": "dept_update"}
                send_message(chat_id, "Enter new Department (CSE / MECH / ECE / AIDS / AI&DS):")
                continue

            if chat_id in pending and pending[chat_id].get("step") == "dept_update":
                dept_input = text.upper().replace(" ", "")
                if dept_input not in VALID_DEPTS:
                    send_message(chat_id, "❌ Invalid dept! CSE | MECH | ECE | AIDS | AI&DS")
                    continue
                pending[chat_id]["dept"] = dept_input
                pending[chat_id]["step"] = "year_update"
                send_message(chat_id, "Enter new Year (I / II / III / IV):")
                continue

            if chat_id in pending and pending[chat_id].get("step") == "year_update":
                year_input = text.upper()
                if year_input not in VALID_YEARS:
                    send_message(chat_id, "❌ Invalid year! I | II | III | IV")
                    continue
                student = get_student_by_chat_id(chat_id)
                add_or_update_student(chat_id, student["username"], student["name"], student["mobile"],
                                      pending[chat_id]["dept"], year_input)
                send_message(chat_id, "✅ Department & Year updated successfully!")
                pending.pop(chat_id, None)
                continue

            # ---------------- ATTENDANCE ----------------
            if text == "/attendance":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ Not registered. Use /start.")
                    continue
                subs = SUBJECT_MAP.get((student["department"], student["year"]), [])
                if not subs:
                    send_message(chat_id, "⚠️ No subjects mapped. Contact admin.")
                    continue
                send_message(chat_id, "⏳ Fetching attendance...")
                att = fetch_attendance(student["username"])
                if not att:
                    send_message(chat_id, "⚠️ Could not fetch attendance.")
                    continue
                overall = avg_attendance(att, subs)
                lines = [f"📊 Attendance for {student['name']} ({student['department']} {student['year']}):"]
                for s in subs:
                    val = att.get(s, 'N/A')
                    lines.append(f"• {s}: {val}")
                if overall:
                    lines.append(f"\nOVERALL: {overall}%")
                send_message(chat_id, "\n".join(lines))
                continue

            if text.startswith("/"):
                send_message(chat_id, "⚠️ Unknown command. Use /start, /attendance, or /updateinfo.")
                continue

            send_message(chat_id, "🤖 Invalid input. Use /start, /attendance, or /updateinfo.")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    threading.Thread(target=attendance_monitor, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    log("🚀 Bot started and running...")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        log("🛑 Bot stopped manually.")
