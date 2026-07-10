#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v30.0 – FINAL_STABLE_FAST
- بث سريع (جودة 40%، 10 إطارات/ثانية)
- إدارة آمنة للمتصفح (async with)
- MongoDB
- إعادة محاولة ذكية
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from logging.handlers import RotatingFileHandler
import aiohttp

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
# الإعدادات الأساسية
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
COOKIES_FILE = "cookies_live.json"
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v30.0 (Fast Stable) بدأ التشغيل...")

# ===================================================================
# MongoDB
# ===================================================================
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB_NAME]
users_collection = db["users"]
history_collection = db["deploy_history"]

# ===================================================================
# دوال قاعدة البيانات (مختصرة)
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
    docs = history_collection.find({"user_id": user_id}, sort=[("deployed_at", -1)], limit=limit)
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
# دوال مساعدة (تمويه، استخراج)
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
    except:
        return None

def smart_extract(link: str) -> Dict[str, Optional[str]]:
    link = link.strip()
    decoded = link
    for _ in range(5):
        decoded = urllib.parse.unquote(decoded)
    
    project = None
    token = None
    email = None
    
    continue_match = re.search(r'[?&]continue=([^&]+)', decoded)
    if continue_match:
        continue_url = urllib.parse.unquote(continue_match.group(1))
        project_match = re.search(r'[?&]project=([^&]+)', continue_url)
        if project_match:
            project = project_match.group(1)
        else:
            project_match = re.search(r'/projects/([^/?#]+)', continue_url)
            if project_match:
                project = project_match.group(1)
    
    if not project:
        parsed = urllib.parse.urlparse(decoded)
        params = urllib.parse.parse_qs(parsed.query)
        project = params.get('project', [None])[0] or params.get('projectId', [None])[0] or params.get('id', [None])[0]
    
    if '#' in decoded:
        fragment = decoded.split('#')[1] if len(decoded.split('#')) > 1 else ''
        email_match = re.search(r'[?&]?Email=([^&]+)', fragment)
        if email_match:
            email = urllib.parse.unquote(email_match.group(1))
    
    if not email:
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        all_emails = re.findall(email_pattern, decoded)
        if all_emails:
            for em in all_emails:
                if 'qwiklabs' in em or 'student' in em:
                    email = em
                    break
            if not email:
                email = all_emails[0]
    
    if not token:
        parsed = urllib.parse.urlparse(decoded)
        params = urllib.parse.parse_qs(parsed.query)
        token = params.get('token', [None])[0] or params.get('display_token', [None])[0] or params.get('auth_token', [None])[0]
    
    if project:
        project = project.strip('/"\'')
    if token:
        token = token.strip('/"\'')
    if email:
        email = email.strip('/"\'')
    
    return {"project_id": project, "token": token, "email": email}

# ===================================================================
# نظام الجلسة الحية (Login / Done)
# ===================================================================
login_event = asyncio.Event()
login_context = None
login_browser = None

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global login_context, login_browser, login_event
    try:
        login_event.clear()
        await update.message.reply_text(
            "🔐 **جاري فتح متصفح متخفي لتسجيل الدخول...**\n"
            "قم بتسجيل الدخول إلى Google ثم ارسل `/done`.",
            parse_mode="Markdown"
        )
        async with async_playwright() as p:
            login_browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled", "--disable-gpu"]
            )
            login_context = await login_browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id=random.choice(TIMEZONES)
            )
            page = await login_context.new_page()
            await page.goto("https://console.cloud.google.com", wait_until="networkidle")
            await update.message.reply_text(
                "🌐 **المتصفح المتخفي مفتوح.**\n"
                "سجل الدخول ثم ارسل `/done`.",
                parse_mode="Markdown"
            )
            await login_event.wait()
    except Exception as e:
        logger.error(f"فشل تسجيل الدخول: {e}")
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")
        if login_browser:
            await login_browser.close()
            login_browser = None
            login_context = None

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global login_context, login_browser, login_event
    try:
        if login_context is None:
            await update.message.reply_text("❌ لا توجد جلسة نشطة. استخدم /login أولاً.")
            return
        cookies = await login_context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"✅ تم حفظ {len(cookies)} كوكي في {COOKIES_FILE}")
        await update.message.reply_text(f"✅ **تم حفظ الجلسة!**\n📦 {len(cookies)} كوكي\n📁 `{COOKIES_FILE}`", parse_mode="Markdown")
        if login_browser:
            await login_browser.close()
        login_context = None
        login_browser = None
        login_event.set()
    except Exception as e:
        logger.error(f"فشل حفظ الكوكيز: {e}")
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")

