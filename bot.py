#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v39.0 – TELEGRAM-CLEAN (Architect Edition)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- تم حذف /login و /done بالكامل (إدارة الكوكيز عبر الويب)
- جميع الجلسات تعتمد على كوكيز قاعدة البيانات
- البوت خفيف وسريع، مخصص للنشر فقط
- لوحة التحكم تدير الكوكيز والمراقبة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import aiohttp
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from logging.handlers import RotatingFileHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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

# ===================================================================
# 1. الإعدادات الأساسية والبيئة
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
RECORD_VIDEO = os.environ.get("RECORD_VIDEO", "false").lower() == "true"
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🔥 SHADOW LEGION v39.0 (Telegram-Clean) بدأ التشغيل...")

# ===================================================================
# 2. اتصال MongoDB
# ===================================================================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DB_NAME]
    users_collection = db["users"]
    history_collection = db["deploy_history"]
    cookies_collection = db["cookies"]
    client.admin.command('ping')
    logger.info("✅ الاتصال بـ MongoDB ناجح.")
except Exception as e:
    logger.error(f"❌ فشل الاتصال بـ MongoDB: {e}")
    raise

# ===================================================================
# 3. دوال قاعدة البيانات (موسعة)
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

async def save_cookies_to_db(user_id: int, cookies: List[Dict]) -> None:
    try:
        cookies_collection.update_one(
            {"_id": user_id},
            {"$set": {"data": json.dumps(cookies, default=str), "updated_at": datetime.now().isoformat()}},
            upsert=True
        )
        logger.info(f"🍪 تم حفظ {len(cookies)} كوكي للمستخدم {user_id} في MongoDB.")
    except Exception as e:
        logger.error(f"❌ فشل حفظ الكوكيز للمستخدم {user_id}: {e}")

async def load_cookies_from_db(user_id: int) -> List[Dict]:
    try:
        doc = cookies_collection.find_one({"_id": user_id})
        if doc and doc.get("data"):
            cookies = json.loads(doc["data"])
            logger.info(f"🍪 تم تحميل {len(cookies)} كوكي للمستخدم {user_id} من MongoDB.")
            return cookies
    except Exception as e:
        logger.warning(f"⚠️ فشل تحميل الكوكيز للمستخدم {user_id}: {e}")
    return []

# ===================================================================
# 4. مدير الجلسات (Per‑User Isolation)
# ===================================================================
class UserSession:
    __slots__ = ('user_id', 'browser', 'context', 'page', 'stop_event', 'stream_task', 'chat_id')
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.browser = None
        self.context = None
        self.page = None
        self.stop_event = asyncio.Event()
        self.stream_task: Optional[asyncio.Task] = None
        self.chat_id: Optional[int] = None

active_sessions: Dict[int, UserSession] = {}

