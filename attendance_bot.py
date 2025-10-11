import requests
import csv
import time
import json
import os
import threading
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller
import time


BOT_TOKEN = "8309149752:AAF-ydD1e3ljBjoVwu8vPJCOue14YeQPfoY"
CSV_FILE = "students.csv"
DATA_FILE = "attendance_data.json"
OFFSET_FILE = "offset.txt"
CHAT_HISTORY_FILE = "chat_history.csv"
HIGHLIGHTED_SUBJECTS = ["CBM348", "GE3791", "AI3021", "OIM352", "GE3751"]

pending_usernames = {}
pending_passwords = {}
changing_password = {}
admin_chat_id = "1718437414"
broadcast_mode = {}

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

def log_chat_interaction(chat_id, username, message_text):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        file_exists = os.path.isfile(CHAT_HISTORY_FILE)
        with open(CHAT_HISTORY_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "chat_id", "username", "message_text"])
            writer.writerow([timestamp, chat_id, username, message_text])
        print(f"Logged chat: {timestamp} - {chat_id} - {username} - {message_text}")
    except Exception as e:
        print(f"Error logging chat interaction: {e}")

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
    except Exception as e:
        print(f"❌ Error in get_updates: {e}")
        return [], offset

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"❌ Failed to send message: {e}")

def broadcast_to_all(message):
    students = load_students()
    sent_to = set()
    for student in students:
        chat_id = normalize_id(student.get("chat_id", ""))
        if chat_id and chat_id not in sent_to:
            try:
                send_message(chat_id, f"📢 Admin Message:\n{message}")
                sent_to.add(chat_id)
            except Exception as e:
                print(f"❌ Failed to send to {chat_id}: {e}")

def load_students():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["username", "password", "name", "chat_id"])
            writer.writeheader()
    students = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append({
                "username": (row.get("username") or "").strip(),
                "password": (row.get("password") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "chat_id": (row.get("chat_id") or "").strip()
            })
    return students

def save_students(students):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "password", "name", "chat_id"])
        writer.writeheader()
        writer.writerows(students)

def get_student_by_chat_id(chat_id):
    nid = normalize_id(chat_id)
    for s in load_students():
        if normalize_id(s.get("chat_id", "")) == nid and nid != "":
            return s
    return None

def add_or_update_student(chat_id, username, password, name):
    students = load_students()
    username = (username or "").strip()
    chat_id = normalize_id(chat_id)
    updated = False
    for s in students:
        if s["username"] == username:
            s["password"] = password
            s["chat_id"] = chat_id
            s["name"] = name
            updated = True
            break
    if not updated:
        students.append({
            "username": username,
            "password": password,
            "name": name,
            "chat_id": chat_id
        })
    save_students(students)
    send_message(chat_id, f"✅ You are now registered successfully, {name}!")
    print(f"[INFO] Registered/Updated: username={username}, chat_id={chat_id}, name={name}")

def change_password(chat_id, new_password):
    nid = normalize_id(chat_id)
    students = load_students()
    for s in students:
        if normalize_id(s.get("chat_id", "")) == nid:
            s["password"] = new_password
            save_students(students)
            send_message(chat_id, "🔒 Your password has been changed successfully!")
            print(f"[INFO] Password changed for chat_id={nid}")
            return
    send_message(chat_id, "⚠️ You are not registered. Use /start to register first.")
    print(f"[WARN] change_password called but chat_id not found: {nid}")

def load_old_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_new_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def attendance_monitor():
    while True:
        print("⏱️ Running attendance check...")
        old_data = load_old_data()
        students = load_students()
        for student in students:
            username = student["username"]
            password = student["password"]
            chat_id = student["chat_id"]
            name = student["name"]
            if not chat_id or not username or not password:
                continue

            attendance = fetch_attendance(username, password)
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
                    lines.append("🚨 Your overall attendance is below 75%. Please improve.")
                elif overall < 80:
                    lines.append("⚠️ Warning! Your overall attendance is near 75%.")
                if dropped_subjects:
                    lines.append("📉 Attendance dropped in:")
                    lines.extend([f"• {s}" for s in dropped_subjects])
                lines.append(f"📊 Overall: {overall:.2f}%")
                message = "\n".join(lines)
                send_message(chat_id, message)

            old_data[username] = attendance
        save_new_data(old_data)
        print("⏱️ Attendance check complete. Sleeping 10 mins...")
        time.sleep(600)
def fetch_attendance(username, password):
    """
    Logs into CARE CRM, clicks Attendance tab, fetches attendance,
    returns a dictionary like: {'CBM348': 85.0, 'GE3791': 90.0, 'OVERALL': 87.5}
    """
    attendance = {}
    driver = None
    try:
        # ✅ Auto install ChromeDriver
        chromedriver_autoinstaller.install()

        # ✅ Headless Chrome options for Linux
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # ✅ Start driver
        driver = webdriver.Chrome(options=chrome_options)
        driver.get("https://crm.care.ac.in/login.html")

        # ✅ Login
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login_id"))).send_keys(username)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.ID, "login_button").click()

        # ✅ Wait for dashboard
        dashboard_element = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(text(),'Attendance')]"))
        )
        driver.execute_script("arguments[0].click();", dashboard_element)
        time.sleep(3)  # wait for JS

        # ✅ Check iframe if attendance table inside
        try:
            iframe = driver.find_element(By.TAG_NAME, "iframe")
            driver.switch_to.frame(iframe)
        except:
            pass

        # ✅ Wait for table
        table = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "table"))
        )

        # ✅ Read attendance
        rows = table.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 3:
                code = cols[0].text.strip()
                perc = cols[2].text.strip().replace(",", ".")
                if "%" in perc and code in HIGHLIGHTED_SUBJECTS:
                    try:
                        attendance[code] = float(perc.replace("%", "").strip())
                    except ValueError:
                        print(f"⚠️ Could not parse {perc} for {code}")

        # ✅ Calculate overall
        if attendance:
            highlighted_values = [v for k, v in attendance.items() if k in HIGHLIGHTED_SUBJECTS]
            if highlighted_values:
                overall = sum(highlighted_values) / len(highlighted_values)
                attendance["OVERALL"] = round(overall, 2)

        return attendance

    except Exception as e:
        print(f"❌ Error fetching attendance for {username}: {e}")
        import traceback
        traceback.print_exc()
        return {}

    finally:
        if driver:
            driver.quit()