# ===================================================================
# محرك التخفي
# ===================================================================
async def load_cookies(context) -> List[Dict]:
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r") as f:
                live_cookies = json.load(f)
            await context.add_cookies(live_cookies)
            return await context.cookies()
        except:
            pass
    # كوكيز احتياطية
    fallback = [
        {"name": "SAPISID", "value": "24YAxem4FqDbuFEk/Av3t8V1lvBUoZEhHl", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PAPISID", "value": "24YAxem4FqDbuFEk/Av3t8V1lvBUoZEhHl", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
        {"name": "SID", "value": "g.a000_wjNRT4QclMabSkctYvjiKX8isVmrjvsXjn-sIu83AjYzcxDf4E57O0vW0SExPoSYUJtkAACgYKARASARQSFQHGX2MivRer4LjlSHhMOnCsHRjnpBoVAUF8yKqWA_-BJRPIH__yizMU0i_Y0076", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "__Secure-3PSID", "value": "g.a000_wjNRT4QclMabSkctYvjiKX8isVmrjvsXjn-sIu83AjYzcxDiKinPT98rTDtiD4-SrNllQACgYKAbYSARQSFQHGX2MiUYFlgGm-fqgsDygOzSn6eRoVAUF8yKqi8zzCQgZxCxRqXq6JKSgU0076", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
    ]
    await context.add_cookies(fallback)
    return await context.cookies()

async def create_authenticated_context(browser, token: str, email: str, project: str):
    fingerprint = generate_random_fingerprint()
    ua = random.choice(USER_AGENTS)
    width = random.randint(1800, 1920)
    height = random.randint(1000, 1080)
    tz = random.choice(TIMEZONES)
    lang = random.choice(LANGUAGES)

    context_options = {
        "user_agent": ua,
        "viewport": {"width": width, "height": height},
        "locale": lang.split(",")[0],
        "timezone_id": tz,
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
    }
    
    proxy = get_random_proxy()
    if proxy:
        context_options["proxy"] = {"server": proxy}
    
    context = await browser.new_context(**context_options)
    await load_cookies(context)
    cookies_loaded = await context.cookies()
    logger.info(f"🍪 تم تحميل {len(cookies_loaded)} كوكي")

    # إخفاء الأتمتة
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'selenium', { get: () => undefined });
        if (!window.chrome) { window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} }; }
        delete window.__playwright;
        delete window.__pw_binding;
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
    except:
        pass

# ===================================================================
# دوال الأزرار والانتظار (مختصرة لكن فعالة)
# ===================================================================
async def smart_click_button(page, texts: List[str]) -> bool:
    for text in texts:
        try:
            btn = await page.query_selector(f"button:has-text('{text}'), div[role='button']:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                return True
        except:
            continue
    return False

EXPIRED_KEYWORDS = ["expired", "invalid", "sign in", "accounts.google.com", "Impossible de vous connecter", "choose an account"]

async def wait_for_redirect(page, email: str = None, max_wait: int = 120) -> Tuple[bool, str]:
    start = time.time()
    while time.time() - start < max_wait:
        url = page.url
        text = await page.inner_text("body")
        if "console.cloud.google.com" in url or "shell.cloud.google.com" in url:
            if "sign in" not in text.lower():
                return True, ""
        if any(k in text.lower() for k in EXPIRED_KEYWORDS):
            return False, "⛔ الرابط منتهي أو غير صالح"
        if "choose an account" in text.lower():
            if email:
                sel = f"div[data-email='{email}'], div:has-text('{email}'), button:has-text('{email}')"
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    continue
            await smart_click_button(page, ["Continue", "التالي", "Next"])
            await asyncio.sleep(2)
            continue
        if "email" in text.lower() and "identifier" in text.lower():
            if email:
                inp = await page.query_selector("input[type='email'], input[type='text'][name='identifier']")
                if inp:
                    await inp.fill(email)
                    await asyncio.sleep(1)
                    await smart_click_button(page, ["Next", "التالي"])
                    await asyncio.sleep(3)
                    continue
            return False, "⛔ فشل تسجيل الدخول (شاشة البريد)"
        if "password" in text.lower() or "كلمة المرور" in text.lower():
            return False, "⛔ الرابط يتطلب كلمة مرور"
        await asyncio.sleep(2)
    return False, "⛔ انتهت المهلة"

# ===================================================================
# Start Cloud Shell
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
        "button:has-text('Launch')",
        "div[role='button']:has-text('Start Cloud Shell')",
    ]
    for attempt in range(max_attempts):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        await asyncio.sleep(0.3)
        for sel in selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click()
                    return True
            except:
                continue
        # جافا سكريبت شامل
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
        except:
            pass
        await asyncio.sleep(4)
    return False