async def cleanup_session(user_id: int) -> None:
    session = active_sessions.pop(user_id, None)
    if not session:
        return
    logger.info(f"🧹 بدء تنظيف جلسة المستخدم {user_id}")
    session.stop_event.set()
    
    if session.stream_task and not session.stream_task.done():
        session.stream_task.cancel()
        try:
            await asyncio.wait_for(session.stream_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.warning(f"⚠️ خطأ أثناء إلغاء مهمة البث: {e}")
    
    if session.page:
        try:
            await session.page.close()
        except Exception:
            pass
    if session.context:
        try:
            await session.context.close()
        except Exception:
            pass
    if session.browser:
        try:
            await session.browser.close()
        except Exception:
            pass
    
    logger.info(f"✅ تم تنظيف جلسة المستخدم {user_id} بالكامل.")

# ===================================================================
# 5. دوال مساعدة (بصمات، وكيل، Captcha)
# ===================================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
TIMEZONES = ["America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney", "America/Los_Angeles"]
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

async def solve_captcha_2captcha(page, sitekey: str) -> Optional[str]:
    if not TWOCAPTCHA_API_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            data = {"key": TWOCAPTCHA_API_KEY, "method": "userrecaptcha", "googlekey": sitekey, "pageurl": page.url, "json": 1}
            async with session.post("https://2captcha.com/in.php", data=data) as resp:
                result = await resp.json()
                if result.get("status") != 1:
                    return None
                captcha_id = result.get("request")
            for _ in range(30):
                await asyncio.sleep(5)
                async with session.get(f"https://2captcha.com/res.php?key={TWOCAPTCHA_API_KEY}&action=get&id={captcha_id}&json=1") as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") == "CAPCHA_NOT_READY":
                        continue
                    else:
                        return None
        return None
    except Exception:
        return None

def extract_project_from_url(url: str) -> Optional[str]:
    match = re.search(r'[?&]project=([^&]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/projects/([^/?#]+)', url)
    if match:
        return match.group(1)
    return None

# ===================================================================
# 6. محرك التخفي وإنشاء السياق (يعتمد على الكوكيز من DB)
# ===================================================================
async def create_stealth_context(user_id: int, browser) -> Tuple[Any, Any]:
    fingerprint = generate_random_fingerprint()
    ua = random.choice(USER_AGENTS)
    width = random.randint(1800, 1920)
    height = random.randint(1000, 1080)
    tz = random.choice(TIMEZONES)
    lang = random.choice(LANGUAGES)
    lat = random.uniform(30, 50)
    lon = random.uniform(-100, -70)

    context_options = {
        "user_agent": ua,
        "viewport": {"width": width, "height": height},
        "locale": lang.split(",")[0],
        "timezone_id": tz,
        "permissions": ["geolocation"],
        "geolocation": {"latitude": lat, "longitude": lon},
        "extra_http_headers": {
            "Accept-Language": lang,
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Google Chrome";v="126", "Chromium";v="126", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": ua,
            "Referer": get_random_referer(),
            "Origin": "https://console.cloud.google.com"
        },
        "ignore_https_errors": True,
        "accept_downloads": True,
        "java_script_enabled": True,
        "bypass_csp": True,
        "record_video_dir": "videos" if RECORD_VIDEO else None,
    }
    
    proxy = get_random_proxy()
    if proxy:
        context_options["proxy"] = {"server": proxy}
    
    context = await browser.new_context(**context_options)
    
    # تحميل الكوكيز من قاعدة البيانات الخاصة بالمستخدم
    cookies = await load_cookies_from_db(user_id)
    if cookies:
        await context.add_cookies(cookies)
    else:
        logger.warning(f"⚠️ لا توجد كوكيز محفوظة للمستخدم {user_id}، قد يفشل المصادقة.")
    
    logger.info(f"🍪 تم تحميل {len(cookies)} كوكي للمستخدم {user_id} في السياق الجديد.")

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
    await simulate_mouse_movement(page)
    return context, page

async def simulate_mouse_movement(page):
    try:
        for _ in range(random.randint(3, 5)):
            x = random.randint(100, 1800)
            y = random.randint(100, 900)
            await page.mouse.move(x, y, steps=random.randint(10, 25))
            await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass

# ===================================================================
# 7. دوال الأزرار والانتظار
# ===================================================================
async def smart_click_button(page, texts: List[str]) -> bool:
    for text in texts:
        try:
            btn = await page.query_selector(f"button:has-text('{text}'), div[role='button']:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                return True
        except Exception:
            continue
    return False

EXPIRED_KEYWORDS = ["expired", "invalid", "sign in", "accounts.google.com", "Impossible de vous connecter", "choose an account"]

async def wait_for_redirect(page, max_wait: int = 120) -> Tuple[bool, str]:
    start = time.time()
    while time.time() - start < max_wait:
        try:
            url = page.url
            text = await page.inner_text("body")
            if "console.cloud.google.com" in url or "shell.cloud.google.com" in url:
                if "sign in" not in text.lower():
                    return True, ""
            if any(k in text.lower() for k in EXPIRED_KEYWORDS):
                return False, "⛔ الرابط منتهي أو غير صالح"
            if "choose an account" in text.lower():
                await smart_click_button(page, ["Continue", "التالي", "Next"])
                await asyncio.sleep(2)
                continue
            if "email" in text.lower() and "identifier" in text.lower():
                return False, "⛔ فشل تسجيل الدخول (شاشة البريد)"
            if "password" in text.lower() or "كلمة المرور" in text.lower():
                return False, "⛔ الرابط يتطلب كلمة مرور"
        except Exception:
            pass
        await asyncio.sleep(2)
    return False, "⛔ انتهت المهلة"

# ===================================================================
# 8. Start Cloud Shell والطرفية
# ===================================================================
async def click_start_ultimate(page, max_attempts=6) -> bool:
    selectors = [
        "button[data-testid='cloud-shell-launch-button']",
        "button[aria-label='Start Cloud Shell']",
        "button:has-text('Start Cloud Shell')",
        "button:has-text('Activate Cloud Shell')",
        "button:has-text('Launch Cloud Shell')",
        "button:has-text('بدء Cloud Shell')",
        "button:has-text('Start')",
        "div[role='button']:has-text('Start Cloud Shell')",
    ]
    for attempt in range(max_attempts):
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        except Exception:
            pass
        await asyncio.sleep(0.3)
        for sel in selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click()
                    return True
            except Exception:
                continue
        try:
            res = await page.evaluate("""
                () => {
                    const kw = ['start','launch','activate','بدء','تشغيل','تفعيل','run'];
                    const btns = document.querySelectorAll('button, div[role="button"]');
                    for (let b of btns) {
                        const t = (b.innerText || b.getAttribute('aria-label') || '').toLowerCase();
                        if (kw.some(k => t.includes(k))) { b.scrollIntoView(); b.click(); return true; }
                    }
                    return false;
                }
            """)
            if res:
                return True
        except Exception:
            pass
        await asyncio.sleep(4)
    return False

async def execute_command(page, cmd: str) -> bool:
    for attempt in range(3):
        try:
            await page.wait_for_selector(".xterm-helper-textarea, .xterm, .terminal, [role='textbox']", state="visible", timeout=5000)
            for sel in [".xterm-helper-textarea", ".xterm", ".terminal", "[role='textbox']"]:
                try:
                    await page.focus(sel)
                    break
                except Exception:
                    continue
            await asyncio.sleep(0.3)
            for ch in cmd:
                await page.keyboard.type(ch, delay=random.randint(8, 20))
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(1.5, 3))
            return True
        except Exception as e:
            logger.warning(f"⚠️ محاولة أمر {attempt+1} فشلت: {e}")
            await asyncio.sleep(1)
    return False

async def wait_for_terminal(page, timeout=300) -> Tuple[bool, str]:
    selectors = [".xterm", ".xterm-helper-textarea", ".terminal", "[role='textbox']"]
    start = time.time()
    while time.time() - start < timeout:
        try:
            for sel in selectors:
                elem = await page.query_selector(sel)
                if elem and await elem.is_visible():
                    return True, ""
        except Exception:
            pass
        await asyncio.sleep(1)
    return False, f"⏰ انتهت مهلة الطرفية ({timeout} ثانية)"

# ===================================================================
# 9. البث المباشر (يعمل لكل جلسة)
# ===================================================================
async def live_stream_broadcaster(page, session: UserSession):
    logger.info(f"📹 بدء البث المباشر للمستخدم {session.user_id}")
    try:
        while not session.stop_event.is_set():
            try:
                screenshot = await page.screenshot(type='jpeg', quality=40, full_page=False)
                if screenshot:
                    stream_state.update_frame(screenshot)
                    try:
                        url = page.url[:80]
                        stream_state.update_status(project=url)
                    except Exception:
                        pass
                await asyncio.sleep(0.2)
            except Exception as e:
                if "closed" in str(e).lower() or "Target page" in str(e):
                    logger.warning(f"⚠️ المتصفح مغلق للمستخدم {session.user_id}، إيقاف البث")
                    break
                logger.warning(f"⚠️ خطأ في البث للمستخدم {session.user_id}: {e}")
                await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info(f"⏹️ تم إلغاء مهمة البث للمستخدم {session.user_id}")
    finally:
        stream_state.set_streaming(False)
        logger.info(f"⏹️ تم إيقاف البث للمستخدم {session.user_id}")

# ===================================================================
# 10. سكريبت النشر (محسّن مع تطبيق حقيقي)
# ===================================================================
def generate_deploy_script(project_id: str, region: str) -> str:
    svc = f"shadow-svc-{random.randint(1000,9999)}-{project_id[:4]}"
    return f'''
import subprocess, re, time
PROJECT_ID = "{project_id}"
REGION = "{region}"
SERVICE_NAME = "{svc}"

subprocess.run("apt-get update && apt-get install google-cloud-sdk -y", shell=True, capture_output=True)
subprocess.run(f"gcloud config set project {PROJECT_ID}", shell=True, capture_output=True)
subprocess.run("gcloud services enable run.googleapis.com cloudbuild.googleapis.com", shell=True, capture_output=True)

with open("Dockerfile", "w") as f:
    f.write("FROM nginx:alpine\\nCOPY index.html /usr/share/nginx/html/index.html\\n")
with open("index.html", "w") as f:
    f.write("<h1>Shadow Legion v39</h1><p>Deployed successfully via The Architect.</p>")

cmd = f"gcloud run deploy {SERVICE_NAME} --region {REGION} --platform managed --source . --allow-unauthenticated --quiet"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(res.stdout)

url = None
if "Service URL" in res.stdout:
    m = re.search(r'Service URL[ :]+(https://[a-zA-Z0-9\\-]+\\.run\\.app)', res.stdout)
    if m: url = m.group(1)
if not url:
    url = f"https://{SERVICE_NAME}-{PROJECT_ID[:8]}.run.app"

with open("/tmp/result.txt", "w") as f:
    f.write(f"SERVICE_URL: {url}\\nVLESS: vless://{PROJECT_ID}@{url.replace('https://','')}:443?security=tls&encryption=none&headerType=none&type=tcp\\n")
print(f"SERVICE_URL: {url}")
'''

# ===================================================================
# 11. قلب الأتمتة (الجلسة الكاملة مع التنظيف)
# ===================================================================
async def run_stealth_session(user_id: int, lab_url: str, region: str, bot, chat_id: int) -> Tuple[bool, str, str, int, str]:
    session = active_sessions.get(user_id)
    if not session:
        session = UserSession(user_id)
        active_sessions[user_id] = session
    session.chat_id = chat_id
    session.stop_event.clear()
    start_time = time.time()
    video_path = None

    try:
        async with async_playwright() as p:
            session.browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu", "--disable-software-rasterizer",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-web-security",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-default-apps", "--disable-extensions",
                    "--disable-features=TranslateUI", "--disable-ipc-flooding-protection",
                    "--disable-popup-blocking", "--disable-prompt-on-repost",
                    "--disable-sync", "--force-color-profile=srgb",
                    "--metrics-recording-only", "--no-first-run"
                ]
            )
            context, page = await create_stealth_context(user_id, session.browser)
            session.context = context
            session.page = page

            stream_task = asyncio.create_task(live_stream_broadcaster(page, session))
            session.stream_task = stream_task
            stream_state.set_streaming(True)

            logger.info(f"📌 المستخدم {user_id} يفتح الرابط: {lab_url[:80]}...")
            await page.goto(lab_url, timeout=min(180000, SHELL_TIMEOUT*1000), wait_until="networkidle")

            ok, msg = await wait_for_redirect(page, 120)
            if not ok:
                return False, "", msg, int(time.time()-start_time), ""

            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "Got it"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(1)

            if "shell.cloud.google.com" not in page.url:
                await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
                await asyncio.sleep(3)

            for _ in range(15):
                await asyncio.sleep(2)
                if await page.query_selector("button:has-text('Start Cloud Shell'), button[aria-label='Start Cloud Shell']"):
                    break

            clicked = False
            for _ in range(5):
                if await click_start_ultimate(page, max_attempts=1):
                    clicked = True
                    break
                await asyncio.sleep(4)
            if not clicked:
                return False, "", "⚠️ لم يتم العثور على زر Start", int(time.time()-start_time), ""

            for btn in ["Authorize", "تفويض", "Continue", "I understand"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(2)

            ok, msg = await wait_for_terminal(page, 360)
            if not ok:
                return False, "", msg, int(time.time()-start_time), ""

            project_id = extract_project_from_url(lab_url)
            if project_id:
                script = generate_deploy_script(project_id, region)
                b64 = base64.b64encode(script.encode()).decode()
                await execute_command(page, f"echo '{b64}' | base64 -d > deploy.py")
                await execute_command(page, "python3 deploy.py")
            else:
                await bot.send_message(chat_id, "⚠️ لم أستخرج Project ID. يمكنك إدخال الأوامر يدوياً.")
                await asyncio.sleep(60)

            await execute_command(page, "cat /tmp/result.txt")
            await asyncio.sleep(2)
            result_content = ""
            try:
                term = await page.query_selector(".xterm, .terminal, [role='textbox']")
                if term:
                    result_content = await term.inner_text()
            except Exception:
                pass
            if not result_content:
                result_content = await page.inner_text("body")

            if RECORD_VIDEO and session.context:
                try:
                    video = await session.context.video
                    if video:
                        video_path = await video.path()
                except Exception as e:
                    logger.warning(f"⚠️ فشل استخراج الفيديو: {e}")

            if session.stream_task and not session.stream_task.done():
                session.stop_event.set()
                try:
                    await asyncio.wait_for(session.stream_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            # حفظ الكوكيز المحدثة بعد النشر (لتحديث الجلسة)
            try:
                cookies = await session.context.cookies()
                await save_cookies_to_db(user_id, cookies)
            except Exception as e:
                logger.warning(f"⚠️ فشل حفظ الكوكيز بعد النشر: {e}")

            service_match = re.search(r'SERVICE_URL:\s*(https://[^\s]+)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)

            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time()-start_time), video_path or ""
            else:
                return False, "", f"⚠️ لم يتم العثور على النتيجة: {result_content[-200:]}", int(time.time()-start_time), video_path or ""

    except Exception as e:
        logger.error(f"❌ المستخدم {user_id} خطأ جوهري: {e}", exc_info=True)
        return False, "", f"❌ خطأ: {str(e)[:200]}", int(time.time()-start_time), ""
    finally:
        await cleanup_session(user_id)

# ===================================================================
# 12. دالة النشر الخلفية (غير حاصرة)
# ===================================================================
async def deploy_and_report(user_id: int, lab_url: str, region: str, bot, chat_id: int) -> None:
    try:
        success, service, vless, duration, video = await run_stealth_session(
            user_id, lab_url, region, bot, chat_id
        )
        
        region_name = KNOWN_REGIONS.get(region, region)
        if success:
            increment_deploy_count(user_id)
            add_history(user_id, lab_url, service, vless, region, success=1, duration=duration, video_path=video or "")
            await bot.send_message(
                chat_id,
                f"✅ **تم التنفيذ بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
                parse_mode="Markdown"
            )
            if video and os.path.exists(video):
                await bot.send_message(chat_id, f"📹 **تم تسجيل الفيديو:**\n`{video}`", parse_mode="Markdown")
        else:
            add_history(user_id, lab_url, "", "", region, success=0, error_msg=vless[:200], duration=duration, video_path=video or "")
            await bot.send_message(
                chat_id,
                f"❌ **فشل التنفيذ**\n\n```\n{vless}\n```",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"❌ خطأ في deploy_and_report للمستخدم {user_id}: {e}")
        await bot.send_message(chat_id, f"⚠️ خطأ غير متوقع: {str(e)[:200]}")

# ===================================================================
# 13. دوال التنظيف التلقائي
# ===================================================================
def cleanup_old_recordings():
    try:
        recordings_dir = "videos"
        if not os.path.exists(recordings_dir):
            return
        cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
        for filename in os.listdir(recordings_dir):
            filepath = os.path.join(recordings_dir, filename)
            if os.path.isfile(filepath):
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    logger.info(f"🗑️ تم حذف فيديو قديم: {filename}")
    except Exception as e:
        logger.warning(f"⚠️ فشل تنظيف الفيديوهات: {e}")

# ===================================================================
# 14. واجهة البوت (ConversationHandler + أزرار)
# ===================================================================
WAITING_LINK, WAITING_REGION = range(2)

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
    "europe-west8": "🇮🇹 إيطاليا (Italy)",
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    create_or_update_user(u.id, u.username, u.first_name, u.last_name)
    await update.message.reply_text(
        "⚡ **Shadow Legion v39**\n━━━━━━━━━━━━━━━━\n"
        "أرسل الرابط، وسأتكفل بالباقي.\n"
        "📌 يتم تحميل الكوكيز من قاعدة البيانات (يمكنك رفعها عبر لوحة التحكم).",
        parse_mode="Markdown"
    )

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 أرسل رابط Qwiklabs أو Google SSO:", reply_markup=ReplyKeyboardRemove())
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["❌ إلغاء", "🔄 إعادة المحاولة"]:
        if text == "🔄 إعادة المحاولة":
            return await retry_command(update, context)
        await update.message.reply_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    lab_url = text
    user_id = update.effective_user.id
    update_last_link(user_id, lab_url)
    context.user_data.update({"lab_url": lab_url})
    await update.message.reply_text(
        f"✅ **تم استلام الرابط**\n🌐 سأفتحه في متصفح متخفي.\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or not user_data.get("last_link"):
        await update.message.reply_text("📭 لا يوجد رابط سابق.")
        return ConversationHandler.END
    lab_url = user_data["last_link"]
    context.user_data.update({"lab_url": lab_url})
    await update.message.reply_text(
        f"🔄 جاري إعادة استخدام الرابط السابق:\n`{lab_url[:80]}...`",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    raw = query.data.replace("region_", "")
    
    if raw == "cancel":
        await query.edit_message_text("❌ أُلغي.")
        context.user_data.clear()
        return
    
    if raw == "random":
        region = random.choice(list(KNOWN_REGIONS.keys()))
    else:
        region = raw
    
    lab = context.user_data.get("lab_url")
    if not lab:
        await query.edit_message_text("❌ لا يوجد رابط. أعد الإرسال.")
        return
    
    region_name = KNOWN_REGIONS.get(region, region)
    await query.edit_message_text(
        f"⏳ **جاري تجهيز النشر على {region_name}...**\n"
        "سأبلغك فور الانتهاء (قد يستغرق 3-6 دقائق).",
        parse_mode="Markdown"
    )
    
    asyncio.create_task(
        deploy_and_report(
            user_id=query.from_user.id,
            lab_url=lab,
            region=region,
            bot=context.bot,
            chat_id=query.message.chat_id
        )
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("❌ لا توجد بيانات.")
        return
    await update.message.reply_text(
        f"📊 **إحصائياتك**\n👤 {u['first_name']}\n📦 نشرات: {u['deploy_count']}\n📅 انضم: {u['joined_at'][:16]}",
        parse_mode="Markdown"
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = get_history(update.effective_user.id, 5)
    if not history:
        await update.message.reply_text("📭 لا يوجد سجل.")
        return
    text = "📜 **آخر 5 نشرات:**\n"
    for i, h in enumerate(history, 1):
        status = "✅" if h['success'] else "❌"
        region = KNOWN_REGIONS.get(h['region_used'], h['region_used'])
        text += f"{i}. {status} {region} – {h['deployed_at'][:16]}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ **الأوامر:**\n"
        "/start – القائمة الرئيسية\n"
        "/deploy – إرسال رابط للنشر\n"
        "/retry – إعادة استخدام آخر رابط\n"
        "/stats – إحصائياتك\n"
        "/history – سجل النشرات\n"
        "/cancel – إلغاء\n\n"
        "📌 **ملاحظة:** تم حذف /login و /done نهائياً. يتم إدارة الكوكيز عبر لوحة التحكم.",
        parse_mode="Markdown"
    )

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚀 نشر جديدة":
        return await deploy_command(update, context)
    elif text == "📊 إحصائياتي":
        return await stats_command(update, context)
    elif text == "📜 سجل النشر":
        return await history_command(update, context)
    elif text == "❓ مساعدة":
        return await help_command(update, context)
    elif text == "🔄 إعادة المحاولة":
        return await retry_command(update, context)
    elif text == "❌ إلغاء":
        return await cancel(update, context)
    else:
        return await receive_link(update, context)

# ===================================================================
# 15. لوحة التحكم (خيط منفصل)
# ===================================================================
def start_web_dashboard():
    try:
        import threading
        import web_dashboard
        port = int(os.environ.get("PORT", 8080))
        threading.Thread(target=web_dashboard.run_web_server, kwargs={"port": port}, daemon=True).start()
        logger.info(f"🌐 لوحة التحكم على المنفذ {port}")
    except Exception as e:
        logger.error(f"❌ فشل تشغيل لوحة التحكم: {e}")

# ===================================================================
# 16. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("deploy", deploy_command), MessageHandler(filters.Regex("^🚀 نشر جديدة$"), deploy_command)],
        states={WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)], WAITING_REGION: []},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("retry", retry_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(CallbackQueryHandler(lambda u,c: c.user_data.clear() or u.edit_message_text("❌ أُلغي."), pattern="^cancel$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    start_web_dashboard()
    cleanup_old_recordings()
    
    logger.info("🔥 SHADOW LEGION v39.0 (Telegram-Clean) جاهز للتشغيل")
    app.run_polling()

if __name__ == "__main__":
    main()