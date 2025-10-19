#!/usr/bin/env python3
"""
Telegram attendance bot (clean copy with agreement and fixed drop alert).
Features:
 - /start registration (agreement, register number, department, year)
 - /attendance -> fetches attendance for mapped subjects and replies
 - Background attendance_monitor -> periodic checks & alerts
"""

import os
import csv
import json
import time
import threading
import requests
from datetime import datetime

# ------------- CONFIG -------------
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"  # replace if needed
ADMIN_CHAT_ID = "1718437414"
CSV_FILE = "students.csv"
DATA_FILE = "attendance.json"
OFFSET_FILE = "offset.txt"

SUBJECT_MAP = {
    ("CSE", "IV"): ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"],
    ("CSE", "III"): ["CS3351", "CS3352", "CS3353"],
    ("ECE", "IV"): ["EC4001", "EC4002", "EC4003"],
}

CARE_API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"
MONITOR_INTERVAL = 10 * 60  # 10 minutes

# ------------- UTILITIES -------------
def normalize_id(x):
    return str(x).strip()

def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")

def send_message(chat_id: str, text: str, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log(f"send_message error: {e}")

def load_offset():
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, "r") as f:
                return int(f.read().strip())
        except:
            return None
    return None

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=110)
        r.raise_for_status()
        data = r.json().get("result", [])
        if data:
            offset = data[-1]["update_id"] + 1
            save_offset(offset)
        return data, offset
    except Exception as e:
        log(f"get_updates error: {e}")
        return [], offset

# ------------- STUDENT STORAGE -------------
def ensure_csv_exists():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id", "department", "year"])
            writer.writeheader()

def load_students():
    ensure_csv_exists()
    students = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append({
                "username": (row.get("username") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "chat_id": (row.get("chat_id") or "").strip(),
                "department": (row.get("department") or "").strip().upper(),
                "year": (row.get("year") or "").strip().upper()
            })
    return students

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "name", "chat_id", "department", "year"])
        writer.writeheader()
        writer.writerows(students)

def get_student_by_chat_id(chat_id):
    nid = normalize_id(chat_id)
    for s in load_students():
        if normalize_id(s.get("chat_id", "")) == nid and nid != "":
            return s
    return None

def add_or_update_student_record(chat_id, username, name, department, year):
    students = load_students()
    username = username.strip()
    department = (department or "").strip().upper()
    year = (year or "").strip().upper()
    chat_id = normalize_id(chat_id)

    updated = False
    for s in students:
        if s["username"] == username:
            s.update({"name": name, "chat_id": chat_id, "department": department, "year": year})
            updated = True
            break
    if not updated:
        students.append({"username": username, "name": name, "chat_id": chat_id, "department": department, "year": year})
    save_students(students)
    log(f"Saved student: {username} | {name} | {department} | {year} | chat:{chat_id}")