async def execute_command(page, cmd: str) -> bool:
    for attempt in range(3):
        try:
            for sel in [".xterm-helper-textarea", ".xterm", ".terminal", "[role='textbox']"]:
                try:
                    await page.focus(sel)
                    break
                except:
                    continue
            await asyncio.sleep(0.2)
            for ch in cmd:
                await page.keyboard.type(ch, delay=random.randint(8, 20))
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(1.5, 3))
            return True
        except:
            await asyncio.sleep(1)
    return False

async def wait_for_terminal(page, timeout=300) -> Tuple[bool, str]:
    selectors = [".xterm", ".xterm-helper-textarea", ".terminal", "[role='textbox']"]
    start = time.time()
    while time.time() - start < timeout:
        for sel in selectors:
            try:
                elem = await page.query_selector(sel)
                if elem and await elem.is_visible():
                    return True, ""
            except:
                continue
        await asyncio.sleep(1)
    return False, f"⏰ انتهت مهلة الطرفية ({timeout} ثانية)"

# ===================================================================
# البث المباشر (سريع، خفيف)
# ===================================================================
streaming_active = False
stream_start_time = None
current_step = "في انتظار البث"
current_url = ""

async def live_stream_broadcaster(page):
    global streaming_active, stream_start_time, current_step, current_url
    streaming_active = True
    stream_state.set_streaming(True)
    stream_start_time = time.time()
    current_step = "جاري فتح المتصفح..."
    logger.info("📹 بدء البث المباشر (سريع)")
    try:
        while streaming_active:
            try:
                # جودة منخفضة، إطار مرئي فقط
                screenshot = await page.screenshot(type='jpeg', quality=40, full_page=False)
                if screenshot:
                    stream_state.update_frame(screenshot)
                    try:
                        current_url = page.url[:80]
                    except:
                        pass
                elapsed = int(time.time() - stream_start_time)
                m, s = divmod(elapsed, 60)
                h, m = divmod(m, 60)
                dur = f"{h:02d}:{m:02d}:{s:02d}"
                stream_state.update_status(
                    action=f"🟢 {current_step} ({dur})",
                    project=current_url,
                    cookies=0
                )
                await asyncio.sleep(0.1)  # 10 إطارات/ثانية
            except:
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"⚠️ فشل البث: {e}")
    finally:
        streaming_active = False
        stream_state.set_streaming(False)
        current_step = "انتهى البث"
        logger.info("⏹️ تم إيقاف البث")

