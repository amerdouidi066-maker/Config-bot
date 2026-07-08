#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v22.0 – PROFESSIONAL GCLOUD EDITION
بوت احترافي لنشر Cloud Run باستخدام gcloud مباشرة
"""

import os
import re
import time
import json
import sqlite3
import hashlib
import logging
import subprocess
import tempfile
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

DB_PATH = "shadow_legion.db"
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v22.0 (Professional gcloud) بدأ التشغيل...")

# ===================================================================
# 2. تعريف الحالات والمتغيرات
# ===================================================================
WAITING_LINK, WAITING_REGION = range(2)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west4": "🇳🇱 هولندا",
    "asia-southeast1": "🇸🇬 سنغافورة",
}

# ===================================================================
# 3. قاعدة البيانات
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            deploy_count INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            error_msg TEXT,
            duration_seconds INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
init_db()

# ===================================================================
# 4. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_name, deploy_count, last_active, joined_at FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "deploy_count": row[4],
            "last_active": row[5],
            "joined_at": row[6]
        }
    return None

def create_or_update_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        c.execute("UPDATE users SET username=?, first_name=?, last_name=?, last_active=CURRENT_TIMESTAMP WHERE user_id=?",
                  (username, first_name, last_name, user_id))
    else:
        c.execute("INSERT INTO users (user_id, username, first_name, last_name) VALUES (?,?,?,?)",
                  (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1, last_active = CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = "", duration: int = 0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg, duration_seconds)
        VALUES (?,?,?,?,?,?,?,?)
    """, (user_id, lab_url, service_url, vless, region, success, error_msg, duration))
    conn.commit()
    conn.close()

def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, lab_url, service_url, vless_link, region_used, deployed_at, success, error_msg, duration_seconds
        FROM deploy_history WHERE user_id=? ORDER BY deployed_at DESC LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    history = []
    for row in rows:
        history.append({
            "id": row[0],
            "lab_url": row[1],
            "service_url": row[2],
            "vless_link": row[3],
            "region_used": row[4],
            "deployed_at": row[5],
            "success": row[6],
            "error_msg": row[7],
            "duration": row[8]
        })
    return history

# ===================================================================
# 5. دوال مساعدة
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'/projects/([^/?]+)', decoded)
    return m.group(1) if m else None

