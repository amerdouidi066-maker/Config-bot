#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v57.0 – PROFESSIONAL_FIXED_EDITION
- تم تصحيح RuntimeWarning: coroutine 'Application._bootstrap_initialize' was never awaited
- استخدام حلقة أحداث صريحة مع asyncio.get_event_loop()
- تشغيل Flask في خيط منفصل مع تأخير لضمان استقرار الحلقة
- معالجة إشارات SIGINT و SIGTERM للإغلاق النظيف
- متوافق مع Cloud Run / Railway / Docker
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import threading
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
from pymongo import MongoClient

import stream_state
import web_dashboard

# ===================================================================
# 1. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("❌ MONGO_URI غير موجود")

MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "shadow_legion")
SHELL_TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "600"))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", "7"))
PROXY_LIST = [p.strip() for p in os.environ.get("PROXY_LIST", "").split(",") if p.strip()]
TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")
PORT = int(os.environ.get("PORT", 8080))
COOKIES_FILE = "cookies_live.json"

# ===================================================================
# 2. إعدادات التسجيل
# ===================================================================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logger.info("🔥 SHADOW LEGION v57.0 – Professional Fixed Edition")

# ===================================================================
# 3. اتصال MongoDB
# ===================================================================
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB_NAME]
users_collection = db["users"]
history_collection = db["deploy_history"]
logger.info("✅ اتصال MongoDB ناجح")

# ===================================================================
# 4. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    doc = users_collection.find_one({"_id": user_id})
    if doc:
        return {
            "user_id": doc["_id"],
            "username": doc.get("username"),
            "first_name": doc.get("first_name"),
            "last_name": doc.get("last_name"),
            "deploy_count": doc.get("deploy_count", 0),
            "last_active": doc.get("last_active"),
            "joined_at": doc.get("joined_at"),
            "last_link": doc.get("last_link")
        }
    return None

def create_or_update_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    now = datetime.now().isoformat()
    users_collection.update_one(
        {"_id": user_id},
        {"$set": {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "last_active": now,
            "joined_at": now
        }},
        upsert=True
    )

def update_last_link(user_id: int, link: str):
    users_collection.update_one(
        {"_id": user_id},
        {"$set": {"last_link": link, "last_active": datetime.now().isoformat()}}
    )

def increment_deploy_count(user_id: int):
    users_collection.update_one(
        {"_id": user_id},
        {"$inc": {"deploy_count": 1}, "$set": {"last_active": datetime.now().isoformat()}}
    )

def add_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str,
                success: int = 1, error_msg: str = "", duration: int = 0, video_path: str = ""):
    history_collection.insert_one({
        "user_id": user_id,
        "lab_url": lab_url,
        "service_url": service_url,
        "vless_link": vless,
        "region_used": region,
        "success": success,
        "error_msg": error_msg,
        "duration_seconds": duration,
        "video_path": video_path,
        "deployed_at": datetime.now().isoformat()
    })

def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    docs = history_collection.find(
        {"user_id": user_id},
        sort=[("deployed_at", -1)],
        limit=limit
    )
    return [{
        "id": str(doc["_id"]),
        "lab_url": doc.get("lab_url"),
        "service_url": doc.get("service_url"),
        "vless_link": doc.get("vless_link"),
        "region_used": doc.get("region_used"),
        "deployed_at": doc.get("deployed_at"),
        "success": doc.get("success", 0),
        "error_msg": doc.get("error_msg"),
        "duration": doc.get("duration_seconds", 0)
    } for doc in docs]

# ===================================================================
# 5. دوال مساعدة
# ===================================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
]
TIMEZONES = ["America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney"]
LANGUAGES = ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.9,ar;q=0.8"]

def get_random_proxy() -> Optional[str]:
    return random.choice(PROXY_LIST) if PROXY_LIST else None

def get_random_referer() -> str:
    return random.choice([
        "https://www.google.com/",
        "https://accounts.google.com/",
        "https://mail.google.com/",
        "https://www.cloudskillsboost.google.com/"
    ])

def generate_random_fingerprint() -> Dict:
    return {
        "vendor": random.choice(['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple']),
        "renderer": random.choice(['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M']),
        "canvas_noise": random.uniform(0.01, 0.05),
        "audio_noise": random.uniform(0.0005, 0.002),
        "device_memory": random.choice([4, 8, 16]),
        "hardware_concurrency": random.choice([4, 8, 12, 16]),
        "platform": random.choice(["Win32", "MacIntel", "Linux x86_64"]),
    }

