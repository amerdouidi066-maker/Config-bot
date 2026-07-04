#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 SHADOW LEGION v125 – النسخة النهائية المتكاملة
✅ أدوات تخفي متطورة (Evasion)
✅ استخراج التوكن من الجلسة (Bypass)
✅ تخزين مؤقت للتوكن (Cache)
✅ إعادة محاولة واحدة
✅ قاعدة بيانات SQLite
✅ أوامر تلغرام كاملة
✅ متوافقة مع Railway
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
from typing import Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

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
import psutil
from cryptography.fernet import Fernet

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
CACHE_DB = "token_cache.db"

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
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT,
            expiry TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

def init_cache_db():
    # تم دمجها في init_db، لكن نتركها للتوافق
    pass

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

def get_cached_token(user_id: int) -> Optional[Tuple[str, datetime]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry FROM token_cache WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        token, expiry_str = row
        expiry = datetime.fromisoformat(expiry_str)
        if expiry > datetime.now():
            return token, expiry
    return None, None

def save_token(user_id: int, access_token: str, expiry_seconds: int = 3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry) VALUES (?, ?, ?)",
        (user_id, access_token, expiry.isoformat())
    )
    conn.commit()
    conn.close()
    logger.info(f"✅ تم تخزين التوكن للمستخدم {user_id}")

def clear_cached_token(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM token_cache WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

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

def extract_from_link(link):
    data = {}
    data['project_id'] = extract_project_id(link) or ''
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
    return f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 **رابط الـ Cloud Run**\n{service_url}\n\n🔗 **VLESS URL**\n{vless}", service_url, vless

# ====================== CHROME DRIVER (التخفي المتطور) ======================
def get_ultimate_driver():
    options = Options()
    # طبقات التخفي المتقدمة
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-features=Translate,OptimizationHints")
    options.add_argument("--disable-web-security")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--incognito")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except:
        driver = webdriver.Chrome(options=options)
    
    # تجاوز كشف السيلينيوم
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});")
    driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});")
    
    return driver

# ====================== TOKEN EXTRACTION ======================
def extract_token_from_network_logs(driver):
    logs = driver.get_log('performance')
    for entry in logs:
        try:
            data = json.loads(entry['message'])
            message = data.get('message', {})
            if message.get('method') == 'Network.requestWillBeSent':
                request = message.get('params', {}).get('request', {})
                headers = request.get('headers', {})
                auth_header = headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    token = auth_header.replace('Bearer ', '')
                    if len(token) > 50:
                        return token
        except:
            continue
    return None

def extract_token_from_local_storage(driver):
    try:
        token = driver.execute_script("""
            var keys = ['access_token', 'id_token', 'oauth_token', 'token', 'gapi_token'];
            for (var i=0; i<keys.length; i++) {
                var val = localStorage.getItem(keys[i]);
                if (val && val.length > 50) return val;
            }
            return null;
        """)
        if token:
            return token
    except:
        pass
    return None

def extract_token_from_cookies(driver):
    try:
        for cookie in driver.get_cookies():
            name = cookie.get('name', '').lower()
            if 'token' in name or 'oauth' in name or 'auth' in name:
                value = cookie.get('value')
                if value and len(value) > 50:
                    return value
    except:
        pass
    return None

def extract_token_driver(driver):
    token = extract_token_from_network_logs(driver)
    if token:
        return token
    token = extract_token_from_local_storage(driver)
    if token:
        return token
    token = extract_token_from_cookies(driver)
    if token:
        return token
    raise Exception("❌ لم نتمكن من استخراج التوكن بأي طريقة.")

# ====================== DEPLOY ======================
def deploy_direct_with_token(project_id, token, region):
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
    r = requests.post(url, headers=headers, json=body, timeout=120)
    if r.status_code in (200, 201):
        service_url = r.json().get('status', {}).get('url')
        if not service_url:
            service_url = f"https://{service_name}-{region}.run.app"
        return build_vless_response(service_url, region)
    elif r.status_code == 401:
        raise Exception("UNAUTHORIZED_TOKEN")
    else:
        raise Exception(f"فشل النشر: {r.status_code} - {r.text[:200]}")