# ===================================================================
# سكريبت النشر (مبسط)
# ===================================================================
def generate_deploy_script(project_id: str, token: str, region: str, email: str) -> str:
    svc = f"shadow-svc-{random.randint(1000,9999)}-{project_id[:4]}"
    return f'''
import subprocess, re
PROJECT_ID = "{project_id}"
REGION = "{region}"
SERVICE_NAME = "{svc}"
subprocess.run("apt-get update && apt-get install google-cloud-sdk -y", shell=True, capture_output=True)
subprocess.run(f"gcloud config set project {PROJECT_ID}", shell=True, capture_output=True)
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

# ===================================================================
# قلب الأتمتة (آمن، مع إعادة محاولة)
# ===================================================================
async def run_browser_session(update, lab_url, project_id, token, email, region, start_time):
    global streaming_active, current_step
    video_path = None
    
    async with async_playwright() as p:
        async with await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled", "--disable-gpu"]
        ) as browser:
            
            context, page = await create_authenticated_context(browser, token, email, project_id)
            
            # بدء البث
            if True:  # ENABLE_LIVE_STREAM
                asyncio.create_task(live_stream_broadcaster(page))
            
            # التحقق من الكوكيز
            cookies = await context.cookies()
            if len(cookies) < 5:
                return False, "", "⚠️ الكوكيز غير مكتملة", int(time.time()-start_time), ""
            
            # فتح الرابط
            current_step = "فتح الرابط..."
            await page.goto(lab_url, timeout=min(180000, SHELL_TIMEOUT*1000), wait_until="networkidle")
            
            # إعادة التوجيه
            ok, msg = await wait_for_redirect(page, email, 120)
            if not ok:
                return False, "", msg, int(time.time()-start_time), ""
            
            # تأكد من الوصول
            body = await page.inner_text("body")
            if "sign in" in body.lower():
                return False, "", "⛔ فشل التجاوز (لا تزال شاشة الدخول)", int(time.time()-start_time), ""
            
            # تجاوز الأزرار الأولية
            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "Got it"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(1)
            
            # التوجه إلى Cloud Shell
            current_step = "التوجه إلى Cloud Shell..."
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
            await asyncio.sleep(3)
            
            # البحث عن Start
            for _ in range(15):
                await asyncio.sleep(2)
                if await page.query_selector("button:has-text('Start Cloud Shell'), button[aria-label='Start Cloud Shell']"):
                    break
            
            # الضغط على Start
            current_step = "البحث عن Start..."
            clicked = False
            for _ in range(5):
                if await click_start_ultimate(page, max_attempts=1):
                    clicked = True
                    break
                await asyncio.sleep(4)
            if not clicked:
                return False, "", "⚠️ لم يتم العثور على زر Start", int(time.time()-start_time), ""
            
            # الأزرار الإضافية
            for btn in ["Authorize", "تفويض", "Continue", "I understand"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(2)
            
            # انتظار الطرفية
            current_step = "انتظار الطرفية..."
            ok, msg = await wait_for_terminal(page, 360)
            if not ok:
                return False, "", msg, int(time.time()-start_time), ""
            
            # تنفيذ النشر
            current_step = "تنفيذ النشر..."
            script = generate_deploy_script(project_id, token, region, email)
            b64 = base64.b64encode(script.encode()).decode()
            await execute_command(page, f"echo '{b64}' | base64 -d > deploy.py")
            await execute_command(page, "python3 deploy.py")
            
            # قراءة النتيجة
            await execute_command(page, "cat /tmp/result.txt")
            await asyncio.sleep(2)
            result_content = ""
            try:
                term = await page.query_selector(".xterm, .terminal, [role='textbox']")
                if term:
                    result_content = await term.inner_text()
            except:
                pass
            if not result_content:
                result_content = await page.inner_text("body")
            
            # استخراج الفيديو إن وجد
            try:
                video = await context.video
                if video:
                    video_path = await video.path()
            except:
                pass
            
            # إغلاق المتصفح (يُغلق تلقائياً مع async with)
            streaming_active = False
            stream_state.set_streaming(False)
            
            # استخراج النتائج
            service_match = re.search(r'SERVICE_URL:\s*(https://[^\s]+)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)
            
            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time()-start_time), video_path
            else:
                return False, "", f"⚠️ لم يتم العثور على النتيجة: {result_content[-200:]}", int(time.time()-start_time), video_path

async def run_in_cloudshell(update, lab_url, project_id, token, email, region):
    start = time.time()
    for attempt in range(3):
        try:
            res = await run_browser_session(update, lab_url, project_id, token, email, region, start)
            if res[0]:  # نجاح
                return res
            if attempt < 2:
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"❌ المحاولة {attempt+1} فشلت: {e}")
            if attempt < 2:
                await asyncio.sleep(5)
    return False, "", "❌ فشل بعد 3 محاولات", int(time.time()-start), ""

# ===================================================================
# واجهة البوت (مبسطة)
# ===================================================================
WAITING_LINK, WAITING_REGION = range(2)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 Iowa",
    "us-east1": "🇺🇸 S. Carolina",
    "us-west1": "🇺🇸 Oregon",
    "europe-west1": "🇧🇪 Belgium",
    "europe-west2": "🇬🇧 London",
    "europe-west3": "🇩🇪 Frankfurt",
    "asia-east1": "🇹🇼 Taiwan",
    "asia-northeast1": "🇯🇵 Tokyo",
    "asia-southeast1": "🇸🇬 Singapore",
    "australia-southeast1": "🇦🇺 Sydney",
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
        "⚡ **Shadow Legion**\n━━━━━━━━━━━━━━━━\nأرسل الرابط، وسأتكفل بالباقي.",
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
    extracted = smart_extract(text)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project:
        await update.message.reply_text("❌ لم أستخرج **project** من الرابط.")
        return WAITING_LINK
    user_id = update.effective_user.id
    update_last_link(user_id, text)
    context.user_data.update({"lab_url": text, "project_id": project, "token": token, "email": email})
    token_display = token[:15] if token else "الكوكيز الحية"
    await update.message.reply_text(
        f"✅ **تم الاستخراج**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n🔑 Token: `{token_display}`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    if not user or not user.get("last_link"):
        await update.message.reply_text("📭 لا يوجد رابط سابق.")
        return ConversationHandler.END
    last = user["last_link"]
    extracted = smart_extract(last)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project:
        await update.message.reply_text("❌ الرابط المخزن لا يحتوي على project.")
        return ConversationHandler.END
    context.user_data.update({"lab_url": last, "project_id": project, "token": token, "email": email})
    token_display = token[:15] if token else "الكوكيز الحية"
    await update.message.reply_text(
        f"✅ **إعادة استخدام الرابط**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n🔑 Token: `{token_display}`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    raw = q.data.replace("region_", "")
    if raw == "random":
        region = random.choice(list(KNOWN_REGIONS.keys()))
    elif raw == "cancel":
        await q.edit_message_text("❌ أُلغي.")
        context.user_data.clear()
        return
    else:
        region = raw
    user_id = q.from_user.id
    lab = context.user_data.get("lab_url")
    proj = context.user_data.get("project_id")
    tok = context.user_data.get("token")
    email = context.user_data.get("email")
    if not proj:
        await q.edit_message_text("❌ انتهت الجلسة. أعد الإرسال.")
        return
    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 جاري النشر على {region_name} ... (3-6 دقائق)")
    success, service, vless, duration, video = await run_in_cloudshell(
        update, lab, proj, tok, email, region
    )
    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab, service, vless, region, success=1, duration=duration, video_path=video or "")
        await q.message.reply_text(
            f"✅ **تم النشر بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown"
        )
        if video and os.path.exists(video):
            await q.message.reply_text(f"📹 **فيديو:** `{video}`", parse_mode="Markdown")
    else:
        add_history(user_id, lab, "", "", region, success=0, error_msg=vless[:200], duration=duration, video_path=video or "")
        await q.message.reply_text(f"❌ **فشل النشر**\n\n```\n{vless}\n```", parse_mode="Markdown")
    context.user_data.clear()

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
    hist = get_history(update.effective_user.id, 5)
    if not hist:
        await update.message.reply_text("📭 لا يوجد سجل.")
        return
    text = "📜 **آخر 5 نشرات:**\n"
    for i, h in enumerate(hist, 1):
        status = "✅" if h['success'] else "❌"
        region = KNOWN_REGIONS.get(h['region_used'], h['region_used'])
        text += f"{i}. {status} {region} – {h['deployed_at'][:16]}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ **الأوامر:**\n"
        "/start – القائمة\n"
        "/login – تسجيل الدخول لمرة واحدة\n"
        "/deploy – نشر جديدة\n"
        "/retry – إعادة استخدام آخر رابط\n"
        "/stats – إحصائياتك\n"
        "/history – سجل النشرات\n"
        "/cancel – إلغاء",
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
# تشغيل خادم الويب
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
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("retry", retry_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(CallbackQueryHandler(lambda u,c: c.user_data.clear() or u.edit_message_text("❌ أُلغي."), pattern="^cancel$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    start_web_dashboard()
    logger.info("🔥 SHADOW LEGION v30.0 (Fast Stable) جاهز")
    app.run_polling()

if __name__ == "__main__":
    main()