# ------------- ATTENDANCE FETCH -------------
def fetch_attendance_api(register_num):
    try:
        payload = {"register_num": register_num, "function": "sva"}
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        r = requests.post(CARE_API_URL, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("success") and "result" in data and "attendance" in data["result"]:
            attendance = {}
            for item in data["result"]["attendance"]:
                code = (item.get("sub_code") or "").strip()
                try:
                    val = float(item.get("attendance_percentage") or 0)
                except:
                    continue
                if code:
                    attendance[code] = val
            return attendance
        else:
            return {}
    except Exception as e:
        log(f"fetch_attendance_api error for {register_num}: {e}")
        return {}

def compute_overall_for_subjects(attendance_dict, subjects):
    vals = [attendance_dict[s] for s in subjects if s in attendance_dict]
    if not vals: return None
    return round(sum(vals) / len(vals), 2)

# ------------- BACKGROUND MONITOR -------------
def load_old_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_new_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def attendance_monitor():
    log("Attendance monitor started.")
    while True:
        try:
            old_data = load_old_data()
            students = load_students()
            for st in students:
                username = st.get("username")
                chat_id = st.get("chat_id")
                name = st.get("name")
                dept = st.get("department")
                year = st.get("year")
                if not username or not chat_id: continue

                subjects = SUBJECT_MAP.get((dept, year), [])
                if not subjects: continue

                att = fetch_attendance_api(username)
                if not att: continue

                overall = compute_overall_for_subjects(att, subjects)
                if overall is not None: att["OVERALL"] = overall

                dropped = []
                prev = old_data.get(username, {})
                for code in subjects:
                    old_val = prev.get(code)
                    new_val = att.get(code)
                    if old_val is not None and new_val is not None:
                        if new_val < old_val - 0.01:  # only real drop
                            dropped.append(f"{code}: {old_val:.2f}% → {new_val:.2f}%")

                if (att.get("OVERALL") is not None and att["OVERALL"] < 80) or dropped:
                    lines = [f"Dear {name},"]
                    if att.get("OVERALL") is not None:
                        if att["OVERALL"] < 75: lines.append(f"🚨 Overall below 75% ({att['OVERALL']:.2f}%)")
                        elif att["OVERALL"] < 80: lines.append(f"⚠️ Overall near 75% ({att['OVERALL']:.2f}%)")
                    if dropped:
                        lines.append("📉 Attendance dropped in:")
                        lines.extend([f"• {d}" for d in dropped])
                    lines.append("\n📊 Current highlighted subjects:")
                    for code in subjects:
                        if code in att: lines.append(f"• {code}: {att[code]:.2f}%")
                    send_message(chat_id, "\n".join(lines))
                    log(f"Alert sent to {username} ({chat_id})")

                # save snapshot for next comparison
                old_data[username] = {k: v for k, v in att.items() if k != "OVERALL"}
            save_new_data(old_data)
        except Exception as e:
            log(f"attendance_monitor loop error: {e}")
        time.sleep(MONITOR_INTERVAL)

# ------------- TELEGRAM LISTENER -------------
pending_registration = {}

def telegram_listener():
    log("Telegram listener started.")
    offset = load_offset()
    while True:
        updates, offset = get_updates(offset)
        for update in updates:
            message = update.get("message", {}) or {}
            text = (message.get("text") or "").strip()
            chat = message.get("chat", {}) or {}
            chat_id = normalize_id(chat.get("id", ""))
            name = (chat.get("first_name") or "Student").strip()
            log(f"Incoming from {chat_id}: {text}")

            # Start agreement step
            if text == "/start":
                existing = get_student_by_chat_id(chat_id)
                if existing:
                    send_message(chat_id, f"✅ Already registered as {existing.get('name')}. Use /attendance.")
                    continue
                send_message(chat_id, f"Hi {name}! Before registration, please agree to company policies. Do you agree?", 
                             reply_markup={"inline_keyboard":[[{"text":"Agree","callback_data":"agree"},{"text":"Disagree","callback_data":"disagree"}]]})
                pending_registration[chat_id] = {"step":"agreement"}
                continue

            # Handle agreement button clicks (via text fallback)
            if chat_id in pending_registration:
                state = pending_registration[chat_id]
                step = state.get("step")
                if step == "agreement":
                    if text.lower() == "agree":
                        state["step"] = "regno"
                        send_message(chat_id, "Great! Enter your CARE Register Number (must start with 8107):")
                        continue
                    else:
                        send_message(chat_id, "⚠️ You must agree to continue registration.")
                        pending_registration.pop(chat_id, None)
                        continue

                # Registration steps
                if step == "regno":
                    if not text.startswith("8107"):
                        send_message(chat_id, "⚠️ Invalid register number. Try again.")
                        continue
                    state["regno"] = text
                    state["step"] = "dept"
                    send_message(chat_id, "Enter your Department (e.g., CSE, ECE):")
                    continue

                if step == "dept":
                    state["department"] = text.strip().upper()
                    state["step"] = "year"
                    send_message(chat_id, "Enter your Year (I / II / III / IV):")
                    continue

                if step == "year":
                    state["year"] = text.strip().upper()
                    add_or_update_student_record(chat_id, state["regno"], name, state["department"], state["year"])
                    send_message(chat_id, "✅ Registered! Use /attendance to fetch your attendance anytime.")
                    pending_registration.pop(chat_id, None)
                    continue

            # /attendance command
            if text == "/attendance":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ Not registered. Use /start.")
                    continue
                subjects = SUBJECT_MAP.get((student.get("department"), student.get("year")), [])
                if not subjects:
                    send_message(chat_id, "⚠️ No subject mapping. Contact admin.")
                    continue
                send_message(chat_id, "⏳ Fetching your attendance, please wait...")
                att = fetch_attendance_api(student["username"])
                if not att:
                    send_message(chat_id, "⚠️ Could not fetch attendance. Try later.")
                    continue
                overall = compute_overall_for_subjects(att, subjects)
                lines = [f"📊 Attendance for {student.get('name')} ({student.get('department')} {student.get('year')}):"]
                for code in subjects:
                    lines.append(f"• {code}: {att.get(code,'N/A') if code in att else 'N/A'}")
                if overall: 
                    lines.append(f"\nOVERALL: {overall:.2f}%")
                send_message(chat_id, "\n".join(lines))
                continue

            # Unknown
            if text.startswith("/"):
                send_message(chat_id, "⚠️ Unknown command. Use /start or /attendance.")
                continue
            send_message(chat_id, "⚠️ Invalid input. Use /start or /attendance.")

# ------------- MAIN -------------
if __name__ == "__main__":
    threading.Thread(target=attendance_monitor, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    log("Bot started. Press Ctrl+C to stop.")
    try:
        while True: time.sleep(10)
    except KeyboardInterrupt:
        log("Shutting down...")
