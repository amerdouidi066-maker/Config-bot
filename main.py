#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 THE ARCHITECT // ULTIMATE BOT v37.0 (ULTIMATE EDITION)
🚀 بوت متكامل مع نظام إدارة مستخدمين، قاعدة بيانات، طابور متقدم، وإعادة محاولة ذكية.
📡 يعمل على المختبرات المؤقتة (Qwiklabs) مع دعم متعدد المستخدمين.
"""

import os, sys, time, re, json, base64, hashlib, tempfile, glob, threading, queue, subprocess, logging, sqlite3, random, string
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ============================================================
# 1. إعدادات التسجيل (Logging)
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. الإعدادات الأساسية (متغيرات البيئة)
# ============================================================
TOKEN = os.environ.get("TOKEN", "توكن_التاعك_هنا")
DEFAULT_EMAIL = os.environ.get("EMAIL", "student-xx@qwiklabs.net")
DEFAULT_PASSWORD = os.environ.get("PASSWORD", "your-password")
MAX_RETRIES = 3
TIMEOUT = 90

# ============================================================
# 3. خادم Flask (Keep-Alive)
# ============================================================
flask_app = Flask('')
@flask_app.route('/')
def home():
    return "✅ THE ARCHITECT // BOT IS ALIVE"

@flask_app.route('/health')
def health():
    return "OK", 200

def keep_alive():
    Thread(target=lambda: flask_app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)).start()
    logger.info("✅ Flask keep-alive server started.")

# ============================================================
# 4. تثبيت المكتبات المطلوبة (تشغيل تلقائي)
# ============================================================
def install_pkg(pkg):
    try:
        __import__(pkg.replace("-", "_"))
    except ImportError:
        logger.info(f"📦 جاري تثبيت {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
        logger.info(f"✅ تم تثبيت {pkg}")

install_pkg("selenium")
install_pkg("webdriver_manager")
install_pkg("rsa")
install_pkg("requests")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import requests, rsa

# ============================================================
# 5. قاعدة البيانات (SQLite) – لإدارة المستخدمين
# ============================================================
DB_PATH = "users.db"

def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول إذا لم تكن موجودة."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            lab_url TEXT,
            last_deploy TIMESTAMP,
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            last_result TEXT,
            region TEXT DEFAULT 'europe-west1'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lab_url TEXT,
            service_url TEXT,
            vless_link TEXT,
            deployed_at TIMESTAMP,
            success INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة.")

def get_user(user_id):
    """استرجاع بيانات المستخدم من قاعدة البيانات."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "email": row[1],
            "password": row[2],
            "lab_url": row[3],
            "last_deploy": row[4],
            "deploy_count": row[5],
            "status": row[6],
            "last_result": row[7],
            "region": row[8]
        }
    return None

def create_or_update_user(user_id, email=None, password=None, lab_url=None, region="europe-west1"):
    """إنشاء أو تحديث بيانات المستخدم."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        c.execute('''
            UPDATE users SET
                email = COALESCE(?, email),
                password = COALESCE(?, password),
                lab_url = COALESCE(?, lab_url),
                region = COALESCE(?, region),
                last_deploy = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (email, password, lab_url, region, user_id))
    else:
        c.execute('''
            INSERT INTO users (user_id, email, password, lab_url, region, last_deploy)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, email or DEFAULT_EMAIL, password or DEFAULT_PASSWORD, lab_url, region))
    conn.commit()
    conn.close()
    logger.info(f"✅ تم تحديث بيانات المستخدم {user_id}")

def update_user_status(user_id, status, last_result=None):
    """تحديث حالة المستخدم ونتيجة آخر عملية نشر."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE users SET
            status = ?,
            last_result = ?,
            deploy_count = deploy_count + 1
        WHERE user_id = ?
    ''', (status, last_result, user_id))
    conn.commit()
    conn.close()

def add_history(user_id, lab_url, service_url, vless_link, success=1):
    """إضافة سجل لعملية نشر ناجحة أو فاشلة."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO history (user_id, lab_url, service_url, vless_link, deployed_at, success)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
    ''', (user_id, lab_url, service_url, vless_link, success))
    conn.commit()
    conn.close()

