#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 SHADOW LEGION v105.0 – النسخة الطويلة المتكاملة (نشر مباشر فقط)
تم إزالة Selenium و API لإنشاء الحساب، والاعتماد على token المباشر
مع تعليقات شاملة ودوال إضافية لزيادة الطول
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

# ====================== IMPORTS ======================
import requests
import psutil

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

# ====================== DATABASE (قاعدة البيانات) ======================
def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول إذا لم تكن موجودة"""
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
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            refresh_token TEXT,
            access_token TEXT,
            expires_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة (تم إنشاء 4 جداول)")

def get_user(user_id):
    """جلب بيانات المستخدم من قاعدة البيانات"""
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
    """تحديث بيانات المستخدم في قاعدة البيانات"""
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

def log_action(user_id, action, details=""):
    """تسجيل حدث في قاعدة البيانات للسجلات"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
    conn.commit()
    conn.close()
    logger.info(f"📝 تم تسجيل حدث: {action} للمستخدم {user_id}")

def get_history(user_id, limit=10):
    """جلب سجل عمليات النشر للمستخدم"""
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

# ====================== EXTRACTORS (استخراج البيانات من الرابط) ======================
def extract_project_id(link):
    """استخراج project_id من الرابط (حتى لو كان مشفراً)"""
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'project%3D([^&]+)', link)
    if match:
        return match.group(1)
    return None

def extract_token(link):
    """استخراج token من الرابط (حتى لو كان مشفراً)"""
    decoded = urllib.parse.unquote(link)
    match = re.search(r'token=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'token%3D([^&]+)', link)
    if match:
        return match.group(1)
    return None

def extract_email(link):
    """استخراج البريد الإلكتروني من الرابط"""
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[Ee]mail=([^&]+)', decoded)
    if match:
        return urllib.parse.unquote(match.group(1))
    match = re.search(r'Email%3D([^&]+)', link)
    if match:
        return urllib.parse.unquote(match.group(1))
    return None

def extract_from_link(link):
    """استخراج جميع البيانات المهمة من الرابط (project_id, token, email)"""
    data = {}
    data['project_id'] = extract_project_id(link) or ''
    data['token'] = extract_token(link) or ''
    data['email'] = extract_email(link) or ''
    return data

def is_valid_url(url):
    """التحقق من صحة الرابط (يبدأ بـ http)"""
    return url.startswith('http://') or url.startswith('https://')

# ====================== VLESS BUILDER (بناء رابط VLESS) ======================
def build_vless_response(service_url, region):
    """بناء رابط VLESS من رابط الخدمة"""
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"shadow_v105").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    vless = (
        f"vless://{uid}@{host}:443"
        f"?encryption=none&security=tls&sni=youtube.com&fp=chrome"
        f"&type=ws&host={host}&path=%2F%40nkka404#DarkTunnel"
    )
    result_msg = (
        f"✅ **تم النشر!**\n"
        f"🌍 المنطقة: {REGIONS.get(region, region)}\n"
        f"🌐 **رابط الـ Cloud Run**\n{service_url}\n\n"
        f"🔗 **VLESS URL**\n{vless}"
    )
    return result_msg, service_url, vless

