cat > shadow_bot_railway.py << 'EOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v1001 – RAILWAY EDITION (REST API ONLY)
يستخدم REST API بدلاً من gcloud، يعمل بدون تثبيت أي أدوات إضافية.
"""

import os
import re
import time
import json
import hashlib
import logging
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ===================================================================
# 1. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود (ضعه في متغيرات البيئة)")

DB_PATH = "shadow_gcloud.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v1001 (REST API) بدأ التشغيل...")

WAITING_LINK, WAITING_REGION = range(2)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west1": "🇧🇪 بلجيكا",
    "asia-southeast1": "🇸🇬 سنغافورة",
}

# ===================================================================
# 2. قاعدة البيانات (نفس الهيكل)
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            deploy_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT,
            expiry TIMESTAMP,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS deploy_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lab_url TEXT,
            service_url TEXT,
            vless_link TEXT,
            region_used TEXT,
            deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_msg TEXT
        );
    """)
    conn.commit()
    conn.close()
init_db()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT deploy_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"deploy_count": row[0]} if row else None

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", list(kwargs.values()) + [user_id])
    else:
        cols = ",".join(kwargs.keys())
        vals = list(kwargs.values())
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {','.join(['?']*len(vals))})", [user_id] + vals)
    conn.commit()
    conn.close()

def get_cached_token(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry, project_id FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0], row[2]
    return None, None

def save_cached_token(user_id, token, project_id, expiry_seconds=3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, token, expiry.isoformat(), project_id))
    conn.commit()
    conn.close()

def add_history(user_id, lab_url, service_url, vless, region, success=1, error_msg=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ===================================================================
# 3. دوال مساعدة
# ===================================================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'/projects/([^/?]+)', decoded)
    return m.group(1) if m else None

def extract_token_from_link(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    if m:
        return m.group(1)
    return None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("railway_tunnel_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return (
        f"vless://{uid}@{host}:443?"
        f"path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&"
        f"security=tls&"
        f"encryption=none&"
        f"host={host}&"
        f"type=ws&"
        f"sni={host}"
        f"#CloudRun"
    )

# ===================================================================
# 4. النشر عبر REST API (بدون gcloud)
# ===================================================================
def deploy_with_rest_api(project_id, region, access_token):
    service_name = f"ahmed-vip1-{int(time.time())}"
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # هيكل الطلب (نفس ما يفعله gcloud)
    body = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "image": "docker.io/ajndjd2/ahmed-vip1",
                        "ports": [{"containerPort": 8080}]
                    }]
                }
            }
        }
    }
    
    # 1. إرسال طلب النشر
    response = requests.post(url, headers=headers, json=body, timeout=60)
    if response.status_code not in [200, 201]:
        raise Exception(f"فشل النشر (HTTP {response.status_code}): {response.text[:200]}")
    
    data = response.json()
    # الانتظار حتى تصبح الخدمة جاهزة (استطلاع)
    service_url = None
    for _ in range(12):  # 12 * 10 = 120 ثانية (دقيقتان)
        time.sleep(10)
        # جلب حالة الخدمة
        describe_url = f"{url}/{service_name}"
        resp = requests.get(describe_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            status_data = resp.json()
            # التحقق من وجود الرابط
            if status_data.get('status', {}).get('url'):
                service_url = status_data['status']['url']
                break
            # قد يكون حالة "Creating" أو "Provisioning"، نستمر في الانتظار
            conditions = status_data.get('status', {}).get('conditions', [])
            ready = any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in conditions)
            if ready:
                # حاول مرة أخرى جلب الرابط
                continue
        else:
            # إذا كان 404، قد يكون لم ينشأ بعد
            pass
    
    if not service_url:
        # محاولة أخيرة: جلب الخدمة مرة أخرى بعد الانتظار
        time.sleep(15)
        resp = requests.get(describe_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            service_url = resp.json().get('status', {}).get('url')
    
    if not service_url:
        raise Exception("تم النشر لكن لم أجد الرابط في الاستجابة.")
    
    return service_url, build_vless(service_url)

# ===================================================================
# 5. واجهة البوت
# ===================================================================
def region_keyboard(regions):
    keyboard = []
    for r in regions:
        display = KNOWN_REGIONS.get(r, r)
        keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"region_{r}")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context):
    await update.message.reply_text(
        "🔥 **Shadow VPN – REST API Edition**\n"
        "أرسل رابط Qwiklabs، سأنشر الخدمة عبر REST API (بدون gcloud).\n"
        "✅ يعمل على Railway وجميع البيئات."
    )

