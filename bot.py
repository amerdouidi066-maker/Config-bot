#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v999 – GCLOUD SUBPROCESS EDITION
يستخدم gcloud run deploy مباشرة من خلال subprocess.
يعمل مع جلسات Qwiklabs المؤقتة.
"""

import os
import re
import time
import json
import hashlib
import logging
import sqlite3
import subprocess
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
    raise ValueError("❌ TOKEN غير موجود في متغيرات البيئة")

DB_PATH = "shadow_gcloud.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (gcloud subprocess) بدأ التشغيل...")

# حالات المحادثة
WAITING_LINK, WAITING_REGION, CONFIRM_DEPLOY = range(3)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا (الوسطى)",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "us-west1": "🇺🇸 أوريغون",
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
    "asia-southeast1": "🇸🇬 سنغافورة",
    "asia-east1": "🇹🇼 تايوان",
    "australia-southeast1": "🇦🇺 سيدني",
}

# ===================================================================
# 2. قاعدة البيانات
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE IF NOT EXISTS region_stats (
            region_code TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

init_db()

# ===================================================================
# 3. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, deploy_count, status, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "deploy_count": row[1], "status": row[2], "last_activity": row[3]}
    return None

def update_user(user_id: int, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", list(kwargs.values()) + [user_id])
    else:
        if "last_activity" not in kwargs:
            kwargs["last_activity"] = datetime.now().isoformat()
        cols = ",".join(kwargs.keys())
        vals = list(kwargs.values())
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {','.join(['?']*len(vals))})", [user_id] + vals)
    conn.commit()
    conn.close()

def get_cached_token(user_id: int) -> Tuple[Optional[str], Optional[str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry, project_id FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0], row[2]
    return None, None

def save_cached_token(user_id: int, token: str, project_id: str = "", expiry_seconds: int = 3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, token, expiry.isoformat(), project_id))
    conn.commit()
    conn.close()

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()
    c = conn.cursor()
    if success:
        c.execute("INSERT INTO region_stats (region_code, success_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET success_count = success_count + 1", (region,))
    else:
        c.execute("INSERT INTO region_stats (region_code, fail_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET fail_count = fail_count + 1", (region,))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ===================================================================
# 4. دوال مساعدة
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'/projects/([^/?]+)', decoded)
    return m.group(1) if m else None

def extract_token_from_link(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    if m:
        return m.group(1)
    return None

def build_vless_link(service_url: str) -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5(("gcloud_sub" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#GcloudTunnel"

# ===================================================================
# 5. النشر عبر gcloud subprocess (الطريقة النهائية)
# ===================================================================
def deploy_with_gcloud(project_id: str, region: str, token: str) -> Tuple[str, str]:
    """
    يستخدم gcloud run deploy مع التوكن الممرر عبر --cred-file.
    يعيد (service_url, vless_link)
    """
    # إنشاء ملف اعتماد مؤقت من التوكن
    cred_data = {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600
    }
    cred_file = "/tmp/gcloud_cred.json"
    with open(cred_file, "w") as f:
        json.dump(cred_data, f)
    
    service_name = f"app-{int(time.time())}"
    
    # تسجيل الدخول باستخدام الملف المؤقت
    login_cmd = ["gcloud", "auth", "login", "--cred-file", cred_file, "--quiet"]
    try:
        subprocess.run(login_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"فشل تسجيل الدخول إلى gcloud: {e.stderr.decode()}")
    
    # أمر النشر
    deploy_cmd = [
        "gcloud", "run", "deploy", service_name,
        "--image", "ajndjd2/ahmed-vip1",
        "--region", region,
        "--platform", "managed",
        "--port", "8080",
        "--allow-unauthenticated",
        "--project", project_id,
        "--quiet"
    ]
    
    try:
        result = subprocess.run(deploy_cmd, capture_output=True, text=True, check=True)
        output = result.stdout + result.stderr
        # البحث عن الرابط في المخرجات
        match = re.search(r'https://[^\s]+\.run\.app', output)
        if match:
            service_url = match.group(0)
            vless = build_vless_link(service_url)
            return service_url, vless
        else:
            raise Exception("لم أجد رابط الخدمة في مخرجات gcloud")
    except subprocess.CalledProcessError as e:
        raise Exception(f"فشل gcloud run deploy: {e.stderr}")
    finally:
        # حذف ملف الاعتماد المؤقت
        if os.path.exists(cred_file):
            os.remove(cred_file)

# ===================================================================
# 6. الحصول على التوكن (من المخبأ أو الرابط)
# ===================================================================
async def get_master_token(user_id: int, link: str, project_id: str) -> Tuple[Optional[str], bool]:
    # 1. التحقق من المخبأ
    cached_token, cached_project = get_cached_token(user_id)
    if cached_token and cached_project == project_id:
        return cached_token, False
    
    # 2. استخراج من الرابط
    token = extract_token_from_link(link)
    if token:
        save_cached_token(user_id, token, project_id)
        return token, False
    
    return None, True

# ===================================================================
# 7. واجهة البوت (الأزرار والأوامر)
# ===================================================================
def build_region_keyboard(regions: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for r in regions:
        display = KNOWN_REGIONS.get(r, r)
        keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"region_{r}")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

def confirm_keyboard(region: str) -> InlineKeyboardMarkup:
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_regions")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        "🔥 **Shadow VPN – gcloud Edition**\n"
        "أرسل رابط Qwiklabs، سأستخدم gcloud للنشر مباشرة.\n"
        "📌 لا يحتاج إلى صلاحيات API إضافية."
    )

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id.")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    # محاولة استخراج التوكن من الرابط
    token, expired = await get_master_token(user_id, text, project_id)
    if expired or not token:
        await update.message.reply_text(
            "⚠️ لم أجد توكن في الرابط.\n"
            "يرجى استخدام الأمر اليدوي:\n"
            "/set_token <التوكن>\n"
            "/set_project <project_id>\n"
            "/deploy"
        )
        return ConversationHandler.END

    context.user_data["token"] = token

    # عرض المناطق (قائمة ثابتة لأننا لا نستدعي API)
    regions = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    context.user_data["regions"] = regions

    region_list = "\n".join([f"  - {r}" for r in regions])
    await update.message.reply_text(
        f"✅ **تم استخراج التوكن!**\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"📡 المناطق المتاحة:\n{region_list}\n\n"
        "👇 اختر المنطقة:",
        reply_markup=build_region_keyboard(regions)
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        await query.edit_message_text("🌍 اختر المنطقة:", reply_markup=build_region_keyboard(regions))
        return WAITING_REGION

    if data.startswith("region_"):
        region = data.replace("region_", "")
        context.user_data["selected_region"] = region
        keyboard = confirm_keyboard(region)
        await query.edit_message_text(
            f"⚠️ **تأكيد النشر**\n"
            f"المنطقة: {KNOWN_REGIONS.get(region, region)}\n"
            f"هل أنت متأكد؟",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY

    return WAITING_REGION

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        await query.edit_message_text("🌍 اختر المنطقة:", reply_markup=build_region_keyboard(regions))
        return WAITING_REGION

    if data.startswith("confirm_"):
        region = data.replace("confirm_", "")
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        lab_url = context.user_data.get("lab_url")

        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة، أعد إرسال الرابط.")
            return ConversationHandler.END

        await query.edit_message_text(f"🚀 **جاري النشر على {region} عبر gcloud...**\n⏳ قد يستغرق 1-2 دقيقة.")

        try:
            service_url, vless = deploy_with_gcloud(project_id, region, token)
            increment_deploy_count(user_id)
            add_deploy_history(user_id, lab_url, service_url, vless, region, success=1)

            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"🌍 المنطقة: {region}\n"
                f"🌐 رابط Cloud Run:\n{service_url}\n\n"
                f"🔗 رابط VLESS:\n{vless}"
            )
            await query.message.reply_text(result)

        except Exception as e:
            error_msg = str(e)[:300]
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(f"❌ **فشل النشر:**\n{error_msg}")

        context.user_data.clear()
        return ConversationHandler.END

    return CONFIRM_DEPLOY

async def set_token_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        token = context.args[0]
        if len(token) < 40:
            await update.message.reply_text("❌ التوكن قصير جداً.")
            return
        context.user_data["manual_token"] = token
        await update.message.reply_text("✅ تم حفظ التوكن يدوياً! الآن استخدم /set_project و /deploy.")
    except IndexError:
        await update.message.reply_text("❌ /set_token <التوكن>")

async def set_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        project_id = context.args[0]
        context.user_data["project_id"] = project_id
        await update.message.reply_text(f"✅ تم حفظ project_id: `{project_id}`")
    except:
        await update.message.reply_text("❌ /set_project <project_id>")

async def deploy_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.user_data.get("manual_token")
    project_id = context.user_data.get("project_id")
    if not token or not project_id:
        await update.message.reply_text("❌ يرجى تعيين التوكن و project_id أولاً.")
        return

    regions = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    context.user_data["regions"] = regions
    context.user_data["token"] = token
    context.user_data["project_id"] = project_id

    region_list = "\n".join([f"  - {r}" for r in regions])
    await update.message.reply_text(
        f"✅ **تم حفظ البيانات!**\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"📡 المناطق المتاحة:\n{region_list}\n\n"
        "👇 اختر المنطقة:",
        reply_markup=build_region_keyboard(regions)
    )
    return WAITING_REGION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 8. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|back_to_regions|cancel)$")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(confirm_callback, pattern="^(confirm_|back_to_regions)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_token", set_token_command))
    app.add_handler(CommandHandler("set_project", set_project_command))
    app.add_handler(CommandHandler("deploy", deploy_manual))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (gcloud subprocess) جاهز للعمل")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()