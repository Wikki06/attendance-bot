import os
import csv
import json
import time
import threading
import random
import requests
from datetime import datetime

# ---------------- CONFIG ----------------
BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
OTP_BOT_TOKEN = "8231642363:AAHsqbj4Y43yEqELaYzb95x7f81XNkI6SSE"  # External OTP bot
ADMIN_CHAT_ID = "1718437414"
CSV_FILE = "students.csv"
DATA_FILE = "attendance.json"
OTP_FILE = "otp_data.json"
MONITOR_INTERVAL = 10 * 60  # 10 mins
OTP_EXPIRY = 300  # 5 minutes

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

def send_message(chat_id, text, reply_markup=None, bot_token=BOT_TOKEN):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log(f"send_message error: {e}")

# ---------------- STUDENT STORAGE ----------------
def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username","name","chat_id","mobile","department","year"])
            writer.writeheader()

def load_students():
    ensure_csv()
    with open(CSV_FILE,"r",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def save_students(students):
    with open(CSV_FILE,"w",newline="",encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f,fieldnames=["username","name","chat_id","mobile","department","year"])
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
            s.update({"chat_id": chat_id,"name":name,"mobile":mobile,"department":dept,"year":year})
            save_students(students)
            return
    students.append({"username":username,"name":name,"chat_id":chat_id,"mobile":mobile,"department":dept,"year":year})
    save_students(students)
    log(f"Saved {username}|{name}|{mobile}|{dept}|{year}")

# ---------------- OTP ----------------
def load_otp_data():
    if os.path.exists(OTP_FILE):
        with open(OTP_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_otp_data(data):
    with open(OTP_FILE,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=2)

def generate_otp():
    return random.randint(100000,999999)

def send_otp(chat_id, otp):
    send_message(chat_id, f"📩 Your OTP is: {otp}", bot_token=OTP_BOT_TOKEN)

# ---------------- ATTENDANCE ----------------
CARE_API_URL = "https://3xlmsxcyn0.execute-api.ap-south-1.amazonaws.com/Prod/CRM-StudentApp"

def fetch_attendance(register_num):
    try:
        payload = {"register_num": register_num,"function":"sva"}
        r = requests.post(CARE_API_URL,json=payload,timeout=15)
        r.raise_for_status()
        data = r.json()
        att = {}
        for i in data.get("result",{}).get("attendance",[]):
            code = i.get("sub_code","")
            try:
                att[code]=float(i.get("attendance_percentage",0))
            except:
                pass
        return att
    except Exception as e:
        log(f"fetch_attendance error: {e}")
        return {}

def avg_attendance(att, subjects):
    vals = [att[s] for s in subjects if s in att]
    return round(sum(vals)/len(vals),2) if vals else None

# ---------------- MONITOR ----------------
def load_json():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(data):
    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=2)

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
                subs = SUBJECT_MAP.get((dept, year),[])
                if not subs: continue
                att = fetch_attendance(reg)
                if not att: continue
                overall = avg_attendance(att,subs)
                att["OVERALL"]=overall
                drops=[]
                for sub in subs:
                    old=prev_data.get(reg,{}).get(sub)
                    new=att.get(sub)
                    if old and new and new<old-0.01:
                        drops.append(f"{sub}: {old:.2f}%→{new:.2f}%")
                if overall and (overall<80 or drops):
                    msg=[f"Dear {name},"]
                    if overall<75: msg.append(f"🚨 Overall below 75% ({overall}%)")
                    elif overall<80: msg.append(f"⚠️ Overall near limit ({overall}%)")
                    if drops: 
                        msg.append("📉 Drop detected:")
                        msg+=[f"• {d}" for d in drops]
                    msg.append("\n📊 Subjects:")
                    for sub in subs:
                        if sub in att:
                            msg.append(f"• {sub}: {att[sub]:.2f}%")
                    send_message(chat,"\n".join(msg))
                prev_data[reg]=att
            save_json(prev_data)
        except Exception as e:
            log(f"monitor error: {e}")
        time.sleep(MONITOR_INTERVAL)

# ---------------- TELEGRAM LISTENER ----------------
pending={}

def telegram_listener():
    log("💬 Telegram listener running...")
    offset=None
    while True:
        updates, offset = get_updates(offset)
        for upd in updates:
            msg=upd.get("message",{})
            text=(msg.get("text") or "").strip()
            chat_id=str(msg.get("chat",{}).get("id",""))
            name=msg.get("chat",{}).get("first_name","Student")

            # ADMIN COMMANDS
            if chat_id==ADMIN_CHAT_ID:
                if text.startswith("/broadcast "):
                    message=text.replace("/broadcast ","").strip()
                    if not message:
                        send_message(chat_id,"⚠️ Usage: /broadcast <message>")
                        continue
                    for s in load_students():
                        send_message(s["chat_id"],f"📢 Announcement:\n{message}")
                    send_message(chat_id,"✅ Broadcast sent.")
                    continue
                if text.startswith("/remove_user "):
                    ident=text.split(" ",1)[1].strip()
                    removed=remove_user(ident)
                    send_message(chat_id,f"🗑️ Removed {removed} user(s) with ID/Reg: {ident}")
                    continue

            # START FLOW
            if text=="/start":
                if get_student_by_chat_id(chat_id):
                    send_message(chat_id,"✅ Already registered. Use /attendance.")
                    continue
                pending[chat_id]={"step":"regno"}
                send_message(chat_id,"Hi! Enter your CARE Register Number (starts with 8107):")
                continue

            # PENDING FLOW
            if chat_id in pending:
                state=pending[chat_id]
                step=state.get("step")
                if step=="regno":
                    if not text.startswith("8107"):
                        send_message(chat_id,"⚠️ Invalid RegNo. Must start with 8107.")
                        continue
                    state["regno"]=text
                    state["step"]="mobile"
                    send_message(chat_id,"Enter your Mobile Number:")
                    continue
                if step=="mobile":
                    mobile=text.strip()
                    if not mobile.isdigit() or len(mobile)<10:
                        send_message(chat_id,"⚠️ Enter valid mobile number (digits only).")
                        continue
                    state["mobile"]=mobile
                    otp=generate_otp()
                    otp_data=load_otp_data()
                    otp_data[chat_id]={"otp":otp,"mobile":mobile,"regno":state["regno"],"timestamp":time.time()}
                    save_otp_data(otp_data)
                    send_otp(chat_id,otp)
                    state["step"]="otp"
                    send_message(chat_id,"Enter the OTP sent to your Telegram:")
                    continue
                if step=="otp":
                    otp_data=load_otp_data()
                    entry=otp_data.get(chat_id)
                    if not entry:
                        send_message(chat_id,"⚠️ No OTP found. Please restart /start.")
                        pending.pop(chat_id,None)
                        continue
                    if time.time()-entry["timestamp"]>OTP_EXPIRY:
                        send_message(chat_id,"⚠️ OTP expired. Restart /start.")
                        otp_data.pop(chat_id)
                        save_otp_data(otp_data)
                        pending.pop(chat_id,None)
                        continue
                    if text.strip()!=str(entry["otp"]):
                        send_message(chat_id,"❌ Wrong OTP. Try again.")
                        continue
                    # OTP verified, ask for dept
                    state["step"]="dept"
                    send_message(chat_id,"Enter your Department (CSE, MECH, ECE, AIDS, AI&DS):")
                    continue
                if step=="dept":
                    dept=text.upper().strip()
                    if dept not in VALID_DEPTS:
                        send_message(chat_id,"⚠️ Dept must be one of: CSE, MECH, ECE, AIDS, AI&DS")
                        continue
                    state["dept"]=dept
                    state["step"]="year"
                    send_message(chat_id,"Enter your Year (I, II, III, IV):")
                    continue
                if step=="year":
                    year=text.upper().strip()
                    if year not in VALID_YEARS:
                        send_message(chat_id,"⚠️ Year must be: I, II, III, IV")
                        continue
                    state["year"]=year
                    add_or_update_student(chat_id,state["regno"],name,state["mobile"],state["dept"],state["year"])
                    send_message(chat_id,"🎉 Registration complete! Use /attendance anytime.")
                    otp_data=load_otp_data()
                    otp_data.pop(chat_id,None)
                    save_otp_data(otp_data)
                    pending.pop(chat_id,None)
                    continue

            # ATTENDANCE COMMAND
            if text=="/attendance":
                student=get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id,"⚠️ Not registered. Use /start.")
                    continue
                subs=SUBJECT_MAP.get((student["department"],student["year"]),[])
                if not subs:
                    send_message(chat_id,"⚠️ No subjects mapped. Contact admin.")
                    continue
                send_message(chat_id,"⏳ Fetching attendance...")
                att=fetch_attendance(student["username"])
                if not att:
                    send_message(chat_id,"⚠️ Could not fetch attendance.")
                    continue
                overall=avg_attendance(att,subs)
                lines=[f"📊 Attendance for {student['name']} ({student['department']} {student['year']}):"]
                for s in subs:
                    val=att.get(s,'N/A')
                    lines.append(f"• {s}: {val}")
                if overall: lines.append(f"\nOVERALL: {overall}%")
                send_message(chat_id,"\n".join(lines))
                continue

            if text.startswith("/"):
                send_message(chat_id,"⚠️ Unknown command. Use /start or /attendance.")
                continue

            send_message(chat_id,"🤖 Invalid input. Use /start or /attendance.")

# ---------------- MAIN ----------------
if __name__=="__main__":
    threading.Thread(target=attendance_monitor,daemon=True).start()
    threading.Thread(target=telegram_listener,daemon=True).start()
    log("🚀 Bot started and running...")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        log("🛑 Bot stopped manually.")