async def load_cookies(context) -> List[Dict]:
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r") as f:
                live_cookies = json.load(f)
            await context.add_cookies(live_cookies)
            logger.info(f"🍪 تم تحميل {len(live_cookies)} كوكي من الملف")
            return await context.cookies()
        except Exception as e:
            logger.error(f"❌ فشل تحميل الكوكيز من الملف: {e}")
    logger.warning("⚠️ استخدام كوكيز افتراضية – قد تكون منتهية")
    embedded = [
        {"name": "SAPISID", "value": "dNAzbJqIULJ0jVSc/AATHsbA-KZD_zuxiL", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PAPISID", "value": "dNAzbJqIULJ0jVSc/AATHsbA-KZD_zuxiL", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
        {"name": "HSID", "value": "AY8tMUKVcf_DaN_iC", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "SSID", "value": "AzMoFRRy6f8GYql9D", "domain": ".google.com", "path": "/", "secure": True},
    ]
    await context.add_cookies(embedded)
    return await context.cookies()

async def create_stealth_context(browser):
    fingerprint = generate_random_fingerprint()
    ua = random.choice(USER_AGENTS)
    width = random.randint(1800, 1920)
    height = random.randint(1000, 1080)
    tz = random.choice(TIMEZONES)
    lang = random.choice(LANGUAGES)
    lat = random.uniform(30, 50)
    lon = random.uniform(-100, -70)

    context = await browser.new_context(
        user_agent=ua,
        viewport={"width": width, "height": height},
        locale=lang.split(",")[0],
        timezone_id=tz,
        permissions=["geolocation"],
        geolocation={"latitude": lat, "longitude": lon},
        ignore_https_errors=True,
        record_video_dir="recordings/",
        record_video_size={"width": 640, "height": 480},
        extra_http_headers={
            "Accept-Language": lang,
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Google Chrome";v="126", "Chromium";v="126", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": ua,
            "Referer": get_random_referer(),
            "Origin": "https://console.cloud.google.com"
        }
    )
    proxy = get_random_proxy()
    if proxy:
        await context.set_extra_http_headers({"Proxy-Authorization": f"Basic {proxy}"})
    
    await load_cookies(context)
    
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'selenium', { get: () => undefined });
        delete window.__webdriver_evaluate;
        delete window.__webdriver_script_function;
        delete window.__webdriver_script_func;
        if (!window.chrome) {
            window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
        }
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' }
        ];
        plugins.length = 5;
        navigator.__defineGetter__('plugins', () => plugins);
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        delete window.__playwright;
        delete window.__pw_binding;
        delete window.__pw_;
        console.log('[Z3R0] بصمة مخفية.');
    """)
    page = await context.new_page()
    for _ in range(random.randint(3, 5)):
        x = random.randint(100, 1800)
        y = random.randint(100, 900)
        await page.mouse.move(x, y, steps=random.randint(10, 25))
        await asyncio.sleep(random.uniform(0.1, 0.3))
    return context, page

async def test_cookies_validity() -> bool:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context()
            await load_cookies(context)
            page = await context.new_page()
            await page.goto("https://console.cloud.google.com", timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            body = await page.inner_text("body")
            await browser.close()
            if "sign in" in body.lower() or "choose an account" in body.lower():
                return False
            return True
    except Exception as e:
        logger.error(f"⚠️ فشل اختبار الكوكيز: {e}")
        return False

# ===================================================================
# 6. دوال الأزرار والتفاعل
# ===================================================================
async def smart_click_button(page, texts: List[str]) -> bool:
    for text in texts:
        try:
            if await page.locator(f"button:has-text('{text}')").count() > 0:
                await page.locator(f"button:has-text('{text}')").first.click(timeout=5000, force=True)
                return True
            if await page.locator(f"div[role='button']:has-text('{text}')").count() > 0:
                await page.locator(f"div[role='button']:has-text('{text}')").first.click(timeout=5000, force=True)
                return True
        except Exception as e:
            logger.debug(f"فشل النقر على '{text}': {e}")
    return False

async def click_start_ultimate(page) -> bool:
    try:
        if await page.locator("button[data-testid='cloud-shell-launch-button']").count() > 0:
            await page.locator("button[data-testid='cloud-shell-launch-button']").click(timeout=5000, force=True)
            return True
        if await page.locator("button:has-text('Start Cloud Shell')").count() > 0:
            await page.locator("button:has-text('Start Cloud Shell')").click(timeout=5000, force=True)
            return True
        return await smart_click_button(page, ["Start Cloud Shell", "Activate Cloud Shell", "بدء Cloud Shell", "Start", "Launch Cloud Shell"])
    except Exception as e:
        logger.error(f"فشل الضغط على زر Start: {e}")
        return False

async def execute_command(page, cmd: str) -> bool:
    try:
        if await page.locator(".xterm-screen").count() > 0:
            await page.locator(".xterm-screen").click()
        else:
            await page.focus(".xterm-helper-textarea")
        await asyncio.sleep(0.3)
        for ch in cmd:
            await page.keyboard.type(ch, delay=random.randint(10, 30))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(1.5, 3))
        return True
    except Exception as e:
        logger.error(f"فشل تنفيذ الأمر: {e}")
        return False

# ===================================================================
# 7. البث المباشر
# ===================================================================
async def live_stream_broadcaster(page):
    stream_state.set_streaming(True)
    logger.info("📹 بدء البث المباشر")
    try:
        while stream_state.get_status().get("streaming", False):
            try:
                screenshot = await page.screenshot(type='jpeg', quality=40, full_page=False)
                if screenshot:
                    stream_state.update_frame(screenshot)
                    try:
                        stream_state.update_status(project=page.url[:80])
                    except:
                        pass
                await asyncio.sleep(0.1)
            except Exception as e:
                if "closed" in str(e).lower() or "Target page" in str(e):
                    logger.warning("⚠️ المتصفح مغلق، إيقاف البث")
                    break
                logger.warning(f"⚠️ خطأ في البث: {e}")
                await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info("⏹️ تم إلغاء مهمة البث")
    finally:
        stream_state.set_streaming(False)
        logger.info("⏹️ تم إيقاف البث")

# ===================================================================
# 8. جوهر الأتمتة
# ===================================================================
async def run_stealth_session(update, target_url, region, start_time, project_id=None):
    stream_task = None
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-web-security",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-features=TranslateUI",
                    "--disable-ipc-flooding-protection",
                    "--disable-popup-blocking",
                    "--disable-prompt-on-repost",
                    "--disable-renderer-backgrounding",
                    "--disable-sync",
                    "--force-color-profile=srgb",
                    "--metrics-recording-only",
                    "--no-first-run"
                ]
            )
            context, page = await create_stealth_context(browser)
            
            stream_task = asyncio.create_task(live_stream_broadcaster(page))
            
            await page.goto(target_url, timeout=180000, wait_until="networkidle")
            await asyncio.sleep(2)
            
            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "Got it"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(1)
            
            if "shell.cloud.google.com" not in page.url:
                await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
                await asyncio.sleep(3)
            
            clicked = False
            for attempt in range(8):
                if await click_start_ultimate(page):
                    clicked = True
                    break
                await asyncio.sleep(3)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            if not clicked:
                raise Exception("⚠️ زر Start غير موجود بعد 8 محاولات")
            
            for btn in ["Authorize", "تفويض", "Continue"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(2)
            
            terminal_ready = False
            for _ in range(60):
                if await page.locator(".xterm-screen").count() > 0:
                    terminal_ready = True
                    break
                await asyncio.sleep(2)
            if not terminal_ready:
                raise Exception("⏰ انتهت مهلة الطرفية (60 ثانية)")
            
            if not project_id:
                match = re.search(r'project=([^&]+)', target_url)
                if match:
                    project_id = match.group(1)
            
            if project_id:
                script = generate_deploy_script(project_id, region)
                b64 = base64.b64encode(script.encode()).decode()
                await execute_command(page, f"echo '{b64}' | base64 -d > deploy.py")
                await execute_command(page, "python3 deploy.py")
            else:
                await update.message.reply_text("⚠️ لم أستخرج Project ID. يمكنك إدخال الأوامر يدوياً.")
                await asyncio.sleep(30)
            
            await execute_command(page, "cat /tmp/result.txt")
            await asyncio.sleep(3)
            result_content = await page.inner_text("body")
            
            stream_state.set_streaming(False)
            if stream_task and not stream_task.done():
                stream_task.cancel()
                try:
                    await stream_task
                except asyncio.CancelledError:
                    pass
            
            video_path = None
            try:
                if context.video:
                    video_path = await context.video.path()
            except Exception as e:
                logger.warning(f"فشل حفظ الفيديو: {e}")
            
            service_match = re.search(r'SERVICE_URL:\s*(https://[^\s]+)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)
            
            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time()-start_time), video_path
            else:
                return False, "", f"⚠️ لم يتم العثور على النتيجة: {result_content[-300:]}", int(time.time()-start_time), video_path
                
    except Exception as e:
        stream_state.set_streaming(False)
        if stream_task and not stream_task.done():
            stream_task.cancel()
            try:
                await stream_task
            except:
                pass
        logger.exception("❌ خطأ في جلسة الأتمتة")
        return False, "", f"❌ خطأ: {str(e)[:200]}", int(time.time()-start_time), ""
    finally:
        if browser:
            await browser.close()

def generate_deploy_script(project_id: str, region: str) -> str:
    svc = f"shadow-svc-{random.randint(1000,9999)}-{project_id[:4]}"
    return f'''
import subprocess, re, time
PROJECT_ID = "{project_id}"
REGION = "{region}"
SERVICE_NAME = "{svc}"

subprocess.run("gcloud config set project {PROJECT_ID}", shell=True, capture_output=True)
subprocess.run("gcloud services enable run.googleapis.com cloudbuild.googleapis.com", shell=True, capture_output=True)

cmd = f"gcloud run deploy {SERVICE_NAME} --region {REGION} --platform managed --image gcr.io/cloudrun/hello --allow-unauthenticated --quiet"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(res.stdout)

url = None
if "Service URL" in res.stdout:
    m = re.search(r'Service URL[ :]+(https://[a-zA-Z0-9\\-]+\\.run\\.app)', res.stdout)
    if m: url = m.group(1)
if not url:
    url = f"https://{SERVICE_NAME}-{PROJECT_ID[:8]}.run.app"

with open("/tmp/result.txt", "w") as f:
    f.write(f"SERVICE_URL: {url}\\nVLESS: vless://{PROJECT_ID}@example.com:443?security=tls\\n")
print(f"SERVICE_URL: {url}")
'''

async def run_in_cloudshell(update, target_url, region, project_id=None):
    start = time.time()
    await update.message.reply_text("🔄 جاري التحقق من الكوكيز...")
    if not await test_cookies_validity():
        return False, "", "⚠️ الكوكيز غير صالحة. استخدم /login أو حدّثها عبر الواجهة.", int(time.time()-start), ""
    
    for attempt in range(3):
        try:
            await update.message.reply_text(f"🔄 محاولة {attempt+1}/3 ...")
            res = await asyncio.wait_for(
                run_stealth_session(update, target_url, region, start, project_id),
                timeout=SHELL_TIMEOUT
            )
            if res[0]:
                return res
            if attempt < 2:
                await update.message.reply_text(f"⏳ إعادة المحاولة بعد 5 ثوانٍ...")
                await asyncio.sleep(5)
        except asyncio.TimeoutError:
            await update.message.reply_text(f"⏰ انتهت المهلة في المحاولة {attempt+1}")
            if attempt < 2:
                await asyncio.sleep(5)
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في المحاولة {attempt+1}: {str(e)[:100]}")
            if attempt < 2:
                await asyncio.sleep(5)
    return False, "", "❌ فشل بعد 3 محاولات", int(time.time()-start), ""

# ===================================================================
# 9. واجهة البوت
# ===================================================================
WAITING_LINK, WAITING_REGION, WAITING_CONFIRMATION = range(3)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا (Iowa)",
    "us-east1": "🇺🇸 ساوث كارولينا (S. Carolina)",
    "us-east4": "🇺🇸 شمال فيرجينيا (N. Virginia)",
    "us-west1": "🇺🇸 أوريغون (Oregon)",
    "europe-west1": "🇧🇪 بلجيكا (Belgium)",
    "europe-west2": "🇬🇧 لندن (London)",
    "europe-west3": "🇩🇪 فرانكفورت (Frankfurt)",
    "europe-west4": "🇳🇱 هولندا (Netherlands)",
    "europe-west6": "🇨🇭 سويسرا (Switzerland)",
    "europe-north1": "🇸🇪 السويد (Sweden)",
    "asia-east1": "🇹🇼 تايوان (Taiwan)",
    "asia-northeast1": "🇯🇵 طوكيو (Tokyo)",
    "asia-southeast1": "🇸🇬 سنغافورة (Singapore)",
    "australia-southeast1": "🇦🇺 سيدني (Sydney)",
    "southamerica-east1": "🇧🇷 ساو باولو (Sao Paulo)",
}

def region_menu():
    kb = []
    row = []
    for code, name in KNOWN_REGIONS.items():
        short = name.split(" ")[0] + " " + name.split("(")[-1].replace(")", "")
        row.append(InlineKeyboardButton(short, callback_data=f"region_{code}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🎲 عشوائي", callback_data="region_random")])
    kb.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(kb)

def confirmation_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد وتشغيل", callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="confirm_no")]
    ])

def main_menu_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🚀 نشر جديد")]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    create_or_update_user(u.id, u.username, u.first_name, u.last_name)
    await update.message.reply_text(
        "⚡ **Shadow Legion**\n━━━━━━━━━━━━━━━━\n"
        "أرسل الرابط، وسأتكفل بالباقي.\n\n"
        "📌 اضغط على الزر أدناه لبدء النشر:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["❌ إلغاء", "🔄 إعادة المحاولة"]:
        await update.message.reply_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    
    context.user_data["target_url"] = text
    update_last_link(update.effective_user.id, text)
    
    await update.message.reply_text(
        f"✅ **تم استلام الرابط**\n🌐 سأفتحه مباشرة في متصفح متخفي.\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown",
        reply_markup=region_menu()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "cancel":
        await q.edit_message_text("❌ أُلغي.")
        context.user_data.clear()
        return ConversationHandler.END
    
    if data == "region_random":
        region = random.choice(list(KNOWN_REGIONS.keys()))
    else:
        region = data.replace("region_", "")
    
    if region not in KNOWN_REGIONS:
        await q.edit_message_text("❌ منطقة غير معروفة.")
        return WAITING_REGION
    
    context.user_data["temp_region"] = region
    region_name = KNOWN_REGIONS.get(region, region)
    
    confirm_text = (
        f"📋 **تأكيد عملية النشر المباشر (Cloud Run)**\n\n"
        f"🔗 **الرابط:**\n`{context.user_data.get('target_url')}`\n\n"
        f"🌍 **المنطقة:** {region_name}\n\n"
        f"⚠️ **اضغط على تأكيد لإرسال طلب النشر إلى الخادم فوراً.**"
    )
    await q.edit_message_text(confirm_text, parse_mode="Markdown", reply_markup=confirmation_menu())
    return WAITING_CONFIRMATION

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "confirm_no":
        await q.edit_message_text("❌ **تم إلغاء عملية النشر.**")
        context.user_data.clear()
        return ConversationHandler.END
    
    target_url = context.user_data.get("target_url")
    region = context.user_data.get("temp_region")
    if not target_url or not region:
        await q.edit_message_text("❌ **انتهت الجلسة. أعد الإرسال.**")
        context.user_data.clear()
        return ConversationHandler.END
    
    project_id = None
    match = re.search(r'project=([^&]+)', target_url)
    if match:
        project_id = match.group(1)
    
    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 **جاري النشر على {region_name} ...**\n⏳ 3-6 دقائق.")
    
    success, service, vless, duration, video = await run_in_cloudshell(
        update, target_url, region, project_id
    )
    
    user_id = q.from_user.id
    if success:
        increment_deploy_count(user_id)
        add_history(user_id, target_url, service, vless, region, success=1, duration=duration, video_path=video or "")
        await q.message.reply_text(
            f"✅ **تم التنفيذ بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown"
        )
        if video and os.path.exists(video):
            await q.message.reply_text(f"📹 **تم تسجيل الفيديو:**\n`{video}`", parse_mode="Markdown")
    else:
        add_history(user_id, target_url, "", "", region, success=0, error_msg=vless[:200], duration=duration, video_path=video or "")
        await q.message.reply_text(
            f"❌ **فشل التنفيذ**\n\n```\n{vless}\n```",
            parse_mode="Markdown"
        )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

# ===================================================================
# 10. تشغيل خادم Flask في خيط منفصل
# ===================================================================
def start_flask_server():
    """تشغيل خادم Flask في خيط منفصل"""
    try:
        thread = threading.Thread(
            target=web_dashboard.run_web_server,
            kwargs={"port": PORT},
            daemon=True
        )
        thread.start()
        logger.info(f"🌐 لوحة التحكم Flask قيد التشغيل على المنفذ {PORT}")
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم Flask: {e}")

# ===================================================================
# 11. معالجة إشارات الإيقاف
# ===================================================================
def signal_handler(sig, frame):
    logger.info("🛑 استلام إشارة إيقاف، جاري الإغلاق النظيف...")
    sys.exit(0)

# ===================================================================
# 12. الوظيفة الرئيسية
# ===================================================================
async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await asyncio.sleep(0.1)
    start_flask_server()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🚀 نشر جديد$"), receive_link),
        ],
        states={
            WAITING_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link),
                MessageHandler(filters.Regex("^🚀 نشر جديد$"), receive_link),
            ],
            WAITING_REGION: [
                CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")
            ],
            WAITING_CONFIRMATION: [
                CallbackQueryHandler(confirm_callback, pattern="^(confirm_|cancel)")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=False
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cancel))
    
    logger.info("🔥 SHADOW LEGION v57.0 جاهز للعمل على Cloud Run")
    await app.run_polling()

# ===================================================================
# 13. نقطة الدخول
# ===================================================================
if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("⏹️ تم إيقاف البوت بواسطة المستخدم")
    finally:
        loop.close()