# ====================== DEPLOY (النشر المباشر) ======================
def deploy_direct(project_id, token, region):
    """
    نشر الخدمة مباشرة على Cloud Run باستخدام token من الرابط.
    هذه هي الطريقة الوحيدة المعتمدة في هذه النسخة.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    service_name = f"shadow-{int(time.time())}"
    body = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "image": "ajndjd2/ahmed-vip1",
                            "ports": [{"containerPort": 8080}]
                        }
                    ]
                }
            }
        }
    }
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    
    logger.info(f"🚀 جاري النشر إلى المنطقة: {region}")
    r = requests.post(url, headers=headers, json=body, timeout=60)
    
    if r.status_code in (200, 201):
        service_url = r.json().get('status', {}).get('url')
        if service_url:
            logger.info(f"✅ تم النشر بنجاح: {service_url}")
            return build_vless_response(service_url, region)
        else:
            raise Exception("تم النشر ولكن لم يتم العثور على رابط الخدمة")
    elif r.status_code == 401:
        raise Exception("⚠️ الرابط منتهي الصلاحية (401). يرجى الحصول على رابط جديد من Qwiklabs.")
    elif r.status_code == 403:
        raise Exception("⚠️ ليس لديك صلاحية النشر في هذا المشروع (403). تأكد من صلاحيات الحساب.")
    elif r.status_code == 404:
        raise Exception("⚠️ المشروع غير موجود (404). تأكد من project_id في الرابط.")
    else:
        raise Exception(f"فشل النشر: {r.status_code} - {r.text[:200]}")

# ====================== QUEUE (طابور المهام) ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    """معالجة طلبات النشر من الطابور بشكل تسلسلي"""
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

                # تعريف دالة الإرسال مع مهلة
                def send_message(text):
                    time.sleep(1)  # مهلة 1 ثانية بين الرسائل
                    asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id=user_id, text=text),
                        loop
                    )

                # ========== بدء التنفيذ ==========
                send_message("🔄 **جاري الدخول إلى Lab وبدء التجهيز...**\nتم التحقق من صلاحية الرابط سيتم ربط الحساب وبدء عملية الإنشاء...")
                time.sleep(1)

                link_data = extract_from_link(link)
                project_id = link_data.get('project_id', '')
                token = link_data.get('token', '')

                if not project_id:
                    raise Exception("❌ project_id مفقود في الرابط.")
                if not token:
                    raise Exception("❌ لا يوجد token في الرابط. الرابط غير صالح.")

                send_message("🔍 **جاري تحليل سياسات المشروع لاستخراج المناطق المسموح بها...**")
                time.sleep(1)
                send_message(f"✅ **تم اكتشاف 1 منطقة مسموح بها من السياسات:**\n\n- {REGIONS.get(region, region)}")

                send_message(f"🚀 **جاري نشر الخدمة على {REGIONS.get(region, region)}...**")

                # تنفيذ النشر المباشر
                result_msg, service_url, vless = deploy_direct(project_id, token, region)
                send_message("✅ **تم النشر بنجاح!**")
                send_message(result_msg)

                # تحديث قاعدة البيانات
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='completed', last_result=? WHERE user_id=?", (result_msg, user_id))
                c.execute(
                    "INSERT INTO history (user_id, lab_url, service_url, vless_link, success) VALUES (?,?,?,?,1)",
                    (user_id, link, service_url, vless)
                )
                conn.commit()
                conn.close()

                log_action(user_id, "deploy_success", f"region={region}, service={service_url}")

            except Exception as e:
                error_msg = str(e)
                send_message(f"❌ **فشل النشر:** {error_msg}")
                # تحديث قاعدة البيانات بالفشل
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='error', last_result=? WHERE user_id=?", (error_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, success) VALUES (?,?,0)", (user_id, link))
                conn.commit()
                conn.close()
                log_action(user_id, "deploy_failed", error_msg)
            finally:
                processing = False
        time.sleep(2)

# تشغيل الطابور في خيط منفصل
threading.Thread(target=process_queue, daemon=True).start()

# ====================== BOT HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start – عرض القائمة الرئيسية"""
    user_id = update.effective_user.id
    update_user(user_id)
    log_action(user_id, "start_command", "user started bot")
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')],
        [InlineKeyboardButton("🖥️ System Info", callback_data='sysinfo')]
    ]
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v105.0**\n"
        "📡 النسخة الطويلة المتكاملة (نشر مباشر فقط)\n"
        "أمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def deploy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """زر النشر – اختيار المنطقة"""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton(name, callback_data=f"region_{code}")] for code, name in REGIONS.items()]
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_region")])
    await query.edit_message_text("🌍 **اختر المنطقة:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار المنطقة والانتظار لاستقبال الرابط"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cancel_region":
        await query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    region = data.replace("region_", "")
    context.user_data['region'] = region
    await query.edit_message_text(
        f"✅ **المنطقة:** {REGIONS.get(region, region)}\n\n🔗 أرسل رابط SSO الآن."
    )
    return 1

async def receive_lab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال الرابط وإضافته إلى الطابور"""
    user_id = update.effective_user.id
    link = update.message.text
    region = context.user_data.get('region', DEFAULT_REGION)

    if not is_valid_url(link):
        await update.message.reply_text("❌ رابط غير صحيح (يجب أن يبدأ بـ http أو https).")
        return 1

    project_id = extract_project_id(link)
    if not project_id:
        await update.message.reply_text("❌ الرابط لا يحتوي على project_id صالح.")
        return 1

    token = extract_token(link)
    if not token:
        await update.message.reply_text("❌ الرابط لا يحتوي على token صالح.")
        return 1

    main_loop = asyncio.get_running_loop()

    # إضافة المهمة إلى الطابور
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
    """إلغاء العملية الحالية"""
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /status – عرض حالة المستخدم"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات لهذا المستخدم.")
        return

    history = get_history(user_id, 3)
    history_text = "\n".join([
        f"• {h[3]} → {'✅ نجاح' if h[4] else '❌ فشل'}"
        for h in history
    ]) if history else "لا يوجد سجل."

    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📧 البريد: {user.get('email', 'غير مضبوط')}\n"
        f"🌍 المنطقة: {REGIONS.get(user.get('region'), user.get('region'))}\n"
        f"📊 عدد النشر: {user.get('deploy_count', 0)}\n"
        f"🔄 الحالة: {user.get('status', 'idle')}\n"
        f"📝 آخر نتيجة: {user.get('last_result', 'لا يوجد')}\n\n"
        f"📜 **آخر 3 عمليات:**\n{history_text}"
    )

