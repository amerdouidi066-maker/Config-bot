#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v8.0 – PROFESSIONAL EDITION
بوت احترافي مع أزرار تفاعلية، سجل النشر، إحصائيات، وأتمتة Cloud Shell.
"""

import os
import re
import time
import json
import base64
import sqlite3
import hashlib
import logging
import asyncio
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
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

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
logger.info("🚀 SHADOW LEGION v8.0 (Professional) بدأ التشغيل...")

# ===================================================================
# 2. تعريف الحالات والمتغيرات
# ===================================================================
WAITING_LINK, WAITING_REGION = range(2)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا (الولايات المتحدة)",
    "us-east1": "🇺🇸 ساوث كارولينا (الولايات المتحدة)",
    "us-west1": "🇺🇸 أوريغون (الولايات المتحدة)",
    "europe-west1": "🇧🇪 بلجيكا (أوروبا)",
    "europe-west3": "🇩🇪 فرانكفورت (أوروبا)",
    "europe-west4": "🇳🇱 هولندا (أوروبا)",
    "asia-southeast1": "🇸🇬 سنغافورة (آسيا)",
    "asia-east1": "🇹🇼 تايوان (آسيا)",
    "australia-southeast1": "🇦🇺 سيدني (أستراليا)",
}

# ===================================================================
# 3. قاعدة البيانات (SQLite)
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
            service_name TEXT,
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

# ===================================================================
# 5. دوال مساعدة لاستخراج البيانات
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

def extract_email(link: str) -> str:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]Email=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'#Email=([^&]+)', decoded)
    if m:
        return m.group(1)
    return "student-02-93b0e6f4b24d@qwiklabs.net"

# ===================================================================
# 6. أتمتة Cloud Shell (Playwright)
# ===================================================================
async def run_in_cloudshell(link: str, project_id: str, token: str, email: str, region: str) -> Tuple[bool, str, str, int]:
    start_time = time.time()
    error_msg = ""
    service_url = ""
    vless = ""
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )
            page = await context.new_page()

            # 1. تسجيل الدخول
            logger.info("🌐 فتح رابط تسجيل الدخول...")
            await page.goto(link, timeout=60000, wait_until="networkidle")
            await asyncio.sleep(5)

            # التحقق من عدم ظهور شاشة تسجيل الدخول
            try:
                email_input = await page.wait_for_selector("input[type='email']", timeout=3000)
                if email_input:
                    await browser.close()
                    return False, "", "❌ انتهت صلاحية الرابط! يرجى الحصول على رابط جديد.", int(time.time() - start_time)
            except:
                pass

            logger.info("✅ تم تسجيل الدخول بنجاح.")

            # 2. الدخول إلى Cloud Shell
            logger.info("📂 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")

            # 3. انتظار تحميل الطرفية
            logger.info("⏳ انتظار تحميل الطرفية...")
            terminal_ready = False
            for attempt in range(10):
                try:
                    await page.wait_for_selector(".xterm, .terminal, [role='textbox'], textarea", timeout=5000)
                    logger.info(f"✅ تم العثور على عنصر الطرفية (المحاولة {attempt+1})")
                    terminal_ready = True
                    break
                except:
                    logger.info(f"⏳ المحاولة {attempt+1}/10: لا يزال التحميل جارياً...")
            if not terminal_ready:
                logger.warning("⚠️ لم نتمكن من تأكيد تحميل الطرفية، ننتظر 15 ثانية ونكمل...")
                await asyncio.sleep(15)

            await asyncio.sleep(3)

            # 4. إعداد السكربت وحقنه
            with open("deploy_script.py", "r") as f:
                script_content = f.read()
            script_content = script_content.replace('os.environ.get("PROJECT_ID")', f'"{project_id}"')
            script_content = script_content.replace('os.environ.get("TOKEN")', f'"{token}"')
            script_content = script_content.replace('os.environ.get("EMAIL")', f'"{email}"')
            script_content = script_content.replace('os.environ.get("REGION")', f'"{region}"')
            b64_script = base64.b64encode(script_content.encode()).decode()

            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py",
                "cat result.txt"
            ]

            for cmd in commands:
                logger.info(f"⌨️ كتابة الأمر: {cmd[:50]}...")
                await page.keyboard.type(cmd)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

            # 5. انتظار النتيجة
            logger.info("⏳ انتظار اكتمال النشر وظهور النتيجة (حتى 3 دقائق)...")
            try:
                await page.wait_for_selector("text=/SERVICE_URL:|VLESS:/", timeout=180000)
                logger.info("✅ تم العثور على النتيجة.")
            except:
                logger.warning("⚠️ لم يتم العثور على النتيجة خلال المهلة.")

            await asyncio.sleep(3)
            terminal_text = await page.evaluate("() => document.body.innerText")
            await browser.close()

            # استخراج النتيجة
            service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', terminal_text)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', terminal_text)

            if service_match and vless_match:
                service_url = service_match.group(1)
                vless = vless_match.group(1)
                return True, service_url, vless, int(time.time() - start_time)
            else:
                return False, "", f"⚠️ لم أتمكن من استخراج النتيجة. آخر ما ظهر:\n```\n{terminal_text[-800:]}\n```", int(time.time() - start_time)

    except Exception as e:
        return False, "", str(e), int(time.time() - start_time)

# ===================================================================
# 7. واجهة البوت (الأزرار والقوائم)
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
# 8. أوامر البوت (Handlers)
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = (
        f"🔥 **مرحباً بك في SHADOW LEGION v8.0**\n\n"
        f"أنا بوت احترافي لنشر خدمات Cloud Run عبر أتمتة Cloud Shell.\n"
        f"📌 **كيفية الاستخدام:**\n"
        f"1️⃣ أرسل رابط Qwiklabs (يحتوي على `token=` و `project=`).\n"
        f"2️⃣ اختر المنطقة من القائمة.\n"
        f"3️⃣ انتظر حتى ينتهي النشر (2-3 دقائق).\n"
        f"4️⃣ استلم رابط VLESS الجاهز.\n\n"
        f"🛡️ **الحالة:** يعمل بكفاءة 100% (نفس طريقة Cloud Shell اليدوية).\n"
        f"📦 **الصورة:** `{DOCKER_IMAGE}`"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ **دليل المساعدة**\n\n"
        "🟢 **الأوامر المتاحة:**\n"
        "/start → إظهار القائمة الرئيسية\n"
        "/deploy → بدء عملية نشر جديدة\n"
        "/history → عرض آخر 10 عمليات نشر\n"
        "/stats → عرض إحصائيات حسابك\n"
        "/cancel → إلغاء العملية الحالية\n\n"
        "📌 **ملاحظة:** البوت يستخدم متصفحاً خفياً لأتمتة Cloud Shell، فلا يحتاج إلى أي توكن إضافي."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data:
        await update.message.reply_text("❌ لم أجد بياناتك. استخدم /start أولاً.")
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
        await update.message.reply_text("📭 لا يوجد سجل نشر حتى الآن.")
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
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    token = extract_token(text)
    email = extract_email(text)

    if not project_id:
        await update.message.reply_text("❌ لم أجد `project_id` في الرابط.")
        return WAITING_LINK
    if not token:
        await update.message.reply_text("❌ لم أجد `token` في الرابط.")
        return WAITING_LINK

    context.user_data["project_id"] = project_id
    context.user_data["token"] = token
    context.user_data["email"] = email
    context.user_data["lab_url"] = text

    await update.message.reply_text(
        f"✅ **تم استخراج البيانات!**\n\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"📧 Email: `{email}`\n"
        f"🔑 Token: `{token[:20]}...{token[-10:]}`\n\n"
        f"🌍 **اختر المنطقة:**",
        parse_mode="Markdown",
        reply_markup=region_inline_keyboard()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        context.user_data.clear()
        return ConversationHandler.END

    region = query.data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    email = context.user_data.get("email")
    lab_url = context.user_data.get("lab_url")

    if not project_id or not token:
        await query.edit_message_text("❌ انتهت الجلسة. أعد إرسال الرابط.")
        return ConversationHandler.END

    region_name = KNOWN_REGIONS.get(region, region)
    await query.edit_message_text(
        f"🚀 **جاري النشر على {region_name}...**\n"
        f"⏳ هذه العملية قد تستغرق 2-3 دقائق.\n"
        f"🔄 يرجى الانتظار..."
    )

    success, service_url, vless_or_error, duration = await run_in_cloudshell(
        lab_url, project_id, token, email, region
    )

    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab_url, service_url, service_url, vless_or_error, region, success=1, duration=duration)

        await query.message.reply_text(
            f"✅ **تم النشر بنجاح!**\n\n"
            f"🌍 **المنطقة:** {region_name}\n"
            f"⏱️ **المدة:** {duration} ثانية\n"
            f"🌐 **الرابط:** `{service_url}`\n\n"
            f"🔗 **رابط VLESS الجاهز:**\n`{vless_or_error}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        add_history(user_id, lab_url, "", "", "", region, success=0, error_msg=vless_or_error[:200], duration=duration)
        await query.message.reply_text(
            f"❌ **فشل النشر:**\n\n```\n{vless_or_error[:500]}\n```",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    context.user_data.clear()
    return ConversationHandler.END

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
        await update.message.reply_text("📎 يبدو أنك أرسلت رابطاً. جاري المعالجة...")
        return await receive_link(update, context)

# ===================================================================
# 9. التشغيل الرئيسي
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
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")],
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

    logger.info("🤖 SHADOW LEGION v8.0 (Professional) جاهز ويعمل على Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()