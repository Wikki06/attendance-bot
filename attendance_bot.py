#!/usr/bin/env python3
"""
Telegram Attendance Bot — OTP via Email (by Vignesh)
Features:
- /start -> RegNo -> Email -> OTP (sent to email) -> Dept & Year validation -> store
- /updateinfo to change dept/year (self only)
- /attendance to fetch attendance from CARE API
- Admin commands: /broadcast & /remove_user
- Background attendance monitor
"""

import os
import csv
import json
import time
import threading
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import requests

# ---------------- CONFIG ----------------
BOT_TOKEN = "8231642363:AAHsqbj4Y43yEqELaYzb95x7f81XNkI6SSE"
ADMIN_CHAT_ID = "1718437414"  # as string, e.g. "1718437414"
CSV_FILE = "students.csv"
DATA_FILE = "attendance.json"
OTP_FILE = "otp_data.json"
MONITOR_INTERVAL = 10 * 60  # seconds
OTP_EXPIRY = 300  # 5 minutes

# SMTP (EMAIL) CONFIG - fill these
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "careattendancebot@gmail.com"     # sender email address
SMTP_PASS = "uwpxqmvcbputaooa"     # app password or SMTP password

# SUBJECT MAP and valid values
SUBJECT_MAP = {
    ("CSE", "IV"): ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"],
    ("CSE", "III"): ["CS3351", "CS3352", "CS3353"],
    ("ECE", "IV"): ["EC4001", "EC4002", "EC4003"],
}

VALID_DEPTS = {"CSE", "MECH", "ECE", "AIDS", "AI&DS"}
VALID_YEARS = {"I", "II", "III", "IV"}

# CARE API (as before)
CARE_API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"

# ---------------- UTILITIES ----------------
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def normalize_id(x):
    return str(x).strip()

def send_message(chat_id, text, reply_markup=None, bot_token=BOT_TOKEN):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
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

# ---------------- STORAGE ----------------
def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username","name","chat_id","email","department","year"])
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["username","name","chat_id","email","department","year"])
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

def add_or_update_student(chat_id, username, name, email, dept, year):
    students = load_students()
    for s in students:
        if s["username"] == username:
            s.update({"chat_id": chat_id, "name": name, "email": email, "department": dept, "year": year})
            save_students(students)
            return
    students.append({"username": username, "name": name, "chat_id": chat_id, "email": email, "department": dept, "year": year})
    save_students(students)
    log(f"Saved {username} | {name} | {email} | {dept} | {year}")

