import os
import json
import time
import csv
import threading
import requests
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
API_URL = "https://care.srmuniv.ac.in/attendence/api"  # Replace with your correct API URL

STUDENTS_CSV = "students.csv"
ATTENDANCE_JSON = "attendance_data.json"
OFFSET_FILE = "offset.txt"

# --- Helper Functions ---

def read_students():
    students = []
    if os.path.exists(STUDENTS_CSV):
        with open(STUDENTS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                students.append(row)
    return students


def save_json(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def fetch_attendance(username):
    """
    Sends API request using register_num and function=sva
    """
    try:
        payload = {
            "register_num": username,
            "function": "sva"
        }
        response = requests.post(API_URL, json=payload)

        if response.status_code == 200:
            data = response.json()
            if data.get("success") and "result" in data:
                attendance_list = data["result"]["attendance"]
                attendance_data = {
                    item["sub_code"]: float(item["attendance_percentage"])
                    for item in attendance_list
                    if "attendance_percentage" in item and item["attendance_percentage"] not in (None, "")
                }
                overall = sum(attendance_data.values()) / len(attendance_data) if attendance_data else 0
                attendance_data["OVERALL"] = round(overall, 2)
                return attendance_data
            else:
                print(f"⚠️ Invalid response: {data}")
                return None
        else:
            print(f"❌ HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ Error fetching attendance for {username}: {e}")
        return None


# --- Telegram Bot Logic ---

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        response = requests.get(url, params=params)
        return response.json()
    except Exception as e:
        print(f"⚠️ Error getting updates: {e}")
        return {}


def telegram_listener():
    print("📡 Bot live! Listening for commands...")
    last_update_id = 0
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            content = f.read().strip()
            if content.isdigit():
                last_update_id = int(content)

    students = read_students()

    while True:
        updates = get_updates(offset=last_update_id + 1)
        if "result" in updates:
            for update in updates["result"]:
                last_update_id = update["update_id"]
                with open(OFFSET_FILE, "w") as f:
                    f.write(str(last_update_id))

                if "message" in update:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"].get("text", "").strip().lower()

                    if text == "/start":
                        send_message(chat_id, "👋 Hey there! Use /attendance to check your attendance.")
                    elif text == "/attendance":
                        send_message(chat_id, "⏳ Fetching your current attendance...")
                        student = next((s for s in students if str(s["chat_id"]) == str(chat_id)), None)
                        if not student:
                            send_message(chat_id, "⚠️ You are not registered in the system.")
                            continue
                        attendance_data = fetch_attendance(student["username"])
                        if attendance_data and "OVERALL" in attendance_data:
                            send_message(chat_id, f"✅ Your overall attendance is {attendance_data['OVERALL']}%")
                        else:
                            send_message(chat_id, "⚠️ Could not fetch attendance. Try again later.")
                    else:
                        send_message(chat_id, "🤖 Unknown command. Try /attendance")

        time.sleep(2)


# --- Attendance Monitor ---

def attendance_monitor():
    print("⏱️ Attendance monitor started...")
    students = read_students()
    old_data = load_json(ATTENDANCE_JSON)

    while True:
        print("⏱️ Checking attendance...")
        new_data = {}
        for student in students:
            username = student["username"]
            chat_id = student["chat_id"]
            attendance = fetch_attendance(username)
            if attendance:
                new_data[username] = attendance
                if username in old_data:
                    for subject, percent in attendance.items():
                        if subject in old_data[username] and percent != old_data[username][subject]:
                            send_message(chat_id, f"📊 {subject} attendance changed: {old_data[username][subject]}% ➜ {percent}%")
                else:
                    send_message(chat_id, f"📢 Attendance data updated! Overall: {attendance['OVERALL']}%")
        save_json(new_data, ATTENDANCE_JSON)
        old_data = new_data
        print("✅ Attendance check complete. Sleeping 10 mins...")
        time.sleep(600)  # check every 10 minutes


# --- Main ---

if __name__ == "__main__":
    threading.Thread(target=telegram_listener, daemon=True).start()
    attendance_monitor()