def get_user_history(user_id, limit=10):
    """استرجاع آخر 10 عمليات نشر للمستخدم."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT lab_url, service_url, vless_link, deployed_at, success
        FROM history
        WHERE user_id = ?
        ORDER BY deployed_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# تهيئة قاعدة البيانات عند بدء التشغيل
init_db()

# ============================================================
# 6. دوال التشفير والنشر (مع إعادة محاولة)
# ============================================================
def b64url(d):
    return base64.urlsafe_b64encode(d).decode().rstrip("=")

def generate_vless(service_url):
    """توليد رابط VLESS من رابط الخدمة."""
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"architect").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

def create_jwt(creds):
    """إنشاء JWT من بيانات الاعتماد."""
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
    return ".".join(segments)

def get_access_token(creds):
    """الحصول على Access Token من ملف credentials."""
    jwt = create_jwt(creds)
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
        timeout=30
    )
    if resp.status_code != 200:
        raise Exception(f"فشل الحصول على Token: {resp.status_code}")
    return resp.json().get("access_token")

def deploy_via_rest_api(project_id, token):
    """نشر الخدمة عبر REST API."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"vip-{int(time.time())}"
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
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/europe-west1/services"
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise Exception(f"فشل النشر: {r.status_code}")
    return r.json().get('status', {}).get('url')

def deploy_with_selenium(lab_url, email=None, password=None, retries=MAX_RETRIES):
    """
    يقوم بالأتمتة الكاملة باستخدام Selenium.
    يعيد (result_message, service_url, vless_link)
    """
    email = email or DEFAULT_EMAIL
    password = password or DEFAULT_PASSWORD

    driver = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"🔄 محاولة {attempt}/{retries} للمستخدم {email}")
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

            # 1. تسجيل الدخول إلى Google
            driver.get("https://accounts.google.com/")
            wait.until(EC.presence_of_element_located((By.ID, "identifierId"))).send_keys(email + Keys.RETURN)
            time.sleep(2)
            wait.until(EC.presence_of_element_located((By.NAME, "Passwd"))).send_keys(password + Keys.RETURN)
            time.sleep(5)

            # 2. استخراج project_id من الرابط
            match = re.search(r'project=([^&]+)', lab_url)
            if not match:
                raise Exception("الرابط لا يحتوي على project=")
            project_id = match.group(1)

            # 3. تفعيل Cloud Run API
            driver.get(f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}")
            time.sleep(3)
            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Enable')]"))).click()
                time.sleep(5)
            except: pass

            # 4. إنشاء حساب خدمة
            driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
            time.sleep(3)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create Service Account')]"))).click()
            time.sleep(2)
            wait.until(EC.presence_of_element_located((By.NAME, "serviceAccountName"))).send_keys("auto-bot")
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create')]"))).click()
            time.sleep(2)
            role_field = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@placeholder, 'Select a role')]")))
            role_field.send_keys("Cloud Run Admin" + Keys.RETURN)
            time.sleep(1)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Done')]"))).click()
            time.sleep(3)

            # 5. تنزيل المفتاح JSON
            driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
            time.sleep(2)
            account = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'auto-bot')]")))
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

            # 6. قراءة الملف من مجلد temp
            list_of_files = glob.glob(os.path.join(download_dir, "*.json"))
            if not list_of_files:
                raise Exception("لم نتمكن من العثور على ملف JSON.")
            latest_file = max(list_of_files, key=os.path.getctime)
            with open(latest_file, 'r') as f:
                creds = json.load(f)
            os.remove(latest_file)
            driver.quit()

            # 7. النشر عبر REST API
            token = get_access_token(creds)
            service_url = deploy_via_rest_api(project_id, token)
            vless_link = generate_vless(service_url)

            return (f"✅ **تم النشر بنجاح!**\n🌐 {service_url}\n🔗 VLESS:\n`{vless_link}`", service_url, vless_link)

        except Exception as e:
            logger.error(f"❌ فشل المحاولة {attempt}: {str(e)}")
            if driver:
                try: driver.quit()
                except: pass
            if attempt < retries:
                time.sleep(5 * attempt)  # تأخير تصاعدي
                continue
            else:
                raise Exception(f"فشلت جميع المحاولات: {str(e)}")

    raise Exception("فشل غير متوقع في عملية النشر.")