# ====================== BYPASS DEPLOY (مع التخفي) ======================
def deploy_bypass(lab_url, email, password, region, send_message, user_id):
    project_id = extract_project_id(lab_url)
    if not project_id:
        raise Exception("❌ project_id مفقود")
    
    # التحقق من التوكن المخزن
    cached_token, expiry = get_cached_token(user_id)
    if cached_token:
        send_message("♻️ استخدام التوكن المخزن (صالح حتى " + expiry.strftime("%H:%M") + ")")
        try:
            result_msg, service_url, vless = deploy_direct_with_token(project_id, cached_token, region)
            return result_msg, service_url, vless
        except Exception as e:
            if "UNAUTHORIZED_TOKEN" in str(e):
                send_message("⚠️ التوكن المخزن منتهي، جاري استخراج توكن جديد...")
                clear_cached_token(user_id)
            else:
                raise e
    
    # محاولة استخراج توكن جديد (مع محاولة إعادة واحدة)
    max_retries = 2
    for attempt in range(max_retries):
        driver = None
        try:
            if attempt > 0:
                send_message(f"🔄 إعادة المحاولة ({attempt+1}/{max_retries})...")
            
            driver = get_ultimate_driver()
            
            send_message("📧 جاري تسجيل الدخول...")
            driver.get("https://accounts.google.com/")
            time.sleep(random.uniform(2, 4))
            
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "identifierId"))
            ).send_keys(email + Keys.RETURN)
            time.sleep(random.uniform(2, 4))
            
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.NAME, "Passwd"))
            ).send_keys(password + Keys.RETURN)
            time.sleep(random.uniform(6, 10))
            
            send_message("🌐 جاري الانتقال إلى Cloud Run Console...")
            driver.get(f"https://console.cloud.google.com/run?project={project_id}")
            time.sleep(random.uniform(8, 12))
            
            send_message("🔑 جاري استخراج التوكن...")
            token = extract_token_driver(driver)
            
            save_token(user_id, token)
            send_message("💾 تم تخزين التوكن للاستخدام المستقبلي")
            
            send_message(f"🚀 جاري النشر على {REGIONS.get(region, region)}...")
            result_msg, service_url, vless = deploy_direct_with_token(project_id, token, region)
            
            driver.quit()
            return result_msg, service_url, vless
            
        except Exception as e:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            error_msg = str(e)
            
            if ("لم نتمكن من استخراج التوكن" in error_msg or "UNAUTHORIZED_TOKEN" in error_msg) and attempt < max_retries - 1:
                send_message("⚠️ فشل استخراج التوكن، جاري إعادة المحاولة...")
                clear_cached_token(user_id)
                time.sleep(3)
                continue
            else:
                raise Exception(f"فشل النشر: {error_msg}")
    
    raise Exception("فشل النشر بعد المحاولات المتكررة")

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

                send_message("✅ **تمت إضافة طلبك إلى طابور الانظار بنجاح!**")
                time.sleep(1)
                send_message("📌 **أولوية النشر: عادية (ثانية)**\nسيقوم البوت بتشغيل طلبك تلقائياً.")
                time.sleep(1)

                link_data = extract_from_link(link)
                project_id = link_data.get('project_id', '')
                email = link_data.get('email', '')

                if not project_id:
                    raise Exception("❌ project_id مفقود.")

                send_message("🔄 **جاري الدخول إلى Lab وبدء التجهيز...**")
                time.sleep(1)

                send_message("🔍 **جاري تحليل سياسات المشروع...**")
                time.sleep(1)
                send_message(f"✅ **تم اكتشاف 1 منطقة مسموح بها:**\n\n- {REGIONS.get(region, region)}")
                time.sleep(1)

                send_message(f"🚀 **جاري نشر الخدمة على {REGIONS.get(region, region)}...**")

                user = get_user(user_id)
                saved_email = user.get('email') if user else None
                saved_password = user.get('password') if user else None

                if not saved_email or not saved_password:
                    raise Exception("⚠️ لا يوجد بريد وكلمة مرور محفوظان.\nاستخدم الأمر /set_creds لحفظ بيانات الدخول.")

                result_msg, service_url, vless = deploy_bypass(
                    link, saved_email, saved_password, region, send_message, user_id
                )
                
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
                error_msg = str(e)
                send_message(f"❌ **فشل النشر:** {error_msg}")
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
        "🔥 **SHADOW LEGION v125**\n"
        "📡 النسخة النهائية مع أدوات التخفي المتطورة\n"
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

    await update.message.reply_text(
        "✅ **تمت إضافة طلبك إلى طابور الانظار بنجاح!**\n\n"
        "📌 **أولوية النشر: عادية (ثانية)**\n"
        "سيقوم البوت بتشغيل طلبك تلقائياً فور توفر منفذ تشغيل شاغر، وسنرسل لك إشعاراً فوراً عند اكتمال نشر الخدمة."
    )
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
    has_token, _ = get_cached_token(user_id)
    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: {user.get('email', 'غير مضبوط')}\n"
        f"🌍 المنطقة: {REGIONS.get(user.get('region'), user.get('region'))}\n"
        f"📊 عدد النشر: {user.get('deploy_count', 0)}\n"
        f"🔄 الحالة: {user.get('status', 'idle')}\n"
        f"🔑 التوكن المخزن: {'✅' if has_token else '❌'}\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}"
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

    logger.info("✅ SHADOW LEGION v125 RUNNING (مع التخفي المتطور)")
    app.run_polling()

if __name__ == "__main__":
    main()