def telegram_listener():
    print("📡 Bot is live. Listening for /start, /changepass, /attendance, and admin commands...")
    offset = load_offset()
    while True:
        updates, offset = get_updates(offset)
        for update in updates:
            message = update.get("message", {})
            text = (message.get("text") or "").strip()
            chat_id = normalize_id(message.get("chat", {}).get("id", ""))
            name = message.get("chat", {}).get("first_name", "User")

            log_chat_interaction(chat_id, name, text)
            print(f"[DEBUG] Incoming: chat_id={chat_id}, text='{text}'")

            # ------------------ Admin Broadcast ------------------
            if chat_id == admin_chat_id:
                if text == "/broadcast":
                    send_message(chat_id, "📢 Enter the message to broadcast to all users:")
                    broadcast_mode[chat_id] = True
                    continue
                elif broadcast_mode.get(chat_id):
                    broadcast_to_all(text)
                    send_message(chat_id, "✅ Broadcast sent successfully.")
                    broadcast_mode.pop(chat_id)
                    continue
            elif text == "/broadcast":
                send_message(chat_id, "❌ You are not authorized to use this command.")
                continue

            # ------------------ /start Registration ------------------
            if text == "/start":
                existing = get_student_by_chat_id(chat_id)
                if existing:
                    send_message(chat_id, f"✅ You’re already registered, {existing.get('name','User')}!")
                    continue
                send_message(chat_id, f"Hi {name}! Please enter your CARE register number to start registration.")
                pending_usernames[chat_id] = True
                continue

            # ------------------ Handle username input ------------------
            if pending_usernames.get(chat_id):
                if text.startswith("8107") and len(text) >= 6:
                    pending_usernames.pop(chat_id, None)
                    pending_passwords[chat_id] = text
                    send_message(chat_id, "Great! Now please enter your password:")
                else:
                    send_message(chat_id, "⚠️ Invalid register number. Try again (must start with 8107).")
                continue

            # ------------------ Handle password input ------------------
            if pending_passwords.get(chat_id):
                username = pending_passwords.pop(chat_id, None)
                password = text
                add_or_update_student(chat_id, username, password, name)
                continue

            # ------------------ /changepass ------------------
            if text == "/changepass":
                existing = get_student_by_chat_id(chat_id)
                if not existing:
                    send_message(chat_id, "⚠️ You are not registered yet. Use /start to register first.")
                    continue
                send_message(chat_id, "🔑 Please enter your new password:")
                changing_password[chat_id] = True
                continue

            if changing_password.get(chat_id):
                new_password = text
                changing_password.pop(chat_id, None)
                change_password(chat_id, new_password)
                continue

            # ------------------ /attendance ------------------
            if text == "/attendance":
                student = get_student_by_chat_id(chat_id)
                if not student:
                    send_message(chat_id, "⚠️ You are not registered yet. Use /start to register first.")
                    continue

                send_message(chat_id, "⏳ Fetching your current attendance, please wait...")

                attendance_data = fetch_attendance(student["username"], student["password"])
                if not attendance_data:
                    send_message(chat_id, "⚠️ Could not fetch attendance. Check your credentials or try later.")
                    continue

                overall = attendance_data.get("OVERALL")
                if overall is not None:
                    send_message(chat_id, f"✅ Your overall attendance is {overall:.2f}%")
                else:
                    send_message(chat_id, "⚠️ Attendance data not found.")
                continue  # important to skip default unknown

            # ------------------ Unknown command ------------------
            if text.startswith("/"):
                send_message(chat_id, "⚠️ Unknown command.")
                continue

            # ------------------ Default reply for normal messages ------------------
            send_message(chat_id, "⚠️ Don’t send unwanted messages... You are being monitored!!!.")
            

def attendance_monitor():
    while True:
        print("⏱️ Running attendance check...")
        old_data = load_old_data()
        students = load_students()
        for student in students:
            username = student["username"]
            password = student["password"]
            chat_id = student["chat_id"]
            name = student["name"]
            if not chat_id or not username or not password:
                continue

            attendance = fetch_attendance(username, password)
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
                    lines.append("🚨 Your overall attendance is below 75%. Please improve.")
                elif overall < 80:
                    lines.append("⚠️ Warning! Your overall attendance is near 75%.")
                if dropped_subjects:
                    lines.append("📉 Attendance dropped in:")
                    lines.extend([f"• {s}" for s in dropped_subjects])
                lines.append(f"📊 Overall: {overall:.2f}%")
                message = "\n".join(lines)
                send_message(chat_id, message)

            old_data[username] = attendance
        save_new_data(old_data)
        print("⏱️ Attendance check complete. Sleeping 10 mins...")
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=attendance_monitor, daemon=True).start()
    while True:
        time.sleep(10)
