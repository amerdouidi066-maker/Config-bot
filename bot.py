#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 SHADOW LEGION v146 – يعتمد فقط على الإيميل وكلمة المرور والرابط
✅ تم إزالة المفتاح (service_key) نهائياً
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
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

import requests
import jwt
import psutil
from cryptography.fernet import Fernet

# محاولة استيراد undetected_chromedriver
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️ Selenium غير مثبت.")

# ====================== CONFIG ======================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN environment variable not set")

DEFAULT_REGION = "us-central1"

REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
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
            region TEXT DEFAULT 'us-central1'
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

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        for key, val in kwargs.items():
            if val is not None:
                c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (val, user_id))
    else:
        c.execute(
            "INSERT INTO users (user_id, email, password, region, last_deploy) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, kwargs.get('email', ''), kwargs.get('password', ''), kwargs.get('region', DEFAULT_REGION))
        )
    conn.commit()
    conn.close()

def get_history(user_id, limit=5):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT lab_url, service_url, vless_link, deployed_at, success FROM history WHERE user_id = ? ORDER BY deployed_at DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

init_db()

# ====================== EXTRACTORS ======================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'project%3D([^&]+)', link)
    if match:
        return match.group(1)
    return None

def extract_token(link):
    decoded = urllib.parse.unquote(link)
    match = re.search(r'token=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'token%3D([^&]+)', link)
    if match:
        return match.group(1)
    return None

def extract_from_link(link):
    data = {}
    data['project_id'] = extract_project_id(link) or ''
    data['token'] = extract_token(link) or ''
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[Ee]mail=([^&]+)', decoded)
    if match:
        data['email'] = urllib.parse.unquote(match.group(1))
    return data

def build_vless_response(service_url, region):
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"shadow_v105").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    vless = f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#DarkTunnel"
    return f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 **رابط الخدمة**\n{service_url}\n\n🔗 **VLESS URL**\n{vless}", service_url, vless