# ---------------- OTP (Email) ----------------
def load_otp_data():
    if os.path.exists(OTP_FILE):
        with open(OTP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_otp_data(data):
    with open(OTP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def generate_otp():
    return random.randint(100000, 999999)

def send_email_otp(to_email, otp, student_reg=None):
    """Send the OTP via SMTP (email). Returns True if send attempt made (not guarantee of delivery)."""
    subject = "Your OTP for Attendance Bot"
    body = f"Your OTP for Attendance Bot is: {otp}\nThis OTP is valid for {OTP_EXPIRY//60} minutes.\n"
    if student_reg:
        body += f"Register Number: {student_reg}\n"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
        server.quit()
        log(f"Sent OTP to email {to_email}")
        return True
    except Exception as e:
        log(f"Error sending email to {to_email}: {e}")
        return False

# ---------------- ATTENDANCE FETCH ----------------
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
    return round(sum(vals)/len(vals), 2) if vals else None

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
                if not subs: continue
                att = fetch_attendance(reg)
                if not att: continue
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
pending = {}  # chat_id -> state dict

def telegram_listener():
    log("💬 Telegram listener running...")
    offset = None
    while True:
        updates, offset = get_updates(offset)
        for upd in updates:
            cb = upd.get("callback_query")
            if cb:
                # no callback handling in this version, but kept for future
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                              data={"callback_query_id": cb["id"]})
                continue

            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            name = msg.get("chat", {}).get("first_name", "Student")

            # ---------------- ADMIN COMMANDS ----------------
            if chat_id == str(ADMIN_CHAT_ID):
                if text.startswith("/broadcast "):
                    message = text.replace("/broadcast ", "").strip()
                    if not message:
                        send_message(chat_id, "⚠️ Usage: /broadcast <message>")
                        continue
                    for s in load_students():
                        send_message(s["chat_id"], f"📢 Announcement:\n{message}")
                    send_message(chat_id, "✅ Broadcast sent.")
                    continue
                if text.startswith("/remove_user "):
                    ident = text.split(" ", 1)[1].strip()
                    removed = remove_user(ident)
                    send_message(chat_id, f"🗑️ Removed {removed} user(s) with ID/Reg: {ident}")
                    continue

            # ---------------- START FLOW ----------------
            if text == "/start":
                if get_student_by_chat_id(chat_id):
                    send_message(chat_id, "✅ Already registered. Use /attendance.")
                    continue
                pending[chat_id] = {"step": "regno"}
                send_message(chat_id, f"Hi {name}! Enter your CARE Register Number (starts with 8107):")
                continue

            # ---------------- PENDING FLOW ----------------
            if chat_id in pending:
                state = pending[chat_id]
                step = state.get("step")

                if step == "regno":
                    regno_input = text.strip()
                    if not regno_input.startswith("8107"):
                        send_message(chat_id, "❌ Invalid register number. Must start with 8107.")
                        continue
                    # Optionally: prevent re-use of regno by other chat_id
                    # If you want to lock a regno once used:
                    # for s in load_students():
                    #     if s["username"] == regno_input and normalize_id(s["chat_id"]) != normalize_id(chat_id):
                    #         send_message(chat_id, "⚠️ This register number is already registered with another account.")
                    #         pending.pop(chat_id, None)
                    #         continue
                    state["regno"] = regno_input
                    state["step"] = "email"
                    send_message(chat_id, "Enter your college email address (e.g. name@college.edu):")
                    continue

                if step == "email":
                    email_input = text.strip()
                    # basic email format check
                    if "@" not in email_input or "." not in email_input.split("@")[-1]:
                        send_message(chat_id, "❌ Invalid email format. Try again (example: name@college.edu).")
                        continue
                    state["email"] = email_input
                    # generate OTP, save to otp_data.json, and send via email
                    otp = generate_otp()
                    otp_data = load_otp_data()
                    otp_data[chat_id] = {
                        "otp": otp,
                        "email": email_input,
                        "regno": state["regno"],
                        "timestamp": time.time()
                    }
                    save_otp_data(otp_data)
                    sent = send_email_otp(email_input, otp, student_reg=state["regno"])
                    state["step"] = "otp"
                    if sent:
                        send_message(chat_id, "📩 OTP sent to your email. Enter the OTP here (valid 5 mins).")
                    else:
                        send_message(chat_id, "⚠️ Failed to send OTP email. Check SMTP settings or email address and retry with /start.")
                        pending.pop(chat_id, None)
                    continue

                if step == "otp":
                    otp_data = load_otp_data()
                    entry = otp_data.get(chat_id)
                    if not entry:
                        send_message(chat_id, "⚠️ No OTP pending. Please restart /start.")
                        pending.pop(chat_id, None)
                        continue
                    if time.time() - entry["timestamp"] > OTP_EXPIRY:
                        send_message(chat_id, "⚠️ OTP expired. Please restart /start.")
                        otp_data.pop(chat_id, None)
                        save_otp_data(otp_data)
                        pending.pop(chat_id, None)
                        continue
                    if text.strip() != str(entry["otp"]):
                        send_message(chat_id, "❌ Wrong OTP. Try again.")
                        continue
                    # OTP verified — proceed to dept
                    state["step"] = "dept"
                    send_message(chat_id, "Enter your Department (CSE / MECH / ECE / AIDS / AI&DS):")
                    continue

                if step == "dept":
                    dept_input = text.upper().replace(" ", "")
                    # normalize AI&DS: accept "AIDS" or "AI&DS" by mapping
                    if dept_input == "AIDS" or dept_input == "AI&DS" or dept_input == "AIDS":
                        dept_input = "AIDS" if dept_input == "AIDS" else "AI&DS" if "AI" in dept_input else dept_input
                    # try to map some variants to valid set
                    # Accept either "AIDS" or "AI&DS" by normalizing to "AI&DS" if user typed AI&DS-like
                    normalized = dept_input
                    # handle simple normalization:
                    if dept_input.replace("&","") == "AIDS":
                        normalized = "AI&DS" if "&" in text or "AI" in text.upper() else "AIDS"
                    # final check: accept user input if the cleaned-up value matches any valid dept name ignoring &/spaces
                    cleaned = dept_input.replace("&","").replace(" ","")
                    allowed_clean = {d.replace("&","").replace(" ","") for d in VALID_DEPTS}
                    if cleaned not in allowed_clean:
                        send_message(chat_id, "❌ Invalid department! Use: CSE | MECH | ECE | AIDS | AI&DS")
                        continue
                    # convert to one of VALID_DEPTS canonical values:
                    # simple mapping:
                    if cleaned == "CSE":
                        dept_canon = "CSE"
                    elif cleaned == "MECH":
                        dept_canon = "MECH"
                    elif cleaned == "ECE":
                        dept_canon = "ECE"
                    elif cleaned == "AIDS":
                        # choose AI&DS canonical (prefer AI&DS)
                        # If user typed 'AIDS' we accept 'AIDS' as well
                        dept_canon = "AI&DS" if "AI" in text.upper() or "&" in text else "AIDS"
                    else:
                        dept_canon = dept_input
                    state["dept"] = dept_canon
                    state["step"] = "year"
                    send_message(chat_id, "Enter your Year (I / II / III / IV):")
                    continue

                if step == "year":
                    year_input = text.upper().strip()
                    if year_input not in VALID_YEARS:
                        send_message(chat_id, "❌ Invalid year! Use: I | II | III | IV")
                        continue
                    state["year"] = year_input
                    # commit user
                    add_or_update_student(chat_id, state["regno"], name, state["email"], state["dept"], state["year"])
                    send_message(chat_id, "🎉 Registration complete! Use /attendance anytime.")
                    # cleanup otp store for this chat
                    otp_data = load_otp_data()
                    otp_data.pop(chat_id, None)
                    save_otp_data(otp_data)
                    pending.pop(chat_id, None)
                    continue

            # ---------------- UPDATE INFO ----------------
            if text == "/updateinfo":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ Not registered. Use /start.")
                    continue
                pending[chat_id] = {"step": "dept_update"}
                send_message(chat_id, "Enter new Department (CSE / MECH / ECE / AIDS / AI&DS):")
                continue

            if chat_id in pending and pending[chat_id].get("step") == "dept_update":
                dept_input = text.upper().replace(" ", "")
                cleaned = dept_input.replace("&","").replace(" ","")
                allowed_clean = {d.replace("&","").replace(" ","") for d in VALID_DEPTS}
                if cleaned not in allowed_clean:
                    send_message(chat_id, "❌ Invalid department! Use: CSE | MECH | ECE | AIDS | AI&DS")
                    continue
                # normalize (simple)
                if cleaned == "CSE": dept_canon = "CSE"
                elif cleaned == "MECH": dept_canon = "MECH"
                elif cleaned == "ECE": dept_canon = "ECE"
                else: dept_canon = "AI&DS"
                pending[chat_id]["dept"] = dept_canon
                pending[chat_id]["step"] = "year_update"
                send_message(chat_id, "Enter new Year (I / II / III / IV):")
                continue

            if chat_id in pending and pending[chat_id].get("step") == "year_update":
                year_input = text.upper().strip()
                if year_input not in VALID_YEARS:
                    send_message(chat_id, "❌ Invalid year! Use: I | II | III | IV")
                    continue
                student = get_student_by_chat_id(chat_id)
                add_or_update_student(chat_id, student["username"], student["name"], student["email"], pending[chat_id]["dept"], year_input)
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

            # Unknown command / message
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
