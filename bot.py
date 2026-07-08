#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v15.1 – ULTIMATE STEALTH (FIXED)
أقوى أدوات التخفي (بدون playwright-extra)
"""

import os
import re
import time
import base64
import hashlib
import logging
import asyncio
import random
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
from playwright_stealth import stealth_async, StealthConfig
from fake_useragent import UserAgent

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
logger.info("🚀 SHADOW LEGION v15.1 (Ultimate Stealth) بدأ التشغيل...")

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

# وكيل مستخدم عشوائي
ua = UserAgent()

# بصمات WebGL عشوائية
WEBGL_VENDORS = ["Google Inc.", "Intel Inc.", "NVIDIA Corporation", "AMD", "Apple Inc."]
WEBGL_RENDERERS = [
    "ANGLE (Intel, Intel(R) UHD Graphics 620, Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti, Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD, Radeon RX 580, Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (Apple, Apple M1, OpenGL 4.1)",
]

# مواقع جغرافية عشوائية
LOCATIONS = [
    {"latitude": 40.7128, "longitude": -74.0060},
    {"latitude": 51.5074, "longitude": -0.1278},
    {"latitude": 48.8566, "longitude": 2.3522},
    {"latitude": 35.6895, "longitude": 139.6917},
    {"latitude": 37.7749, "longitude": -122.4194},
    {"latitude": 25.2048, "longitude": 55.2708},
]

# ===================================================================
# 3. قاعدة البيانات (نفسها)
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
# 4. دوال مساعدة
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

def random_delay(min_sec: float = 0.5, max_sec: float = 2.0) -> float:
    return random.uniform(min_sec, max_sec)

# ===================================================================
# 5. أتمتة Cloud Shell – النسخة الخارقة (بدون playwright-extra)
# ===================================================================
async def run_in_cloudshell(link: str, project_id: str, token: str, region: str) -> Tuple[bool, str, str, int]:
    start_time = time.time()
    
    # إعدادات التخفي العشوائية
    user_agent = ua.random
    webgl_vendor = random.choice(WEBGL_VENDORS)
    webgl_renderer = random.choice(WEBGL_RENDERERS)
    location = random.choice(LOCATIONS)
    viewport_width = random.choice([1366, 1440, 1536, 1600, 1920, 2560])
    viewport_height = random.choice([768, 900, 960, 1050, 1080, 1440])
    timezones = ["America/New_York", "Europe/London", "Europe/Paris", "Asia/Tokyo", "America/Los_Angeles", "Asia/Dubai"]
    timezone = random.choice(timezones)
    locales = ["en-US", "en-GB", "fr-FR", "de-DE", "es-ES", "ja-JP", "ar-SA"]
    locale = random.choice(locales)
    device_scale_factor = random.choice([1, 1.5, 2])
    
    logger.info(f"🕵️ وكيل المستخدم: {user_agent[:60]}...")
    
    for attempt in range(3):
        logger.info(f"🔄 المحاولة {attempt+1}/3 (بصمة جديدة)")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless="new",
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        f"--window-size={viewport_width},{viewport_height}",
                        "--disable-gpu",
                        "--disable-software-rasterizer",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--disable-web-security",
                        "--disable-features=BlockInsecurePrivateNetworkRequests",
                        "--disable-features=OutOfBlinkCors",
                        "--disable-features=SameSiteByDefaultCookies",
                        "--disable-ipc-flooding-protection",
                        "--disable-renderer-backgrounding",
                        "--disable-background-timer-throttling",
                        "--disable-backgrounding-occluded-windows",
                        "--disable-breakpad",
                        "--disable-client-side-phishing-detection",
                        "--disable-component-extensions-with-background-pages",
                        "--disable-default-apps",
                        "--disable-domain-reliability",
                        "--disable-extensions",
                        "--disable-field-trial-config",
                        "--disable-hang-monitor",
                        "--disable-prompt-on-repost",
                        "--disable-sync",
                        "--disable-translate",
                        "--metrics-recording-only",
                        "--safebrowsing-disable-auto-update",
                        "--disable-features=OptimizationGuideModelDownloading",
                        "--disable-features=MediaRouter",
                        "--disable-features=TranslateUI",
                        "--disable-features=GlobalMediaControls",
                        "--disable-features=TabGroups",
                        "--disable-features=PrivacySandboxAdsAPIsOverride",
                    ]
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": viewport_width, "height": viewport_height},
                    locale=locale,
                    timezone_id=timezone,
                    permissions=["geolocation"],
                    geolocation=location,
                    color_scheme="light",
                    device_scale_factor=device_scale_factor,
                    is_mobile=False,
                    has_touch=False,
                    java_script_enabled=True,
                    accept_downloads=True,
                    extra_http_headers={
                        "Accept-Language": locale.replace("-", "_"),
                        "Accept-Encoding": "gzip, deflate, br",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Upgrade-Insecure-Requests": "1",
                    }
                )
                page = await context.new_page()

                # تطبيق Stealth (بدون playwright-extra)
                await stealth_async(page, config=StealthConfig(
                    webgl_vendor=True,
                    renderer_webgl=True,
                    canvas=True,
                    webgl=True,
                    audio_context=True,
                    languages=True,
                    navigator_plugins=True,
                    navigator_permissions=True,
                    navigator_webdriver=True,
                    chrome_app=True,
                    chrome_runtime=True,
                    iframe=True,
                    media_codecs=True,
                    out_media=True,
                    shared_array_buffer=True,
                    speech_synthesis=True,
                    user_agent=True,
                ))

                # 1. فتح الرابط
                logger.info("🌐 فتح الرابط (بصمة جديدة)...")
                await page.goto(link, timeout=60000, wait_until="networkidle")
                await asyncio.sleep(random_delay(2, 4))

                # 2. التحقق من تسجيل الدخول
                try:
                    await page.wait_for_url(
                        lambda url: "console.cloud.google.com" in url or "shell.cloud.google.com" in url,
                        timeout=30000
                    )
                    logger.info("✅ تم تسجيل الدخول بنجاح.")
                except:
                    current_url = page.url
                    await browser.close()
                    if attempt == 2:
                        return False, "", f"❌ فشل تسجيل الدخول (بعد 3 محاولات).\nالعنوان الحالي: `{current_url}`", int(time.time() - start_time)
                    else:
                        logger.warning(f"⚠️ فشل تسجيل الدخول في المحاولة {attempt+1}، نعيد المحاولة...")
                        continue

                # 3. تجاوز شاشات الترحيب والشروط (نفس الكود السابق)
                page_text = await page.inner_text("body")

                if "Welcome to your new account" in page_text or ("Welcome" in page_text and "Understand" in page_text):
                    logger.info("👋 شاشة الترحيب...")
                    for selector in ["button:has-text('Understand')", "button:has-text('I understand')"]:
                        try:
                            await page.click(selector, timeout=3000)
                            logger.info("✅ تم الضغط على Understand.")
                            await asyncio.sleep(random_delay(2, 3))
                            break
                        except:
                            continue

                if "Terms of Service" in page_text and "I agree to the Google Cloud Platform Terms of Service" in page_text:
                    logger.info("📜 شاشة الشروط...")
                    try:
                        checkbox = await page.query_selector("input[type='checkbox']")
                        if checkbox:
                            await checkbox.check()
                        else:
                            await page.evaluate("""() => {
                                const cb = document.querySelector('input[type="checkbox"]');
                                if (cb && !cb.checked) cb.checked = true;
                            }""")
                        await asyncio.sleep(random_delay(0.5, 1))
                        for btn_text in ["Continue", "Agree and Continue", "Agree"]:
                            try:
                                await page.click(f"button:has-text('{btn_text}')", timeout=3000)
                                logger.info(f"✅ تم الضغط على {btn_text}.")
                                await asyncio.sleep(random_delay(2, 3))
                                break
                            except:
                                continue
                    except Exception as e:
                        logger.warning(f"⚠️ فشل تجاوز الشروط: {e}")

                # 4. التوجه إلى Cloud Shell
                logger.info("📂 التوجه إلى Cloud Shell...")
                await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(random_delay(2, 4))

                # 5. الضغط على Start Cloud Shell (JavaScript)
                logger.info("🔍 البحث عن زر Start Cloud Shell...")
                clicked = False
                for js_attempt in range(3):
                    try:
                        clicked = await page.evaluate("""() => {
                            const elements = document.querySelectorAll('*');
                            for (let el of elements) {
                                const text = el.innerText || el.textContent || '';
                                if (text.includes('Start Cloud Shell') || text.includes('Launch Cloud Shell')) {
                                    if (el.tagName === 'BUTTON' || el.tagName === 'A') {
                                        el.click();
                                        return true;
                                    }
                                    const clickable = el.closest('button') || el.closest('a') || el;
                                    clickable.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if clicked:
                            logger.info("✅ تم الضغط على Start Cloud Shell (JavaScript).")
                            break
                    except:
                        pass
                    await asyncio.sleep(1)
                
                if not clicked:
                    logger.info("⏳ ننتظر 15 ثانية (ربما بدأت تلقائياً)...")
                    await asyncio.sleep(15)

                # 6. انتظار الطرفية
                logger.info("⏳ انتظار تحميل الطرفية...")
                terminal_ready = False
                for attempt_terminal in range(20):
                    try:
                        await page.wait_for_selector(".xterm, .terminal, [role='textbox']", timeout=5000)
                        terminal_ready = True
                        logger.info(f"✅ الطرفية جاهزة (محاولة {attempt_terminal+1})")
                        break
                    except:
                        logger.info(f"⏳ المحاولة {attempt_terminal+1}/20...")
                if not terminal_ready:
                    await asyncio.sleep(20)

                await asyncio.sleep(random_delay(2, 4))

                # 7. حقن السكربت
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
                    logger.info(f"⌨️ كتابة الأمر: {cmd[:50]}...")
                    await page.keyboard.type(cmd)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(random_delay(2, 4))

                # 8. انتظار النتيجة
                logger.info("⏳ انتظار النتيجة (حتى 5 دقائق)...")
                result_text = ""
                for attempt_result in range(30):
                    await asyncio.sleep(10)
                    try:
                        terminal_element = await page.query_selector(".xterm, .terminal, [role='textbox']")
                        if terminal_element:
                            result_text = await terminal_element.inner_text()
                        else:
                            result_text = await page.inner_text("body")
                        if "SERVICE_URL:" in result_text or "VLESS:" in result_text:
                            logger.info(f"✅ تم العثور على النتيجة (محاولة {attempt_result+1})")
                            break
                    except:
                        pass

                await browser.close()

                service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', result_text)
                vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_text)

                if service_match and vless_match:
                    return True, service_match.group(1), vless_match.group(1), int(time.time() - start_time)
                else:
                    if attempt == 2:
                        return False, "", f"⚠️ لم أتمكن من استخراج النتيجة.\nآخر ما ظهر:\n```\n{result_text[-800:]}\n```", int(time.time() - start_time)
                    else:
                        logger.warning(f"⚠️ لم تظهر النتيجة في المحاولة {attempt+1}، نعيد المحاولة...")
                        continue

        except Exception as e:
            if attempt == 2:
                return False, "", str(e), int(time.time() - start_time)
            else:
                logger.warning(f"⚠️ خطأ في المحاولة {attempt+1}: {e}، نعيد المحاولة...")
                continue

    return False, "", "❌ فشلت جميع المحاولات (3 محاولات).", int(time.time() - start_time)

# ===================================================================
# 6. واجهة البوت (نفسها)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v15.1 – ULTIMATE STEALTH (FIXED)**\n\n"
        "📌 أرسل رابط Qwiklabs.\n"
        "🕵️ أقوى أدوات التخفي:\n"
        "   • بصمة متصفح عشوائية (WebGL, Canvas, AudioContext)\n"
        "   • وكيل مستخدم عشوائي\n"
        "   • موقع جغرافي عشوائي\n"
        "   • إعادة محاولة تلقائية (3 محاولات)\n"
        "   • أحدث إصدار headless (new)\n"
        "   • تأخيرات عشوائية (سلوك بشري)\n"
        "⏳ المدة المتوقعة: 3-6 دقائق.",
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
        f"🕵️ يتم تطبيق بصمة متصفح عشوائية...\n"
        f"⏳ المدة المتوقعة: 3-6 دقائق.\n"
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
# 7. التشغيل الرئيسي
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

    logger.info("🤖 SHADOW LEGION v15.1 (Ultimate Stealth) جاهز ويعمل على Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()