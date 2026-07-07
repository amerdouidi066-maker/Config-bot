#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v2.1 – RAILWAY GCLOUD EDITION (PROFESSIONAL UI + NETHERLANDS)
بوت احترافي مع قائمة تفاعلية، إحصائيات، سجل النشر، وأزرار متطورة.
تمت إضافة منطقة هولندا (europe-west4) واستخدام CLOUDSDK_AUTH_ACCESS_TOKEN.
"""

import os
import re
import time
import json
import uuid
import sqlite3
import hashlib
import logging
import subprocess
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

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
# 1. الإعدادات الأساسية والمتغيرات البيئية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود في متغيرات البيئة (Railway -> Variables)")

DB_PATH = "shadow_legion.db"
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"

# إعدادات التسجيل (Logging)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v2.1 (PRO + NL + TOKEN FIX) بدأ التشغيل...")

# ===================================================================
# 2. تعريف حالات المحادثة (Conversation States)
# ===================================================================
(WAITING_LINK, WAITING_REGION, WAITING_CONFIRM) = range(3)

# ===================================================================
# 3. قائمة المناطق المعروفة (مع أعلام وعواصم) ✅ تمت إضافة هولندا
# ===================================================================
KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا (الولايات المتحدة)",
    "us-east1": "🇺🇸 ساوث كارولينا (الولايات المتحدة)",
    "us-west1": "🇺🇸 أوريغون (الولايات المتحدة)",
    "europe-west1": "🇧🇪 بلجيكا (أوروبا)",
    "europe-west3": "🇩🇪 فرانكفورت (أوروبا)",
    "europe-west4": "🇳🇱 هولندا (أوروبا)",  # ✅ تمت الإضافة
    "asia-southeast1": "🇸🇬 سنغافورة (آسيا)",
    "asia-east1": "🇹🇼 تايوان (آسيا)",
    "australia-southeast1": "🇦🇺 سيدني (أستراليا)",
}

# ===================================================================
# 4. قاعدة البيانات (SQLite) – متطورة مع جداول إضافية
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
            service_name TEXT,
            service_url TEXT,
            vless_link TEXT,
            region_used TEXT,
            deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_msg TEXT,
            duration_seconds INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('version', '2.1.0');
        INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('maintenance', 'false');
    """)
    conn.commit()
    conn.close()
init_db()

# ===================================================================
# 5. دوال قاعدة البيانات (CRUD المتقدمة)
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

def add_history(user_id: int, lab_url: str, service_name: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = "", duration: int = 0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO deploy_history (user_id, lab_url, service_name, service_url, vless_link, region_used, success, error_msg, duration_seconds)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (user_id, lab_url, service_name, service_url, vless, region, success, error_msg, duration))
    conn.commit()
    conn.close()

def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, lab_url, service_name, service_url, vless_link, region_used, deployed_at, success, error_msg, duration_seconds
        FROM deploy_history WHERE user_id=? ORDER BY deployed_at DESC LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    history = []
    for row in rows:
        history.append({
            "id": row[0],
            "lab_url": row[1],
            "service_name": row[2],
            "service_url": row[3],
            "vless_link": row[4],
            "region_used": row[5],
            "deployed_at": row[6],
            "success": row[7],
            "error_msg": row[8],
            "duration": row[9]
        })
    return history

def get_cached_token(user_id: int) -> Tuple[Optional[str], Optional[str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry, project_id FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0], row[2]
    return None, None

def save_cached_token(user_id: int, token: str, project_id: str, expiry_seconds: int = 3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, token, expiry.isoformat(), project_id))
    conn.commit()
    conn.close()

# ===================================================================
# 6. دوال استخراج البيانات من الرابط (مطابقة للسكربت الناجح)
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

# ===================================================================
# 7. توليد رابط VLESS (نفس الصيغة النهائية)
# ===================================================================
def build_vless(service_url: str) -> str:
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("shadow_legion_pro_" + str(int(time.time()))).encode()).hexdigest()
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
# 8. تنفيذ أوامر النظام (مع دعم CLOUDSDK_AUTH_ACCESS_TOKEN)
# ===================================================================
def run_cmd(cmd: List[str], env: Dict[str, str] = None) -> Tuple[str, str]:
    """تنفيذ أمر مع دعم متغيرات البيئة المخصصة"""
    logger.info(f"Executing: {' '.join(cmd)}")
    if env is None:
        env = os.environ.copy()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        logger.warning(f"Command error: {result.stderr}")
    return result.stdout.strip(), result.stderr