# ============================================================
# 7. نظام الطابور (Queue) المتقدم
# ============================================================
task_queue = queue.Queue()
processing = False
user_deploy_lock = threading.Lock()

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                user_id, lab_url = task_queue.get()
                logger.info(f"📌 معالجة طلب المستخدم {user_id}")
                user = get_user(user_id)
                if not user:
                    update_user_status(user_id, 'error', '❌ المستخدم غير موجود في قاعدة البيانات.')
                    processing = False
                    continue

                update_user_status(user_id, 'processing')
                try:
                    email = user.get('email') or DEFAULT_EMAIL
                    password = user.get('password') or DEFAULT_PASSWORD
                    result_msg, service_url, vless_link = deploy_with_selenium(lab_url, email, password)
                    update_user_status(user_id, 'completed', result_msg)
                    add_history(user_id, lab_url, service_url, vless_link, success=1)
                except Exception as e:
                    error_msg = f"❌ فشل النشر: {str(e)}"
                    update_user_status(user_id, 'error', error_msg)
                    add_history(user_id, lab_url, None, None, success=0)

            except Exception as e:
                logger.error(f"❌ خطأ في معالجة الطابور: {str(e)}")
            finally:
                processing = False
        time.sleep(2)

# تشغيل معالج الطابور في خلفية منفصلة
Thread(target=process_queue, daemon=True).start()