async def receive_link(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id.")
        return WAITING_LINK

    token = extract_token_from_link(text)
    if not token:
        await update.message.reply_text(
            "❌ لم أجد توكن في الرابط.\n"
            "استخدم الأمر اليدوي:\n"
            "/set_token <التوكن>\n"
            "/set_project <project_id>\n"
            "/deploy"
        )
        return ConversationHandler.END

    save_cached_token(user_id, token, project_id)
    context.user_data["token"] = token
    context.user_data["project_id"] = project_id
    context.user_data["lab_url"] = text

    regions = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    await update.message.reply_text(
        f"✅ **تم استخراج التوكن!**\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"🌍 اختر المنطقة:",
        reply_markup=region_keyboard(regions)
    )
    return WAITING_REGION

async def region_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    region = data.replace("region_", "")
    token = context.user_data.get("token")
    project_id = context.user_data.get("project_id")
    lab_url = context.user_data.get("lab_url")

    if not token or not project_id:
        await query.edit_message_text("❌ انتهت الجلسة")
        return ConversationHandler.END

    await query.edit_message_text(f"🚀 **جاري النشر على {region}...** (قد يستغرق 1-2 دقيقة)")

    try:
        service_url, vless = deploy_with_rest_api(project_id, region, token)
        increment_deploy_count(user_id)
        add_history(user_id, lab_url, service_url, vless, region, success=1)

        await query.message.reply_text(
            f"✅ **تم النشر!**\n"
            f"🌍 المنطقة: {region}\n"
            f"🌐 الرابط: {service_url}\n\n"
            f"🔗 **VLESS النهائي:**\n`{vless}`"
        )

    except Exception as e:
        error_msg = str(e)[:300]
        add_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
        await query.message.reply_text(f"❌ فشل النشر: {error_msg}")

    context.user_data.clear()
    return ConversationHandler.END

async def set_token_command(update: Update, context):
    user_id = update.effective_user.id
    try:
        token = context.args[0]
        if len(token) < 40:
            await update.message.reply_text("❌ التوكن قصير جداً.")
            return
        context.user_data["manual_token"] = token
        await update.message.reply_text("✅ تم حفظ التوكن يدوياً!")
    except:
        await update.message.reply_text("❌ /set_token <التوكن>")

async def set_project_command(update: Update, context):
    user_id = update.effective_user.id
    try:
        project_id = context.args[0]
        context.user_data["project_id"] = project_id
        await update.message.reply_text(f"✅ تم حفظ project_id: `{project_id}`")
    except:
        await update.message.reply_text("❌ /set_project <project_id>")

async def deploy_manual(update: Update, context):
    user_id = update.effective_user.id
    token = context.user_data.get("manual_token")
    project_id = context.user_data.get("project_id")
    if not token or not project_id:
        await update.message.reply_text("❌ يرجى تعيين التوكن و project_id أولاً.")
        return

    regions = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    context.user_data["token"] = token
    context.user_data["project_id"] = project_id

    await update.message.reply_text(
        f"✅ تم حفظ البيانات!\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"🌍 اختر المنطقة:",
        reply_markup=region_keyboard(regions)
    )
    return WAITING_REGION

async def cancel(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 6. التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_token", set_token_command))
    app.add_handler(CommandHandler("set_project", set_project_command))
    app.add_handler(CommandHandler("deploy", deploy_manual))
    app.add_handler(conv)

    logger.info("🚀 Shadow VPN – REST API Edition جاهز (يعمل على Railway)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main() 