def extract_token(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url: str) -> str:
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("shadow_legion_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

def find_gcloud() -> str:
    """البحث عن gcloud في المسار أو المواقع الشائعة"""
    for cmd in ["gcloud", "/usr/bin/gcloud", "/usr/lib/google-cloud-sdk/bin/gcloud"]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            return cmd
        except:
            continue
    raise Exception("لم يتم العثور على gcloud. تأكد من تثبيته.")

# ===================================================================
# 6. النشر عبر gcloud (الطريقة الناجحة)
# ===================================================================
def deploy_with_gcloud(project_id: str, token: str, region: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """ينفذ أوامر gcloud مباشرة ويعيد (service_url, vless, error)"""
    start_time = time.time()
    cred_data = {"access_token": token, "token_type": "Bearer", "expires_in": 3600}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(cred_data, f)
        cred_file = f.name

    service_name = f"ahmed-vip1-{int(time.time())}"
    gcloud = find_gcloud()

    try:
        # 1. تسجيل الدخول
        subprocess.run([gcloud, "auth", "login", "--cred-file", cred_file, "--quiet"], check=True, capture_output=True)
        
        # 2. تفعيل API
        subprocess.run([gcloud, "services", "enable", "run.googleapis.com", f"--project={project_id}", "--quiet"], check=True, capture_output=True)
        time.sleep(5)

        # 3. نشر الخدمة
        result = subprocess.run([
            gcloud, "run", "deploy", service_name,
            "--image", DOCKER_IMAGE,
            "--region", region,
            "--platform", "managed",
            "--port", "8080",
            "--allow-unauthenticated",
            "--project", project_id,
            "--quiet"
        ], capture_output=True, text=True, check=True)
        output = result.stdout + result.stderr

        # 4. استخراج الرابط
        match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', output)
        if match:
            service_url = match.group(0)
            duration = int(time.time() - start_time)
            return service_url, build_vless(service_url), None, duration

        # 5. إذا لم يظهر، استخدم describe
        describe_cmd = [
            gcloud, "run", "services", "describe", service_name,
            "--region", region,
            "--project", project_id,
            "--format", "value(status.url)"
        ]
        for _ in range(6):
            time.sleep(5)
            desc_result = subprocess.run(describe_cmd, capture_output=True, text=True)
            url = desc_result.stdout.strip()
            if url and url.startswith("http"):
                duration = int(time.time() - start_time)
                return url, build_vless(url), None, duration

        raise Exception("لم أجد رابط الخدمة بعد المحاولات المتكررة.")

    except subprocess.CalledProcessError as e:
        return None, None, f"فشل gcloud: {e.stderr}", int(time.time() - start_time)
    finally:
        if os.path.exists(cred_file):
            os.remove(cred_file)

# ===================================================================
# 7. واجهة البوت (القوائم والأزرار)
# ===================================================================
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🚀 نشر خدمة جديدة"), KeyboardButton("📊 إحصائياتي")],
        [KeyboardButton("📜 سجل النشر"), KeyboardButton("❓ المساعدة")],
        [KeyboardButton("❌ إلغاء العملية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def region_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for code, name in KNOWN_REGIONS.items():
        keyboard.append([InlineKeyboardButton(f"🌍 {name}", callback_data=f"region_{code}")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

# ===================================================================
# 8. أوامر البوت ومعالجات الأزرار
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v22.0 – Professional gcloud Edition**\n\n"
        "📌 أرسل رابط Qwiklabs (يحتوي على `token=` و `project=`).\n"
        "✅ سأستخدم `gcloud` مباشرة للنشر (بدون متصفح).\n"
        "⚡ أتمتة كاملة 100% – لا حاجة لأي تدخل يدوي.\n\n"
        "📊 استخدم الأزرار أدناه للتنقل.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ **دليل المساعدة**\n\n"
        "/start → القائمة الرئيسية\n"
        "/deploy → بدء نشر جديدة\n"
        "/history → عرض سجل النشر\n"
        "/stats → عرض إحصائياتك\n"
        "/cancel → إلغاء العملية",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data:
        await update.message.reply_text("❌ لم أجد بياناتك. استخدم /start أولاً.")
        return
    await update.message.reply_text(
        f"📊 **إحصائياتك**\n\n"
        f"🆔 المعرف: `{user_data['user_id']}`\n"
        f"👤 الاسم: {user_data['first_name'] or 'غير محدد'}\n"
        f"📦 عدد النشرات: `{user_data['deploy_count']}`\n"
        f"📅 تاريخ الانضمام: `{user_data['joined_at'][:16]}`\n"
        f"⏳ آخر نشاط: `{user_data['last_active'][:16]}`",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    history = get_history(user_id, limit=10)
    if not history:
        await update.message.reply_text("📭 لا يوجد سجل نشر حتى الآن.")
        return
    text = "📜 **آخر 10 عمليات نشر:**\n\n"
    for i, item in enumerate(history, 1):
        status = "✅" if item['success'] else "❌"
        region_display = KNOWN_REGIONS.get(item['region_used'], item['region_used'])
        text += f"{i}. {status} {region_display} - {item['deployed_at'][:16]}\n"
        if item['vless_link']:
            text += f"   🔗 `{item['vless_link'][:50]}...`\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 أرسل رابط Qwiklabs (يبدأ بـ `https://www.skills.google/...`)",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text == "❌ إلغاء العملية":
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    token = extract_token(text)
    if not project_id or not token:
        await update.message.reply_text("❌ لم أجد project_id أو token في الرابط.")
        return WAITING_LINK

    context.user_data["project_id"] = project_id
    context.user_data["token"] = token
    context.user_data["lab_url"] = text

    await update.message.reply_text(
        f"✅ **تم استخراج البيانات**\n"
        f"🆔 Project: `{project_id}`\n"
        f"🔑 Token: `{token[:20]}...`\n\n"
        f"🌍 **اختر المنطقة:**",
        parse_mode="Markdown",
        reply_markup=region_inline_keyboard()
    )
    return WAITING_REGION

# ===================================================================
# 9. معالجات الأزرار (خارج ConversationHandler)
# ===================================================================
async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        context.user_data.clear()
        return

    region = query.data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    lab_url = context.user_data.get("lab_url")

    if not project_id or not token:
        await query.edit_message_text("❌ انتهت الجلسة. أعد إرسال الرابط.")
        return

    region_name = KNOWN_REGIONS.get(region, region)
    await query.edit_message_text(
        f"🚀 **جاري النشر على {region_name}...**\n"
        f"⏳ يستغرق 1-2 دقيقة. يرجى الانتظار..."
    )

    service_url, vless, error, duration = deploy_with_gcloud(project_id, token, region)

    if error:
        add_history(user_id, lab_url, "", "", region, success=0, error_msg=error[:200], duration=duration)
        await query.message.reply_text(
            f"❌ **فشل النشر**\n\n```\n{error}\n```",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        increment_deploy_count(user_id)
        add_history(user_id, lab_url, service_url, vless, region, success=1, duration=duration)
        await query.message.reply_text(
            f"✅ **تم النشر بنجاح!**\n\n"
            f"🌍 المنطقة: {region_name}\n"
            f"⏱️ المدة: {duration} ثانية\n"
            f"🌐 الرابط: `{service_url}`\n\n"
            f"🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    context.user_data.clear()

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم الإلغاء.")
    context.user_data.clear()

# ===================================================================
# 10. أوامر الإلغاء والمساعدة
# ===================================================================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚀 نشر خدمة جديدة":
        return await deploy_command(update, context)
    elif text == "📊 إحصائياتي":
        return await stats_command(update, context)
    elif text == "📜 سجل النشر":
        return await history_command(update, context)
    elif text == "❓ المساعدة":
        return await help_command(update, context)
    elif text == "❌ إلغاء العملية":
        return await cancel(update, context)
    else:
        return await receive_link(update, context)

# ===================================================================
# 11. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("deploy", deploy_command),
            MessageHandler(filters.Regex("^🚀 نشر خدمة جديدة$"), deploy_command)
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [],  # ✅ فارغ – الأزرار تُعالج خارجياً
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(conv_handler)

    # ✅ معالجات الأزرار العامة (خارج ConversationHandler)
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    logger.info("🤖 SHADOW LEGION v22.0 (Professional gcloud) جاهز ويعمل على Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()