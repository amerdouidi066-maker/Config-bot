#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 THE ARCHITECT // ULTIMATE BOT v41.0 (PRODUCTION READY)
🚀 بوت متطور يعمل على Railway – يتعامل مع صلاحية الروابط ويعيد المحاولة تلقائياً.
"""

import os, sys, time, re, json, base64, hashlib, tempfile, glob, threading, queue, subprocess, logging, sqlite3, urllib.parse
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ============================================================
# 1. إعدادات التسجيل
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. الإعدادات الأساسية
# ============================================================
TOKEN = os.environ.get("TOKEN", "توكن_التاعك_هنا")
DEFAULT_EMAIL = os.environ.get("EMAIL", "")
DEFAULT_PASSWORD = os.environ.get("PASSWORD", "")
MAX_RETRIES = 3
SESSION_TIMEOUT = 600  # 10 دقائق

# ============================================================
# 3. خادم Flask (Keep-Alive)
# ============================================================
flask_app = Flask('')
@flask_app.route('/')
def home(): return "✅ THE ARCHITECT // BOT IS ALIVE"
@flask_app.route('/health')
def health(): return "OK", 200

def keep_alive():
    Thread(target=lambda: flask_app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)).start()
    logger.info("✅ Flask keep-alive started.")

# ============================================================
# 4. تثبيت المكتبات تلقائياً
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
# 5. قاعدة البيانات
# ============================================================
DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
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
            success INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة.")

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

def create_or_update_user(user_id, **kwargs):
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
        ''', (kwargs.get('email'), kwargs.get('password'), kwargs.get('lab_url'), kwargs.get('region'), user_id))
    else:
        c.execute('''
            INSERT INTO users (user_id, email, password, lab_url, region, last_deploy)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, kwargs.get('email') or DEFAULT_EMAIL, kwargs.get('password') or DEFAULT_PASSWORD,
              kwargs.get('lab_url'), kwargs.get('region') or "europe-west1"))
    conn.commit()
    conn.close()

def update_user_status(user_id, status, last_result=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE users SET status = ?, last_result = ?, deploy_count = deploy_count + 1
        WHERE user_id = ?
    ''', (status, last_result, user_id))
    conn.commit()
    conn.close()

def add_history(user_id, lab_url, service_url, vless_link, success=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO history (user_id, lab_url, service_url, vless_link, deployed_at, success)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
    ''', (user_id, lab_url, service_url, vless_link, success))
    conn.commit()
    conn.close()

init_db()

# ============================================================
# 6. دوال التشفير والنشر
# ============================================================
def b64url(d): return base64.urlsafe_b64encode(d).decode().rstrip("=")

def generate_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"architect").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

def create_jwt(creds):
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
    jwt = create_jwt(creds)
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
        timeout=30
    )
    if resp.status_code != 200:
        raise Exception(f"فشل Token: {resp.status_code}")
    return resp.json().get("access_token")

def deploy_via_rest_api(project_id, token):
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
    if r.status_code in (200, 201):
        return r.json().get('status', {}).get('url')
    elif r.status_code == 403:
        raise Exception("❌ رابط منتهي الصلاحية أو صلاحية غير كافية. يرجى إرسال رابط جديد.")
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

def deploy_with_sso(link_data):
    """النشر مع اكتشاف انتهاء صلاحية الرابط وإعادة المحاولة."""
    project_id = link_data.get('project_id')
    email = link_data.get('email')
    token = link_data.get('token')
    if not project_id:
        raise Exception("الرابط لا يحتوي على project_id")

    # 1. محاولة النشر باستخدام token مباشرة
    if token:
        try:
            service_url = deploy_via_rest_api(project_id, token)
            vless = generate_vless(service_url)
            return (f"✅ **تم النشر!**\n🌐 {service_url}\n🔗 VLESS:\n`{vless}`", service_url, vless)
        except Exception as e:
            if "منتهي الصلاحية" in str(e):
                raise Exception("❌ الرابط منتهي الصلاحية. يرجى إرسال رابط جديد.")
            logger.warning(f"فشل النشر باستخدام token: {e}")

    # 2. استخدام Selenium مع البريد وكلمة المرور
    email = email or DEFAULT_EMAIL
    password = DEFAULT_PASSWORD
    if not email or not password:
        raise Exception("لا يوجد بريد إلكتروني أو كلمة مرور صالحة.")

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

        # تسجيل الدخول
        driver.get("https://accounts.google.com/")
        wait.until(EC.presence_of_element_located((By.ID, "identifierId"))).send_keys(email + Keys.RETURN)
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.NAME, "Passwd"))).send_keys(password + Keys.RETURN)
        time.sleep(5)

        # تفعيل Cloud Run API
        driver.get(f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}")
        time.sleep(3)
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Enable')]"))).click()
            time.sleep(5)
        except: pass

        # إنشاء حساب خدمة
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

        # تنزيل المفتاح
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

        list_of_files = glob.glob(os.path.join(download_dir, "*.json"))
        if not list_of_files:
            raise Exception("لم نتمكن من العثور على ملف JSON.")
        latest_file = max(list_of_files, key=os.path.getctime)
        with open(latest_file, 'r') as f:
            creds = json.load(f)
        os.remove(latest_file)
        driver.quit()

        # النشر عبر REST API
        access_token = get_access_token(creds)
        service_url = deploy_via_rest_api(project_id, access_token)
        vless = generate_vless(service_url)
        return (f"✅ **تم النشر!**\n🌐 {service_url}\n🔗 VLESS:\n`{vless}`", service_url, vless)

    except Exception as e:
        if driver:
            try: driver.quit()
            except: pass
        raise e

# ============================================================
# 7. نظام الطابور المتقدم
# ============================================================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                user_id, link = task_queue.get()
                logger.info(f"📌 معالجة طلب المستخدم {user_id}")
                link_data = extract_from_link(link)
                result_msg, service_url, vless_link = deploy_with_sso(link_data)
                update_user_status(user_id, 'completed', result_msg)
                add_history(user_id, link, service_url, vless_link, success=1)
                logger.info(f"✅ تم النشر للمستخدم {user_id}")
            except Exception as e:
                error_msg = str(e)
                if "منتهي الصلاحية" in error_msg:
                    error_msg = "❌ الرابط منتهي الصلاحية. يرجى إرسال رابط جديد عبر الزر."
                logger.error(error_msg)
                update_user_status(user_id, 'error', error_msg)
                add_history(user_id, link, None, None, success=0)
            finally:
                processing = False
        time.sleep(2)

Thread(target=process_queue, daemon=True).start()

# ============================================================
# 8. واجهة البوت
# ============================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    create_or_update_user(user_id)
    logo = """
    █████╗ ██████╗  ██████╗██╗  ██╗██╗████████╗ ██████╗██╗   ██╗██╗  ██╗
   ██╔══██╗██╔══██╗██╔════╝██║  ██║██║╚══██╔══╝██╔════╝██║   ██║╚██╗██╔╝
   ███████║██████╔╝██║     ███████║██║   ██║   ██║     ██║   ██║ ╚███╔╝ 
   ██╔══██║██╔══██╗██║     ██╔══██║██║   ██║   ██║     ██║   ██║ ██╔██╗ 
   ██║  ██║██║  ██║╚██████╗██║  ██║██║   ██║   ╚██████╗╚██████╔╝██╔╝ ██╗
   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝  ╚═╝
    """
    keyboard = [[InlineKeyboardButton("🚀 تشغيل خدمة سريعة", callback_data='deploy')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"`{logo}`\n\n"
        "🔥 **THE ARCHITECT // v41.0**\n"
        "📡 **أرسل رابط مختبر Google Skills** (SSO).\n"
        "سأنشر الخدمة تلقائياً.\n\n"
        "💡 إذا ظهرت رسالة 'رابط منتهي'، فقط أرسل رابطاً جديداً.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def deploy_button(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔗 أرسل رابط مختبر Google Skills (SSO) الآن.")
    context.user_data['state'] = 'awaiting_lab'
    return 0

async def receive_lab(update: Update, context):
    user_id = update.effective_user.id
    link = update.message.text
    if not link.startswith('http'):
        await update.message.reply_text("❌ الرابط غير صحيح. يجب أن يبدأ بـ http.")
        return 0
    task_queue.put((user_id, link))
    create_or_update_user(user_id, lab_url=link)
    await update.message.reply_text(
        "✅ **تمت إضافة طلبك إلى طابور الانتظار!**\n"
        "🔄 سيتم النشر تلقائياً.\n"
        "📨 سنرسل لك النتيجة فور اكتمال الخدمة."
    )
    # مراقبة النتيجة
    def monitor():
        while True:
            user = get_user(user_id)
            if user and user.get('status') in ('completed', 'error'):
                result = user.get('last_result', '⚠️ حدث خطأ غير متوقع.')
                import asyncio
                asyncio.run(update.message.reply_text(result, parse_mode='Markdown'))
                break
            time.sleep(5)
    Thread(target=monitor, daemon=True).start()
    context.user_data.clear()
    return ConversationHandler.END

# ============================================================
# 9. أوامر إضافية
# ============================================================
async def status_command(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات لك.")
        return
    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: `{user.get('email')}`\n"
        f"🌍 المنطقة: `{user.get('region')}`\n"
        f"📊 عدد عمليات النشر: `{user.get('deploy_count', 0)}`\n"
        f"🔄 الحالة: `{user.get('status', 'idle')}`\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}",
        parse_mode='Markdown'
    )

async def history_command(update: Update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT lab_url, service_url, vless_link, deployed_at, success
        FROM history WHERE user_id = ? ORDER BY deployed_at DESC LIMIT 5
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📜 لا يوجد سجل نشر.")
        return
    lines = ["📜 **آخر عمليات النشر:**"]
    for i, (lab_url, service_url, vless_link, deployed_at, success) in enumerate(rows, 1):
        status_icon = "✅" if success else "❌"
        lines.append(f"{i}. {status_icon} `{lab_url[:60]}...`\n   {deployed_at}")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

# ============================================================
# 10. تشغيل البوت
# ============================================================
def main():
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("history", history_command))
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='deploy')],
        states={0: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)]},
        fallbacks=[]
    )
    app.add_handler(conv)
    logger.info("✅ البوت جاهز. استخدم /start.")
    app.run_polling()

if __name__ == "__main__":
    main()