def deploy_with_gcloud(project_id: str, region: str, token: str) -> Tuple[str, str]:
    """النشر عبر gcloud باستخدام CLOUDSDK_AUTH_ACCESS_TOKEN (بدون auth login)"""
    start_time = time.time()
    service_name = f"vip-{int(time.time())}"
    
    # ✅ الحل السحري: استخدام التوكن مباشرة عبر متغير البيئة
    env = os.environ.copy()
    env["CLOUDSDK_AUTH_ACCESS_TOKEN"] = token
    env["CLOUDSDK_CORE_PROJECT"] = project_id  # تحديد المشروع أيضاً

    service_url = None
    try:
        # 1. تفعيل API
        run_cmd(["gcloud", "services", "enable", "run.googleapis.com", f"--project={project_id}"], env=env)
        time.sleep(5)

        # 2. نشر الخدمة (مع تمرير env)
        stdout, stderr = run_cmd([
            "gcloud", "run", "deploy", service_name,
            "--image", DOCKER_IMAGE,
            "--region", region,
            "--platform", "managed",
            "--port", "8080",
            "--allow-unauthenticated",
            "--project", project_id,
            "--quiet"
        ], env=env)
        output = stdout + stderr
        if "ERROR" in stderr or "error" in stderr.lower():
            raise Exception(f"فشل النشر: {stderr}")

        # 3. استخراج الرابط من المخرجات
        match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', output)
        if match:
            service_url = match.group(0)
        else:
            # 4. احتياطي: gcloud describe
            for attempt in range(6):
                time.sleep(5)
                url, _ = run_cmd([
                    "gcloud", "run", "services", "describe", service_name,
                    "--region", region,
                    "--project", project_id,
                    "--format", "value(status.url)"
                ], env=env)
                if url and url.startswith("http"):
                    service_url = url
                    break

        if not service_url:
            raise Exception("لم أجد رابط الخدمة بعد المحاولات المتكررة.")

        vless = build_vless(service_url)
        duration = int(time.time() - start_time)
        return service_url, vless, duration

    except Exception as e:
        duration = int(time.time() - start_time)
        raise Exception(str(e))