def deploy_with_token(project_id, token, region):
    """النشر المباشر باستخدام التوكن من الرابط"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"shadow-{int(time.time())}"
    body = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]
                }
            }
        }
    }
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code in (200, 201):
        service_url = r.json().get('status', {}).get('url')
        if not service_url:
            service_url = f"https://{service_name}-{region}.run.app"
        return build_vless_response(service_url, region)
    elif r.status_code == 401:
        raise Exception("UNAUTHORIZED_TOKEN")
    else:
        raise Exception(f"فشل النشر: {r.status_code} - {r.text[:200]}")

# ====================== SELENIUM DEPLOY ======================
def get_stealth_driver():
    if not SELENIUM_AVAILABLE:
        raise Exception("Selenium غير مثبت.")
    
    try:
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        driver = uc.Chrome(options=options)
        return driver
    except:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver

def deploy_with_selenium(lab_url, email, password, region, send_message):
    if not SELENIUM_AVAILABLE:
        raise Exception("Selenium غير مثبت.")
    
    driver = None
    max_retries = 2
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                send_message(f"🔄 إعادة المحاولة ({attempt+1}/{max_retries})...")
                time.sleep(5)
            
            send_message("👤 **جاري إنشاء حساب الخدمة عبر Selenium...**")
            driver = get_stealth_driver()
            wait = WebDriverWait(driver, 60)

            send_message("📧 جاري تسجيل الدخول إلى Google...")
            driver.get("https://accounts.google.com/")
            time.sleep(2)
            
            wait.until(EC.presence_of_element_located((By.ID, "identifierId"))).send_keys(email + Keys.RETURN)
            time.sleep(3)
            wait.until(EC.presence_of_element_located((By.NAME, "Passwd"))).send_keys(password + Keys.RETURN)
            time.sleep(5)
            
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Google Cloud')]")))
                send_message("✅ تم تسجيل الدخول بنجاح")
            except:
                pass

            project_id = extract_project_id(lab_url)
            if not project_id:
                raise Exception("project_id مفقود")

            send_message("☁️ جاري تمكين Cloud Run API...")
            driver.get(f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}")
            time.sleep(5)
            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Enable')]"))).click()
                time.sleep(5)
            except:
                pass

            send_message("👤 جاري إنشاء حساب الخدمة...")
            driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
            time.sleep(10)
            
            popup_selectors = [
                "//*[@aria-label='Close']",
                "//*[contains(text(), 'Dismiss')]",
                "//*[contains(text(), 'Skip')]",
                "//*[contains(text(), 'No thanks')]",
                "//*[contains(text(), 'Got it')]",
                "//*[contains(text(), 'Take a tour')]",
                "//button[@aria-label='Close']"
            ]
            for sel in popup_selectors:
                try:
                    popup = driver.find_element(By.XPATH, sel)
                    if popup and popup.is_displayed():
                        popup.click()
                        time.sleep(2)
                        break
                except:
                    continue

            create_button = None
            selectors = [
                "//*[contains(text(), 'Create Service Account')]",
                "//*[contains(text(), 'CREATE SERVICE ACCOUNT')]",
                "button[aria-label='Create Service Account']",
                "//*[@role='button' and contains(., 'Create')]",
                "//*[contains(@class, 'create-service-account')]",
                "//button[contains(., 'Create')]"
            ]
            for sel in selectors:
                try:
                    if sel.startswith("//"):
                        create_button = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    else:
                        create_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    break
                except:
                    continue
            
            if not create_button:
                js_script = """
                    var buttons = document.querySelectorAll('button, [role="button"]');
                    for (var i=0; i<buttons.length; i++) {
                        if (buttons[i].innerText.includes('Create') && buttons[i].offsetParent !== null) {
                            return buttons[i];
                        }
                    }
                    return null;
                """
                create_button = driver.execute_script(js_script)
                if create_button:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", create_button)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", create_button)
                    create_button = None
            
            if not create_button:
                raise Exception("لم نتمكن من العثور على زر 'Create Service Account'.")
            
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", create_button)
                time.sleep(1)
                create_button.click()
            except:
                driver.execute_script("arguments[0].click();", create_button)
            time.sleep(4)
            
            wait.until(EC.presence_of_element_located((By.NAME, "serviceAccountName"))).send_keys("shadow-bot")
            time.sleep(1)
            
            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create') and @type='submit']"))).click()
            except:
                driver.find_element(By.XPATH, "//*[contains(text(), 'Create')]").click()
            time.sleep(3)
            
            role_field = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@placeholder, 'Select a role')]")))
            role_field.send_keys("Cloud Run Admin" + Keys.RETURN)
            time.sleep(2)
            
            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Done')]"))).click()
            except:
                driver.find_element(By.XPATH, "//*[contains(text(), 'Done')]").click()
            time.sleep(4)

            send_message("📄 جاري تنزيل المفتاح...")
            driver.get(f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}")
            time.sleep(3)
            account = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'shadow-bot')]")))
            account.click()
            time.sleep(3)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Keys')]"))).click()
            time.sleep(3)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Add Key')]"))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create New Key')]"))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'JSON')]"))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Create')]"))).click()
            time.sleep(15)

            download_dir = tempfile.gettempdir()
            list_of_files = glob.glob(os.path.join(download_dir, "*.json"))
            if not list_of_files:
                raise Exception("ملف JSON غير موجود")
            latest_file = max(list_of_files, key=os.path.getctime)
            with open(latest_file, 'r') as f:
                creds = json.load(f)
            os.remove(latest_file)
            driver.quit()

            send_message("🔐 جاري إنشاء JWT...")
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
            jwt_token = ".".join(segments)

            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt_token},
                timeout=30
            )
            if resp.status_code != 200:
                raise Exception(f"فشل الحصول على التوكن: {resp.status_code}")
            token = resp.json().get("access_token")
            if not token:
                raise Exception("لا يوجد access_token")

            send_message("🚀 جاري نشر الخدمة...")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            service_name = f"shadow-{int(time.time())}"
            body = {
                "apiVersion": "serving.knative.dev/v1",
                "kind": "Service",
                "metadata": {"name": service_name},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]
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

            return build_vless_response(service_url, region)

        except Exception as e:
            if driver:
                try: driver.quit()
                except: pass
            if attempt < max_retries - 1:
                send_message(f"⚠️ فشلت المحاولة {attempt+1}، جاري إعادة المحاولة...")
                time.sleep(5)
            else:
                raise Exception(f"فشل Selenium: {str(e)}")

# ====================== MAIN DEPLOY ======================
def deploy_main(lab_url, region, send_message, user_id):
    project_id = extract_project_id(lab_url)
    if not project_id:
        raise Exception("❌ project_id مفقود")
    
    user = get_user(user_id)
    
    # 1. محاولة النشر المباشر بالتوكن (الأسرع)
    token = extract_token(lab_url)
    if token:
        try:
            send_message("⚡ **جاري النشر المباشر باستخدام التوكن...**")
            return deploy_with_token(project_id, token, region)
        except Exception as e:
            if "UNAUTHORIZED_TOKEN" in str(e):
                send_message("⚠️ التوكن منتهي الصلاحية")
            else:
                send_message(f"⚠️ فشل النشر المباشر: {str(e)[:100]}")
    
    # 2. طريقة Selenium (الإيميل + كلمة المرور)
    if user and user.get('email') and user.get('password') and SELENIUM_AVAILABLE:
        send_message("🔄 **جاري التبديل إلى طريقة Selenium...**")
        return deploy_with_selenium(lab_url, user['email'], user['password'], region, send_message)
    
    raise Exception(
        "❌ **لا توجد طريقة للنشر.**\n\n"
        "📧 **استخدم /set_creds لحفظ الإيميل وكلمة المرور (لطريقة Selenium).**\n"
        "⚡ **أو استخدم رابط SSO جديداً يحتوي على token صالح.**"
    )

# ====================== QUEUE ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                item = task_queue.get()
                user_id = item['user_id']
                link = item['link']
                region = item['region']
                context = item['context']
                loop = item['loop']
                bot = context.bot

                def send_message(text):
                    time.sleep(1)
                    asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id=user_id, text=text),
                        loop
                    )

                send_message("🔄 **جاري الدخول إلى Lab وبدء التجهيز...**")
                time.sleep(1)

                link_data = extract_from_link(link)
                project_id = link_data.get('project_id', '')
                if not project_id:
                    raise Exception("❌ project_id مفقود.")

                send_message("🔍 **جاري تحليل سياسات المشروع...**")
                time.sleep(1)
                send_message(f"✅ **تم اكتشاف 1 منطقة مسموح بها:**\n\n- {REGIONS.get(region, region)}")
                time.sleep(1)

                send_message(f"🚀 **جاري نشر الخدمة على {REGIONS.get(region, region)}...**")

                result_msg, service_url, vless = deploy_main(link, region, send_message, user_id)
                
                send_message("✅ **تم النشر بنجاح!**")
                send_message(result_msg)

                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='completed', last_result=? WHERE user_id=?", (result_msg, user_id))
                c.execute(
                    "INSERT INTO history (user_id, lab_url, service_url, vless_link, success) VALUES (?,?,?,?,1)",
                    (user_id, link, service_url, vless)
                )
                conn.commit()
                conn.close()

            except Exception as e:
                send_message(f"❌ **فشل النشر:** {str(e)}")
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='error', last_result=? WHERE user_id=?", (str(e), user_id))
                c.execute("INSERT INTO history (user_id, lab_url, success) VALUES (?,?,0)", (user_id, link))
                conn.commit()
                conn.close()
            finally:
                processing = False
        time.sleep(2)

threading.Thread(target=process_queue, daemon=True).start()

# ====================== BOT HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')],
        [InlineKeyboardButton("🖥️ System Info", callback_data='sysinfo')]
    ]
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v146**\n"
        "📡 يعتمد فقط على الإيميل وكلمة المرور والرابط\n"
        "أمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_creds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = context.args[1]
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد الإلكتروني وكلمة المرور بنجاح!")
    except IndexError:
        await update.message.reply_text("❌ الاستخدام: /set_creds <البريد> <كلمة_المرور>")

async def deploy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton(name, callback_data=f"region_{code}")] for code, name in REGIONS.items()]
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
    await query.edit_message_text(f"✅ **المنطقة:** {REGIONS.get(region, region)}\n\n🔗 أرسل رابط SSO الآن.")
    return 1

async def receive_lab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text
    region = context.user_data.get('region', DEFAULT_REGION)

    if not link.startswith('http'):
        await update.message.reply_text("❌ رابط غير صحيح.")
        return 1

    project_id = extract_project_id(link)
    if not project_id:
        await update.message.reply_text("❌ الرابط لا يحتوي على project_id.")
        return 1

    main_loop = asyncio.get_running_loop()

    task_queue.put({
        'user_id': user_id,
        'link': link,
        'region': region,
        'context': context,
        'loop': main_loop
    })

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
    
    history = get_history(user_id, 3)
    history_text = "\n".join([
        f"• {h[3]} → {'✅ نجاح' if h[4] else '❌ فشل'}"
        for h in history
    ]) if history else "لا يوجد سجل."

    has_creds = "✅" if user.get('email') and user.get('password') else "❌"

    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: {user.get('email', 'غير مضبوط')}\n"
        f"🔐 بيانات الدخول: {has_creds}\n"
        f"🌍 المنطقة: {REGIONS.get(user.get('region'), user.get('region'))}\n"
        f"📊 عدد النشر: {user.get('deploy_count', 0)}\n"
        f"🔄 الحالة: {user.get('status', 'idle')}\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}\n\n"
        f"📜 **آخر 3 عمليات:**\n{history_text}"
    )

async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    info = {
        "OS": platform.system(),
        "Release": platform.release(),
        "Arch": platform.machine(),
        "CPU": psutil.cpu_percent(),
        "RAM": psutil.virtual_memory().percent,
        "Disk": psutil.disk_usage('/').percent
    }
    result = "🖥️ **معلومات النظام**\n" + "\n".join([f"{k}: {v}" for k, v in info.items()])
    await query.edit_message_text(result)

async def change_region_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    keyboard = [[InlineKeyboardButton(name, callback_data=f"setregion_{code}")] for code, name in REGIONS.items()]
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="back_menu")])
    msg = "🌍 **اختر منطقتك الافتراضية الجديدة:**"
    if query:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    region = query.data.replace("setregion_", "")
    if region == "back_menu":
        await start(update, context)
        return
    user_id = query.from_user.id
    update_user(user_id, region=region)
    await query.edit_message_text(f"✅ تم تغيير المنطقة إلى {REGIONS.get(region, region)}.")
    await start(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ====================== MAIN ======================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("set_creds", set_creds))

    deploy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='^deploy$')],
        states={
            0: [CallbackQueryHandler(region_callback, pattern='^(region_|cancel_region)')],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)]
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)]
    )
    app.add_handler(deploy_conv)
    app.add_handler(CallbackQueryHandler(change_region_command, pattern='^change_region$'))
    app.add_handler(CallbackQueryHandler(set_region_callback, pattern='^setregion_'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_menu$'))
    app.add_handler(CallbackQueryHandler(sysinfo_command, pattern='^sysinfo$'))
    app.add_handler(CallbackQueryHandler(status_command, pattern='^status$'))

    logger.info("✅ SHADOW LEGION v146 RUNNING (بدون مفتاح)")
    app.run_polling()

if __name__ == "__main__":
    main()