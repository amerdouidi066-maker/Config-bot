#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v14.1 – PROFESSIONAL EDITION
Stealth Browser + Cloud Shell Automation + VLESS Generator
"""

import os
import re
import time
import base64
import hashlib
import logging
import asyncio
import sqlite3
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
from playwright_stealth import stealth_async

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
logger.info("🚀 SHADOW LEGION v14.1 (Professional) بدأ التشغيل...")

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

# ===================================================================
# 6. أتمتة Cloud Shell مع Stealth (نسخة احترافية)
# ===================================================================
async def run_in_cloudshell(link: str, project_id: str, token: str, region: str) -> Tuple[bool, str, str, int]:
    start_time = time.time()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-web-security"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                permissions=["geolocation"],
                geolocation={"latitude": 40.7128, "longitude": -74.0060}
            )
            page = await context.new_page()

            await stealth_async(page)

            logger.info("فتح الرابط (Stealth Mode)...")
            await page.goto(link, timeout=60000, wait_until="networkidle")
            await asyncio.sleep(5)

            # التحقق من تسجيل الدخول
            try:
                await page.wait_for_url(
                    lambda url: "console.cloud.google.com" in url or "shell.cloud.google.com" in url,
                    timeout=30000
                )
                logger.info("تم تسجيل الدخول بنجاح.")
            except:
                current_url = page.url
                await browser.close()
                return False, "", f"❌ فشل تسجيل الدخول (تم الكشف).\nالعنوان الحالي: `{current_url}`", int(time.time() - start_time)

            page_text = await page.inner_text("body")

            # تجاوز شاشة الترحيب
            if "Welcome to your new account" in page_text or ("Welcome" in page_text and "Understand" in page_text):
                logger.info("تجاوز شاشة الترحيب...")
                for selector in ["button:has-text('Understand')", "button:has-text('I understand')"]:
                    try:
                        await page.click(selector, timeout=3000)
                        logger.info("تم الضغط على Understand.")
                        await asyncio.sleep(3)
                        break
                    except:
                        continue

            # تجاوز شاشة الشروط
            if "Terms of Service" in page_text and "I agree to the Google Cloud Platform Terms of Service" in page_text:
                logger.info("تجاوز شاشة الشروط...")
                try:
                    checkbox = await page.query_selector("input[type='checkbox']")
                    if checkbox:
                        await checkbox.check()
                    else:
                        await page.evaluate("""() => {
                            const cb = document.querySelector('input[type="checkbox"]');
                            if (cb && !cb.checked) cb.checked = true;
                        }""")
                    await asyncio.sleep(1)
                    for btn_text in ["Continue", "Agree and Continue", "Agree"]:
                        try:
                            await page.click(f"button:has-text('{btn_text}')", timeout=3000)
                            logger.info(f"تم الضغط على {btn_text}.")
                            await asyncio.sleep(3)
                            break
                        except:
                            continue
                except Exception as e:
                    logger.warning(f"فشل تجاوز الشروط: {e}")

            # التوجه إلى Cloud Shell
            logger.info("التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")

            # الضغط على زر "Start Cloud Shell" إذا ظهر
            try:
                start_button = await page.wait_for_selector(
                    "button:has-text('Start Cloud Shell'), button:has-text('Launch Cloud Shell'), button:has-text('Open Cloud Shell')",
                    timeout=15000
                )
                if start_button:
                    await start_button.click()
                    logger.info("تم الضغط على Start Cloud Shell.")
                    await asyncio.sleep(5)
                else:
                    logger.info("لم يظهر زر Start Cloud Shell، نواصل...")
            except:
                logger.info("لم يتم العثور على زر Start Cloud Shell (بدأت تلقائياً).")

            # انتظار تحميل الطرفية
            logger.info("انتظار تحميل الطرفية...")
            terminal_ready = False
            for attempt in range(15):
                try:
                    await page.wait_for_selector(".xterm, .terminal, [role='textbox']", timeout=5000)
                    terminal_ready = True
                    logger.info(f"الطرفية جاهزة (محاولة {attempt+1})")
                    break
                except:
                    logger.info(f"محاولة {attempt+1}/15...")
            if not terminal_ready:
                await asyncio.sleep(20)

            await asyncio.sleep(3)

            # حقن السكربت
            with open("deploy_script.py", "r") as f:
                script_content = f.read()
            script_content = script_content.replace('os.environ.get("PROJECT_ID")', f'"{project_id}"')
            script_content = script_content.replace('os.environ.get("TOKEN")', f'"{token}"')
            script_content = script_content.replace('os.environ.get("REGION")', f'"{region}"')
            script_content = script_content.replace('os.environ.get("EMAIL")', '"student@qwiklabs.net"')
            b64_script = base64.b64encode(script_content.encode()).decode()

            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py"
            ]

            for cmd in commands:
                logger.info(f"كتابة الأمر: {cmd[:50]}...")
                await page.keyboard.type(cmd)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

            # انتظار النتيجة
            logger.info("انتظار النتيجة (حتى 5 دقائق)...")
            result_text = ""
            for attempt in range(30):
                await asyncio.sleep(10)
                try:
                    terminal_element = await page.query_selector(".xterm, .terminal, [role='textbox']")
                    if terminal_element:
                        result_text = await terminal_element.inner_text()
                    else:
                        result_text = await page.inner_text("body")
                    if "SERVICE_URL:" in result_text or "VLESS:" in result_text:
                        logger.info(f"تم العثور على النتيجة (محاولة {attempt+1})")
                        break
                except:
                    pass

            await browser.close()

            service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', result_text)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_text)

            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time() - start_time)
            else:
                return False, "", f"⚠️ لم أتمكن من استخراج النتيجة.\nآخر ما ظهر:\n```\n{result_text[-800:]}\n```", int(time.time() - start_time)

    except Exception as e:
        return False, "", str(e), int(time.time() - start_time)

# ===================================================================
# 7. واجهة البوت
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
        "🔥 **SHADOW LEGION v14.1 – Professional Edition**\n\n"
        "📌 أرسل رابط Qwiklabs.\n"
        "✅ سيتم أتمتة كل شيء: تسجيل الدخول، تجاوز الشاشات، تنفيذ السكربت.\n"
        "⏳ المدة المتوقعة: 3-5 دقائق. سيتم إرسال النتيجة فور ظهورها.",
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
        await update.message.reply_text("❌ لم أجد بياناتك.")
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
        await update.message.reply_text("📭 لا يوجد سجل نشر.")
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
        f"⏳ المدة المتوقعة: 3-5 دقائق.\n"
        f"🔄 سيتم إعلامك عند الانتهاء."
    )

    success, service_url, vless_or_error, duration = await run_in_cloudshell(
        lab_url, project_id, token, region
    )

    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab_url, service_url, vless_or_error, region, success=1, duration=duration)
        await query.message.reply_text(
            f"✅ **تم النشر بنجاح**\n\n"
            f"🌍 المنطقة: {region_name}\n"
            f"⏱️ المدة: {duration} ثانية\n"
            f"🌐 الرابط: `{service_url}`\n\n"
            f"🔗 **VLESS:**\n`{vless_or_error}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        add_history(user_id, lab_url, "", "", region, success=0, error_msg=vless_or_error[:200], duration=duration)
        await query.message.reply_text(
            f"❌ **فشل النشر**\n\n```\n{vless_or_error}\n```",
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
            WAITING_REGION: [],
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
    
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    logger.info("🤖 SHADOW LEGION v14.1 (Professional) جاهز ويعمل على Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()