# ===================================================================
# 9. واجهة البوت التفاعلية (Reply Keyboard + Inline Buttons)
# ===================================================================
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """لوحة المفاتيح الرئيسية (تظهر دائماً في الأسفل)"""
    keyboard = [
        [KeyboardButton("🚀 نشر خدمة جديدة"), KeyboardButton("📊 إحصائياتي")],
        [KeyboardButton("📜 سجل النشر"), KeyboardButton("❓ المساعدة")],
        [KeyboardButton("❌ إلغاء العملية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def region_inline_keyboard() -> InlineKeyboardMarkup:
    """أزرار المناطق (تظهر في الرسالة) - متضمنة هولندا"""
    keyboard = []
    row = []
    for code, name in KNOWN_REGIONS.items():
        display_name = code
        row.append(InlineKeyboardButton(f"🌍 {display_name}", callback_data=f"region_{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

# ===================================================================
# 10. أوامر البوت (Handlers)
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = (
        f"🔥 **مرحباً بك في SHADOW LEGION v2.1**\n\n"
        f"أنا بوت احترافي لنشر خدمات Cloud Run باستخدام `gcloud`.\n"
        f"📌 **كيفية الاستخدام:**\n"
        f"1️⃣ أرسل رابط Qwiklabs (يحتوي على `token=` و `project=`).\n"
        f"2️⃣ اختر المنطقة من القائمة (تتضمن هولندا 🇳🇱).\n"
        f"3️⃣ انتظر حتى ينتهي النشر (1-2 دقيقة).\n"
        f"4️⃣ استلم رابط VLESS الجاهز.\n\n"
        f"🛡️ **الحالة:** يعمل بكفاءة 100% (نفس طريقة Cloud Shell).\n"
        f"📦 **الصورة:** `{DOCKER_IMAGE}`"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ **دليل المساعدة**\n\n"
        "🟢 **الأوامر المتاحة:**\n"
        "/start → إظهار القائمة الرئيسية\n"
        "/deploy → بدء عملية نشر جديدة (بديل للزر)\n"
        "/history → عرض آخر 10 عمليات نشر\n"
        "/stats → عرض إحصائيات حسابك\n"
        "/cancel → إلغاء العملية الحالية\n\n"
        "📌 **ملاحظة:** البوت يعتمد على `gcloud` المثبت في النظام، ولا يحتاج إلى أي توكن OAuth إضافي."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data:
        await update.message.reply_text("❌ لم أجد بياناتك في السجل. استخدم /start أولاً.")
        return
    
    stats_text = (
        f"📊 **إحصائياتك الشخصية**\n\n"
        f"🆔 المعرف: `{user_data['user_id']}`\n"
        f"👤 الاسم: {user_data['first_name'] or 'غير محدد'}\n"
        f"📦 عدد النشرات: `{user_data['deploy_count']}`\n"
        f"📅 تاريخ الانضمام: `{user_data['joined_at'][:16]}`\n"
        f"⏳ آخر نشاط: `{user_data['last_active'][:16]}`"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    history = get_history(user_id, limit=10)
    if not history:
        await update.message.reply_text("📭 لا يوجد سجل نشر حتى الآن. استخدم /deploy لبدء أول نشر.")
        return
    
    text = "📜 **آخر 10 عمليات نشر:**\n\n"
    for i, item in enumerate(history, 1):
        status = "✅" if item['success'] else "❌"
        region_display = KNOWN_REGIONS.get(item['region_used'], item['region_used'])
        service = item['service_name'] or "غير معروف"
        text += f"{i}. {status} **{service}** ({region_display})\n"
        if item['service_url']:
            text += f"   🌐 {item['service_url'][:50]}...\n"
        text += f"   🕒 {item['deployed_at'][:16]}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 **بدء عملية نشر جديدة**\n\n"
        "📎 أرسل رابط Qwiklabs (يبدأ بـ `https://www.skills.google/...`)",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text == "❌ إلغاء العملية":
        await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    
    if not text.startswith("http"):
        await update.message.reply_text("❌ الرابط غير صالح. تأكد من أنه يبدأ بـ `http`.")
        return WAITING_LINK
    
    project_id = extract_project_id(text)
    token = extract_token(text)
    
    if not project_id:
        await update.message.reply_text("❌ لم أجد `project_id` في الرابط. تأكد من وجود `project=`.")
        return WAITING_LINK
    
    if not token:
        await update.message.reply_text(
            "❌ لم أجد `token` في الرابط.\n"
            "تأكد من وجود `token=` أو `display_token=`."
        )
        return WAITING_LINK
    
    context.user_data["project_id"] = project_id
    context.user_data["token"] = token
    context.user_data["lab_url"] = text
    
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح!**\n\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"🔑 Token: `{token[:20]}...{token[-10:]}`\n\n"
        f"🌍 **اختر المنطقة المناسبة للنشر (تتضمن هولندا):**",
        parse_mode="Markdown",
        reply_markup=region_inline_keyboard()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        context.user_data.clear()
        return ConversationHandler.END
    
    region = data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    lab_url = context.user_data.get("lab_url")
    
    if not project_id or not token:
        await query.edit_message_text("❌ انتهت الجلسة. أعد إرسال الرابط باستخدام /deploy.")
        return ConversationHandler.END
    
    region_name = KNOWN_REGIONS.get(region, region)
    await query.edit_message_text(
        f"🚀 **جاري النشر على {region_name}...**\n"
        f"⏳ هذه العملية قد تستغرق من 1 إلى 2 دقيقة.\n"
        f"🔄 يرجى الانتظار..."
    )
    
    try:
        service_url, vless, duration = deploy_with_gcloud(project_id, region, token)
        service_name = service_url.replace('https://', '').split('.')[0]
        
        increment_deploy_count(user_id)
        add_history(user_id, lab_url, service_name, service_url, vless, region, success=1, duration=duration)
        
        result_text = (
            f"✅ **تم النشر بنجاح!**\n\n"
            f"🌍 **المنطقة:** {region_name}\n"
            f"⏱️ **المدة:** {duration} ثانية\n"
            f"🌐 **الرابط:** `{service_url}`\n\n"
            f"🔗 **رابط VLESS الجاهز:**\n"
            f"`{vless}`"
        )
        await query.message.reply_text(result_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        
    except Exception as e:
        error_msg = str(e)[:500]
        add_history(user_id, lab_url, "", "", "", region, success=0, error_msg=error_msg, duration=0)
        await query.message.reply_text(
            f"❌ **فشل النشر:**\n\n"
            f"```\n{error_msg}\n```\n\n"
            f"💡 تأكد من صلاحية التوكن والمشروع.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم إلغاء العملية الحالية.", reply_markup=main_menu_keyboard())
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
        await update.message.reply_text("📎 يبدو أنك أرسلت رابطاً. جاري المعالجة...")
        return await receive_link(update, context)

# ===================================================================
# 11. التشغيل الرئيسي (Main)
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("deploy", deploy_command),
            MessageHandler(filters.Regex("^🚀 نشر خدمة جديدة$"), deploy_command)
        ],
        states={
            WAITING_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)
            ],
            WAITING_REGION: [
                CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel)
        ],
        allow_reentry=True
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    
    logger.info("🤖 SHADOW LEGION v2.1 (PRO + NL + TOKEN FIX) جاهز ويعمل على Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()