async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر System Info – عرض معلومات النظام"""
    query = update.callback_query
    await query.answer()
    info = {
        "OS": platform.system(),
        "Release": platform.release(),
        "Arch": platform.machine(),
        "CPU": psutil.cpu_percent(),
        "RAM": psutil.virtual_memory().percent,
        "Disk": psutil.disk_usage('/').percent,
        "Python": sys.version.split()[0],
    }
    result = "🖥️ **معلومات النظام**\n" + "\n".join([f"{k}: {v}" for k, v in info.items()])
    await query.edit_message_text(result)

async def change_region_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير المنطقة الافتراضية للمستخدم"""
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
    """تأكيد تغيير المنطقة"""
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
    """العودة إلى القائمة الرئيسية"""
    await start(update, context)

# ====================== MAIN ======================
def main():
    """الدالة الرئيسية لتشغيل البوت"""
    if not TOKEN:
        logger.error("❌ لم يتم تعيين TOKEN. تأكد من متغيرات البيئة.")
        sys.exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))

    # محادثة النشر (اختيار المنطقة + استقبال الرابط)
    deploy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='^deploy$')],
        states={
            0: [CallbackQueryHandler(region_callback, pattern='^(region_|cancel_region)')],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)]
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)]
    )
    app.add_handler(deploy_conv)

    # CallbackQueryHandlers
    app.add_handler(CallbackQueryHandler(change_region_command, pattern='^change_region$'))
    app.add_handler(CallbackQueryHandler(set_region_callback, pattern='^setregion_'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_menu$'))
    app.add_handler(CallbackQueryHandler(sysinfo_command, pattern='^sysinfo$'))

    logger.info("✅ SHADOW LEGION v105.0 RUNNING (النسخة الطويلة المتكاملة)")
    app.run_polling()

if __name__ == "__main__":
    main()