# ============================================================
# 8. واجهة البوت (قائمة رئيسية متقدمة)
# ============================================================
# أوامر البوت
async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        create_or_update_user(user_id, DEFAULT_EMAIL, DEFAULT_PASSWORD)

    logo = """
    █████╗ ██████╗  ██████╗██╗  ██╗██╗████████╗ ██████╗██╗   ██╗██╗  ██╗
   ██╔══██╗██╔══██╗██╔════╝██║  ██║██║╚══██╔══╝██╔════╝██║   ██║╚██╗██╔╝
   ███████║██████╔╝██║     ███████║██║   ██║   ██║     ██║   ██║ ╚███╔╝ 
   ██╔══██║██╔══██╗██║     ██╔══██║██║   ██║   ██║     ██║   ██║ ██╔██╗ 
   ██║  ██║██║  ██║╚██████╗██║  ██║██║   ██║   ╚██████╗╚██████╔╝██╔╝ ██╗
   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝  ╚═╝
    """
    keyboard = [
        [InlineKeyboardButton("🚀 تشغيل خدمة سريعة", callback_data='deploy')],
        [InlineKeyboardButton("📋 حالتك", callback_data='status')],
        [InlineKeyboardButton("📜 سجل النشر", callback_data='history')],
        [InlineKeyboardButton("⚙️ إعدادات الحساب", callback_data='settings')],
        [InlineKeyboardButton("❓ مساعدة", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"`{logo}`\n\n"
        "🔥 **THE ARCHITECT // v37.0**\n"
        f"👤 مرحباً بك {update.effective_user.first_name}!\n"
        "📡 أرسل رابط مختبر GCP (يحتوي على `project=`) لبدء النشر التلقائي.\n"
        "📌 استخدم الأزرار للتحكم في حسابك.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# ============================================================
# 9. معالج الأزرار والتفاعلات
# ============================================================
async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == 'deploy':
        await query.edit_message_text(
            "🔗 **أرسل رابط مختبر GCP** (يحتوي على `project=`).\n"
            "سيتم إضافة طلبك إلى طابور الانتظار."
        )
        context.user_data['state'] = 'awaiting_lab'
        return 0

    elif data == 'status':
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("❌ لا توجد بيانات لك.")
            return
        status_text = (
            f"📋 **حالتك**\n\n"
            f"📧 البريد: `{user.get('email')}`\n"
            f"🌍 المنطقة: `{user.get('region')}`\n"
            f"📊 عدد عمليات النشر: `{user.get('deploy_count', 0)}`\n"
            f"🔄 الحالة: `{user.get('status', 'idle')}`\n"
            f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}"
        )
        await query.edit_message_text(status_text, parse_mode='Markdown')

    elif data == 'history':
        history = get_user_history(user_id, limit=5)
        if not history:
            await query.edit_message_text("📜 لا يوجد سجل نشر.")
            return
        lines = ["📜 **آخر عمليات النشر:**"]
        for i, (lab_url, service_url, vless_link, deployed_at, success) in enumerate(history, 1):
            status_icon = "✅" if success else "❌"
            lines.append(f"{i}. {status_icon} `{lab_url[:50]}...`\n   {deployed_at}")
        await query.edit_message_text("\n".join(lines), parse_mode='Markdown')

    elif data == 'settings':
        keyboard = [
            [InlineKeyboardButton("🔑 تغيير البريد الإلكتروني", callback_data='change_email')],
            [InlineKeyboardButton("🔑 تغيير كلمة المرور", callback_data='change_password')],
            [InlineKeyboardButton("🌍 تغيير المنطقة", callback_data='change_region')],
            [InlineKeyboardButton("🔙 العودة", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚙️ **إعدادات الحساب**\nاختر ما تريد تعديله.", parse_mode='Markdown', reply_markup=reply_markup)

    elif data == 'change_email':
        await query.edit_message_text("📧 أرسل البريد الإلكتروني الجديد.")
        context.user_data['state'] = 'changing_email'
        return 1

    elif data == 'change_password':
        await query.edit_message_text("🔑 أرسل كلمة المرور الجديدة.")
        context.user_data['state'] = 'changing_password'
        return 2

    elif data == 'change_region':
        keyboard = [
            [InlineKeyboardButton("🇪🇺 أوروبا (europe-west1)", callback_data='region_europe-west1')],
            [InlineKeyboardButton("🇺🇸 أمريكا (us-central1)", callback_data='region_us-central1')],
            [InlineKeyboardButton("🇦🇺 آسيا (asia-southeast1)", callback_data='region_asia-southeast1')],
            [InlineKeyboardButton("🔙 العودة", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🌍 **اختر المنطقة:**", parse_mode='Markdown', reply_markup=reply_markup)

    elif data.startswith('region_'):
        region = data.replace('region_', '')
        create_or_update_user(user_id, region=region)
        await query.edit_message_text(f"✅ تم تغيير المنطقة إلى `{region}`.", parse_mode='Markdown')

    elif data == 'back':
        await start(update, context)

    elif data == 'help':
        await query.edit_message_text(
            "❓ **المساعدة**\n\n"
            "1️⃣ أرسل `/start` لبدء البوت.\n"
            "2️⃣ اضغط على '🚀 تشغيل خدمة سريعة'.\n"
            "3️⃣ أرسل رابط مختبر GCP (يحتوي على `project=`).\n"
            "4️⃣ انتظر 2-3 دقائق – ستحصل على رابط VLESS.\n\n"
            "📌 يمكنك أيضاً:\n"
            "- عرض حالتك (`/status`)\n"
            "- عرض سجل النشر (`/history`)\n"
            "- تغيير الإعدادات (`/settings`)"
        )

    return ConversationHandler.END

# ============================================================
# 10. استقبال البيانات (رابط المختبر، تغيير البريد، تغيير كلمة المرور)
# ============================================================
async def receive_lab(update: Update, context):
    user_id = update.effective_user.id
    lab_url = update.message.text
    if not lab_url.startswith('http') or 'project=' not in lab_url:
        await update.message.reply_text("❌ رابط غير صحيح. يجب أن يحتوي على `project=`.")
        return 0

    # إضافة المستخدم إلى الطابور
    task_queue.put((user_id, lab_url))
    create_or_update_user(user_id, lab_url=lab_url)
    await update.message.reply_text(
        "✅ **تمت إضافة طلبك إلى طابور الانتظار!**\n"
        "📌 الأولوية: عادية\n"
        "🔄 سيتم النشر تلقائياً فور توفر منفذ تشغيل شاغر.\n"
        "📨 سنرسل لك النتيجة فور اكتمال الخدمة."
    )

    # تشغيل دالة مراقبة لإرسال النتيجة عند الانتهاء
    def monitor_and_notify():
        while True:
            user = get_user(user_id)
            if user and user.get('status') in ('completed', 'error'):
                result = user.get('last_result', '⚠️ حدث خطأ غير متوقع.')
                import asyncio
                asyncio.run(update.message.reply_text(result, parse_mode='Markdown'))
                break
            time.sleep(5)
    Thread(target=monitor_and_notify, daemon=True).start()

    context.user_data.clear()
    return ConversationHandler.END

async def receive_new_email(update: Update, context):
    user_id = update.effective_user.id
    new_email = update.message.text
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
        await update.message.reply_text("❌ بريد إلكتروني غير صحيح.")
        return 1
    create_or_update_user(user_id, email=new_email)
    await update.message.reply_text(f"✅ تم تحديث البريد إلى `{new_email}`.", parse_mode='Markdown')
    await start(update, context)
    return ConversationHandler.END

async def receive_new_password(update: Update, context):
    user_id = update.effective_user.id
    new_password = update.message.text
    if len(new_password) < 6:
        await update.message.reply_text("❌ كلمة المرور قصيرة جداً (يجب أن تكون 6 أحرف على الأقل).")
        return 2
    create_or_update_user(user_id, password=new_password)
    await update.message.reply_text("✅ تم تحديث كلمة المرور.")
    await start(update, context)
    return ConversationHandler.END

# ============================================================
# 11. أوامر إضافية (Status, History, Help)
# ============================================================
async def status_command(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات لك. أرسل /start أولاً.")
        return
    status_text = (
        f"📋 **حالتك**\n\n"
        f"📧 البريد: `{user.get('email')}`\n"
        f"🌍 المنطقة: `{user.get('region')}`\n"
        f"📊 عدد عمليات النشر: `{user.get('deploy_count', 0)}`\n"
        f"🔄 الحالة: `{user.get('status', 'idle')}`\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}"
    )
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def history_command(update: Update, context):
    user_id = update.effective_user.id
    history = get_user_history(user_id, limit=10)
    if not history:
        await update.message.reply_text("📜 لا يوجد سجل نشر.")
        return
    lines = ["📜 **آخر عمليات النشر:**"]
    for i, (lab_url, service_url, vless_link, deployed_at, success) in enumerate(history, 1):
        status_icon = "✅" if success else "❌"
        lines.append(f"{i}. {status_icon} `{lab_url[:60]}...`\n   {deployed_at}")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

async def help_command(update: Update, context):
    await update.message.reply_text(
        "❓ **المساعدة**\n\n"
        "1️⃣ أرسل `/start` لبدء البوت.\n"
        "2️⃣ اضغط على '🚀 تشغيل خدمة سريعة'.\n"
        "3️⃣ أرسل رابط مختبر GCP (يحتوي على `project=`).\n"
        "4️⃣ انتظر 2-3 دقائق – ستحصل على رابط VLESS.\n\n"
        "📌 يمكنك أيضاً:\n"
        "- عرض حالتك (`/status`)\n"
        "- عرض سجل النشر (`/history`)\n"
        "- تغيير الإعدادات (`/settings`)"
    )

# ============================================================
# 12. تشغيل البوت
# ============================================================
def main():
    # تشغيل Flask
    keep_alive()

    # تهيئة البوت
    app = ApplicationBuilder().token(TOKEN).build()

    # أوامر البوت
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("help", help_command))

    # محادثة متقدمة للتفاعلات
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern='^(deploy|status|history|settings|change_email|change_password|change_region|back|help|region_.*)$')
        ],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_email)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_password)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)

    # معالج عام للأزرار
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("✅ البوت جاهز. استخدم /start.")
    app.run_polling()

if __name__ == "__main__":
    main()
