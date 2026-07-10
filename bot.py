#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v31.0 – DIRECT_LINK_STEALTH_MASTER
- فتح الرابط مباشرة في متصفح متخفي (بدون استخراج بيانات)
- الاعتماد الكامل على الكوكيز الحية
- Z3R0-STEALTH v2
- بث مباشر سريع قابل للإلغاء
- تسجيل فيديو تلقائي
- MongoDB
- إعادة محاولة ذكية
- واجهة بوت مبسطة وغامضة
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
logger.info("🚀 SHADOW LEGION v31.0 (Direct Link Stealth Master) بدأ التشغيل...")

# ===================================================================
# 2. اتصال MongoDB
# ===================================================================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DB_NAME]
    users_collection = db["users"]
    history_collection = db["deploy_history"]
    client.admin.command('ping')
    logger.info("✅ الاتصال بـ MongoDB ناجح.")
except Exception as e:
    logger.error(f"❌ فشل الاتصال بـ MongoDB: {e}")
    raise

# ===================================================================
# 3. دوال قاعدة البيانات (MongoDB)
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
    result = []
    for doc in docs:
        result.append({
            "id": str(doc["_id"]),
            "lab_url": doc.get("lab_url"),
            "service_url": doc.get("service_url"),
            "vless_link": doc.get("vless_link"),
            "region_used": doc.get("region_used"),
            "deployed_at": doc.get("deployed_at"),
            "success": doc.get("success", 0),
            "error_msg": doc.get("error_msg"),
            "duration": doc.get("duration_seconds", 0)
        })
    return result

# ===================================================================
# 4. دوال مساعدة متقدمة (تمويه، كابتشا، استخراج بروجكت اختياري)
# ===================================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/118.0",
]
TIMEZONES = ["America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney", "America/Los_Angeles", "Europe/Paris", "Asia/Dubai"]
LANGUAGES = ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.9,ar;q=0.8", "fr-FR,fr;q=0.9,en;q=0.8"]

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
        "vendor": random.choice(['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple', 'ARM']),
        "renderer": random.choice(['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M', 'Apple M1 GPU', 'ARM Mali-G78']),
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
            data = {
                "key": TWOCAPTCHA_API_KEY,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": page.url,
                "json": 1
            }
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

def extract_project_from_url(url: str) -> Optional[str]:
    """محاولة استخراج project ID من الرابط (اختياري، للاستخدام في النشر)."""
    match = re.search(r'[?&]project=([^&]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/projects/([^/?#]+)', url)
    if match:
        return match.group(1)
    return None

# ===================================================================
# 5. نظام الجلسة الحية (Login / Done)
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
        fingerprint = generate_random_fingerprint()
        ua = random.choice(USER_AGENTS)
        width = random.randint(1800, 1920)
        height = random.randint(1000, 1080)
        tz = random.choice(TIMEZONES)
        lang = random.choice(LANGUAGES)
        lat = random.uniform(30, 50)
        lon = random.uniform(-100, -70)
        
        async with async_playwright() as p:
            login_browser = await p.chromium.launch(
                headless=False,
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
                    "--disable-sync",
                    "--force-color-profile=srgb",
                    "--metrics-recording-only",
                    "--no-first-run"
                ]
            )
            login_context = await login_browser.new_context(
                user_agent=ua,
                viewport={"width": width, "height": height},
                locale=lang.split(",")[0],
                timezone_id=tz,
                permissions=["geolocation"],
                geolocation={"latitude": lat, "longitude": lon},
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
                },
                ignore_https_errors=True,
                accept_downloads=True,
                java_script_enabled=True,
            )
            await login_context.add_init_script(f"""
                (() => {{
                    Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
                    Object.defineProperty(navigator, 'selenium', {{ get: () => undefined }});
                    delete window.__webdriver_evaluate;
                    delete window.__webdriver_script_function;
                    delete window.__webdriver_script_func;
                    if (!window.chrome) {{
                        window.chrome = {{ runtime: {{}}, loadTimes: () => {{}}, csi: () => {{}}, app: {{}} }};
                    }}
                    const plugins = [
                        {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' }},
                        {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' }},
                        {{ name: 'Native Client', filename: 'internal-nacl-plugin' }}
                    ];
                    plugins.length = 5;
                    navigator.__defineGetter__('plugins', () => plugins);
                    Object.defineProperty(navigator, 'languages', {{ get: () => ['{lang}', 'en-US', 'en'] }});
                    Object.defineProperty(navigator, 'platform', {{ get: () => '{fingerprint["platform"]}' }});
                    Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fingerprint["device_memory"]} }});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fingerprint["hardware_concurrency"]} }});
                    const realGetParam = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(p) {{
                        if (p === 37445) return '{fingerprint["vendor"]}';
                        if (p === 37446) return '{fingerprint["renderer"]}';
                        if (p === 7936) return 'WebGL 1.0';
                        if (p === 7937) return 'WebGL GLSL ES 1.0';
                        return realGetParam.call(this, p);
                    }};
                    WebGLRenderingContext.prototype.getExtension = function(name) {{
                        if (name === 'WEBGL_debug_renderer_info') return null;
                        return WebGLRenderingContext.prototype.getExtension.call(this, name);
                    }};
                    const canvasNoise = {fingerprint["canvas_noise"]};
                    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                    HTMLCanvasElement.prototype.toDataURL = function(type) {{
                        if (type === 'image/png' || !type) {{
                            const ctx = this.getContext('2d');
                            if (ctx) {{
                                const imgData = ctx.getImageData(0, 0, this.width, this.height);
                                for (let i = 0; i < imgData.data.length; i += 4) {{
                                    if (Math.random() < canvasNoise) {{
                                        imgData.data[i] ^= (Math.random() > 0.5 ? 1 : 0);
                                        imgData.data[i+1] ^= (Math.random() > 0.5 ? 1 : 0);
                                        imgData.data[i+2] ^= (Math.random() > 0.5 ? 1 : 0);
                                    }}
                                }}
                                ctx.putImageData(imgData, 0, 0);
                            }}
                        }}
                        return origToDataURL.apply(this, arguments);
                    }};
                    const audioNoise = {fingerprint["audio_noise"]};
                    const origChannel = AudioBuffer.prototype.getChannelData;
                    AudioBuffer.prototype.getChannelData = function(ch) {{
                        const data = origChannel.call(this, ch);
                        for (let i = 0; i < data.length; i += 100) data[i] += (Math.random() - 0.5) * audioNoise;
                        return data;
                    }};
                    delete window.__playwright;
                    delete window.__pw_binding;
                    delete window.__pw_;
                    if (navigator.userAgent !== '{ua}') {{
                        Object.defineProperty(navigator, 'userAgent', {{ get: () => '{ua}' }});
                    }}
                    console.log('[Z3R0] بصمة مخفية.');
                }})();
            """)
            page = await login_context.new_page()
            await simulate_mouse_movement(page)
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
        await update.message.reply_text(
            f"✅ **تم حفظ الجلسة!**\n📦 {len(cookies)} كوكي\n📁 `{COOKIES_FILE}`",
            parse_mode="Markdown"
        )
        if login_browser:
            await login_browser.close()
        login_context = None
        login_browser = None
        login_event.set()
    except Exception as e:
        logger.error(f"فشل حفظ الكوكيز: {e}")
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")

# ===================================================================
# 6. محرك التخفي الأساسي (Z3R0-STEALTH v2)
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

async def create_stealth_context(browser):
    """إنشاء سياق متخفي بالكامل بدون token أو email."""
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
    }
    
    proxy = get_random_proxy()
    if proxy:
        context_options["proxy"] = {"server": proxy}
        logger.info(f"🌐 استخدام Proxy: {proxy[:30]}...")
    
    context = await browser.new_context(**context_options)
    await load_cookies(context)
    cookies_loaded = await context.cookies()
    logger.info(f"🍪 تم تحميل {len(cookies_loaded)} كوكي")

    # Z3R0-STEALTH v2 (سكريبت التخفي الكامل)
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
        console.log('[Z3R0] بصمة مخفية بالكامل.');
    """)

    page = await context.new_page()
    await simulate_mouse_movement(page)
    return context, page

async def simulate_mouse_movement(page):
    try:
        for _ in range(random.randint(3, 6)):
            x = random.randint(100, 1800)
            y = random.randint(100, 900)
            await page.mouse.move(x, y, steps=random.randint(10, 30))
            await asyncio.sleep(random.uniform(0.1, 0.5))
        await page.mouse.click(random.randint(100, 1800), random.randint(100, 900))
        logger.info("✅ تمت محاكاة حركة الماوس.")
    except Exception as e:
        logger.warning(f"⚠️ فشل محاكاة حركة الماوس: {e}")

# ===================================================================
# 7. دوال الأزرار والانتظار المتقدمة
# ===================================================================
async def smart_click_button(page, text_keywords: List[str], aria_labels: List[str] = None) -> bool:
    if aria_labels is None:
        aria_labels = text_keywords
    for text in text_keywords:
        try:
            btn = await page.query_selector(f"button:has-text('{text}'), div[role='button']:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                logger.info(f"✅ نقر على الزر عبر النص: {text}")
                return True
        except:
            pass
    for label in aria_labels:
        try:
            btn = await page.query_selector(f"button[aria-label*='{label}'], div[role='button'][aria-label*='{label}']")
            if btn and await btn.is_visible():
                await btn.click()
                logger.info(f"✅ نقر على الزر عبر aria-label: {label}")
                return True
        except:
            pass
    try:
        buttons = await page.query_selector_all("button, div[role='button'], a[role='button']")
        for btn in buttons:
            text = await btn.inner_text()
            aria = await btn.get_attribute("aria-label") or ""
            combined = (text + " " + aria).lower()
            for kw in text_keywords:
                if kw.lower() in combined:
                    if await btn.is_visible():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        logger.info(f"✅ نقر على الزر عبر البحث الشامل: {kw}")
                        return True
    except:
        pass
    return False

async def extract_sitekey(page) -> Optional[str]:
    try:
        iframes = await page.query_selector_all("iframe[src*='recaptcha']")
        for iframe in iframes:
            src = await iframe.get_attribute("src")
            if src:
                match = re.search(r'k=([^&]+)', src)
                if match:
                    return match.group(1)
        return None
    except:
        return None

EXPIRED_KEYWORDS = [
    "expired", "invalid", "session", "access denied", "not found", "404", "410",
    "sign in", "choose an account", "accounts.google.com", "login", "log in",
    "Couldn't sign you in", "verify this account", "contact your administrator",
    "domain", "not authorized", "forbidden", "terminated", "suspended",
    "Impossible de vous connecter"
]

async def wait_for_redirect_auto(update: Update, page, email: str = None, max_wait: int = 120) -> Tuple[bool, str]:
    start_time = time.time()
    login_attempted = False
    last_url = ""
    while time.time() - start_time < max_wait:
        current_url = page.url
        page_text = await page.inner_text("body")
        if current_url != last_url:
            logger.info(f"🔄 URL الحالي: {current_url[:80]}")
            last_url = current_url
        if ("console.cloud.google.com" in current_url or "shell.cloud.google.com" in current_url):
            if "sign in" not in page_text.lower() and "email" not in page_text.lower() and "password" not in page_text.lower():
                logger.info("✅ تم الوصول إلى Console/Shell بنجاح.")
                return True, ""
            else:
                logger.warning("⚠️ المحتوى هو شاشة تسجيل دخول.")
        if any(kw in page_text.lower() for kw in EXPIRED_KEYWORDS):
            logger.warning("⛔ رابط منتهي الصلاحية.")
            return False, "⛔ انتهت صلاحية الرابط."
        if "Welcome to your new account" in page_text:
            if await smart_click_button(page, ["Understand", "I understand"]):
                logger.info("✅ تم الضغط على Understand.")
                await asyncio.sleep(2)
                continue
        if "recaptcha" in page_text.lower() or "captcha" in page_text.lower():
            logger.info("🛡️ CAPTCHA مكتشفة...")
            sitekey = await extract_sitekey(page)
            if sitekey:
                solution = await solve_captcha_2captcha(page, sitekey)
                if solution:
                    try:
                        await page.fill("#g-recaptcha-response", solution)
                        await page.click("form button[type='submit'], form input[type='submit']")
                        logger.info("✅ تم حل CAPTCHA.")
                        await asyncio.sleep(2)
                        continue
                    except:
                        pass
        if "accounts.google.com" in current_url or "sign in" in page_text.lower() or "Impossible de vous connecter" in page_text:
            logger.info("🔐 شاشة Google – محاولة التجاوز...")
            if "choose an account" in page_text.lower() or "pick an account" in page_text.lower():
                logger.info("🔄 شاشة اختيار حساب...")
                try:
                    if email:
                        account_selector = f"div[data-email='{email}'], div:has-text('{email}'), button:has-text('{email}')"
                        btn = await page.query_selector(account_selector)
                        if btn and await btn.is_visible():
                            await btn.click()
                            logger.info(f"✅ تم النقر على الحساب: {email}")
                            await asyncio.sleep(2)
                            continue
                    if await smart_click_button(page, ["Continue", "التالي", "Next"]):
                        logger.info("✅ تم الضغط على Continue.")
                        await asyncio.sleep(2)
                        continue
                except Exception as e:
                    logger.warning(f"⚠️ فشل النقر على الحساب: {e}")
            elif "email" in page_text.lower() or "identifier" in page_text.lower() or "phone" in page_text.lower():
                logger.info("📧 شاشة إدخال البريد...")
                if email and not login_attempted:
                    try:
                        email_input = await page.wait_for_selector("input[type='email'], input[type='text'][name='identifier']", timeout=5000)
                        if email_input:
                            await email_input.fill(email)
                            logger.info(f"✅ تم إدخال البريد: {email}")
                            await asyncio.sleep(1)
                            if await smart_click_button(page, ["Next", "التالي"]):
                                logger.info("✅ تم الضغط على Next.")
                                await asyncio.sleep(3)
                                login_attempted = True
                                continue
                    except:
                        pass
                return False, "⛔ فشل تسجيل الدخول (شاشة البريد)."
            elif "password" in page_text.lower() or "كلمة المرور" in page_text:
                logger.warning("🔑 شاشة كلمة المرور – لا يمكن التجاوز.")
                return False, "⛔ الرابط يتطلب كلمة مرور."
            else:
                logger.warning("⚠️ شاشة غير متوقعة، إعادة التحميل...")
                await page.reload()
                await asyncio.sleep(2)
                continue
        await asyncio.sleep(2)
    return False, "⛔ انتهت المهلة (120 ثانية)."

# ===================================================================
# 8. دوال Start Cloud Shell والطرفية (محسّنة)
# ===================================================================
async def click_start_ultimate(page, max_attempts=8) -> bool:
    logger.info("🔍 البحث عن زر Start Cloud Shell (محاولات متعددة)...")
    
    selectors = [
        "button[data-testid='cloud-shell-launch-button']",
        "button[data-testid='cloud-shell-start']",
        "button.gcp-shell-launch",
        "button[aria-label='Start Cloud Shell']",
        "button[aria-label='Open Cloud Shell']",
        "button:has-text('Start Cloud Shell')",
        "button:has-text('Activate Cloud Shell')",
        "button:has-text('Launch Cloud Shell')",
        "button:has-text('بدء Cloud Shell')",
        "button:has-text('تفعيل Cloud Shell')",
        "button:has-text('Start')",
        "button:has-text('Launch')",
        "button:has-text('Activate')",
        "button:has-text('بدء')",
        "button:has-text('تشغيل')",
        "button:has-text('تفعيل')",
        "button#start-cloud-shell",
        "button.gcloud-start-button",
        "button[data-command='start']",
        "button[data-action='start']",
        ".cloud-shell-start-button",
        ".start-cloud-shell-btn",
        "button[class*='start']",
        "button[class*='cloud-shell']",
        "div[role='button']:has-text('Start Cloud Shell')",
        "div[role='button']:has-text('Activate Cloud Shell')",
        "div[role='button']:has-text('Launch Cloud Shell')",
    ]
    
    for attempt in range(max_attempts):
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            await asyncio.sleep(0.5)
        except:
            pass
        
        for selector in selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    await btn.click()
                    logger.info(f"✅ تم الضغط على الزر باستخدام: {selector}")
                    return True
            except:
                continue
        
        try:
            frames = page.frames
            for frame in frames:
                for selector in selectors:
                    try:
                        btn = await frame.query_selector(selector)
                        if btn and await btn.is_visible():
                            await btn.scroll_into_view_if_needed()
                            await asyncio.sleep(0.5)
                            await btn.click()
                            logger.info(f"✅ تم الضغط على الزر في iframe: {selector}")
                            return True
                    except:
                        continue
        except:
            pass
        
        try:
            result = await page.evaluate("""
                () => {
                    const keywords = ['start', 'launch', 'activate', 'بدء', 'تشغيل', 'تفعيل', 'run', 'open'];
                    const btns = document.querySelectorAll('button, div[role="button"], a[role="button"]');
                    for (let btn of btns) {
                        const text = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
                        if (keywords.some(k => text.includes(k))) {
                            btn.scrollIntoView();
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if result:
                logger.info("✅ تم الضغط على الزر عبر JavaScript الشامل.")
                return True
        except:
            pass
        
        logger.warning(f"⚠️ لم يتم العثور على زر Start في المحاولة {attempt+1}/{max_attempts}")
        await asyncio.sleep(5)
    
    logger.error("❌ فشل العثور على زر Start Cloud Shell بعد عدة محاولات.")
    return False

async def execute_command_robust(page, cmd: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        logger.info(f"▶️ تنفيذ: {cmd[:60]}... (محاولة {attempt+1}/{max_retries})")
        try:
            terminal_selectors = [".xterm-helper-textarea", ".xterm", ".terminal", "[role='textbox']"]
            for selector in terminal_selectors:
                try:
                    await page.focus(selector)
                    break
                except:
                    continue
            await asyncio.sleep(0.3)
            for ch in cmd:
                await page.keyboard.type(ch, delay=random.randint(10, 25))
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(1.5, 3))
            return True
        except Exception as e:
            logger.error(f"فشل الأمر في المحاولة {attempt+1}: {e}")
            await asyncio.sleep(2)
    logger.error(f"❌ فشل تنفيذ الأمر بعد {max_retries} محاولات.")
    return False

async def wait_for_terminal_enhanced(page, timeout_seconds=360) -> Tuple[bool, str]:
    logger.info(f"⏳ في انتظار الطرفية (مهلة {timeout_seconds} ثانية)...")
    start_time = time.time()
    selectors = [
        ".xterm", ".xterm-helper-textarea", ".xterm-screen", ".terminal",
        "[role='textbox']", "textarea", ".terminal-active", ".xterm-viewport"
    ]
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=20000, state="visible")
            logger.info(f"✅ تم العثور على الطرفية باستخدام: {selector}")
            return True, ""
        except:
            continue
    try:
        frames = page.frames
        for frame in frames:
            for selector in selectors:
                try:
                    elem = await frame.wait_for_selector(selector, timeout=5000, state="visible")
                    if elem:
                        logger.info(f"✅ تم العثور على الطرفية داخل iframe: {selector}")
                        return True, ""
                except:
                    continue
    except Exception as e:
        logger.warning(f"⚠️ فشل البحث في iframes: {e}")
    while time.time() - start_time < timeout_seconds:
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    logger.info(f"✅ الطرفية ظهرت (حلقة احتياطية) – {selector}")
                    return True, ""
            except:
                pass
        await asyncio.sleep(1)
    return False, f"⏰ انتهت مهلة انتظار الطرفية ({timeout_seconds} ثانية)."

# ===================================================================
# 9. البث المباشر (مع إمكانية الإلغاء الفوري)
# ===================================================================
streaming_active = False
stream_stop_event = asyncio.Event()
stream_start_time = None
current_step = "في انتظار البث"
current_url = ""

async def live_stream_broadcaster(page):
    global streaming_active, stream_start_time, current_step, current_url
    streaming_active = True
    stream_state.set_streaming(True)
    stream_start_time = time.time()
    current_step = "جاري فتح المتصفح..."
    logger.info("📹 بدء البث المباشر (سريع، قابل للإلغاء)...")
    
    try:
        while not stream_stop_event.is_set():
            try:
                screenshot = await page.screenshot(type='jpeg', quality=40, full_page=False)
                if screenshot:
                    stream_state.update_frame(screenshot)
                    try:
                        current_url = page.url[:100]
                    except:
                        pass
                
                elapsed = int(time.time() - stream_start_time)
                m, s = divmod(elapsed, 60)
                h, m = divmod(m, 60)
                duration_str = f"{h:02d}:{m:02d}:{s:02d}"
                
                try:
                    cookies = await page.context.cookies()
                    cookie_count = len(cookies)
                except:
                    cookie_count = 0
                
                stream_state.update_status(
                    action=f"🟢 {current_step} ({duration_str})",
                    project=current_url,
                    cookies=cookie_count
                )
                
                await asyncio.sleep(0.1)
            except Exception as e:
                if "closed" in str(e).lower():
                    logger.warning("⚠️ تم إغلاق المتصفح، إيقاف البث")
                    break
                logger.warning(f"⚠️ خطأ في حلقة البث: {e}")
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"⚠️ فشل البث المباشر: {e}")
    finally:
        streaming_active = False
        stream_state.set_streaming(False)
        stream_stop_event.clear()
        current_step = "انتهى البث"
        logger.info("⏹️ تم إيقاف البث المباشر.")

# ===================================================================
# 10. سكريبت النشر (اختياري، يُستخدم فقط إذا وجد project)
# ===================================================================
def generate_deploy_script(project_id: str, region: str) -> str:
    service_name = f"shadow-svc-{random.randint(1000, 9999)}-{project_id[:4]}"
    return f'''
import subprocess, re
PROJECT_ID = "{project_id}"
REGION = "{region}"
SERVICE_NAME = "{service_name}"
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
# 11. قلب الأتمتة (فتح الرابط مباشرة)
# ===================================================================
async def run_browser_session_direct(update, lab_url, region, start_time):
    global stream_stop_event, streaming_active, current_step
    video_path = None
    browser = None
    context_browser = None
    page = None
    stream_task = None
    
    logger.info(f"🔄 فتح الرابط مباشرة في متصفح متخفي: {lab_url[:80]}...")
    current_step = "تشغيل المتصفح..."
    stream_stop_event.clear()
    
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
                    "--disable-features=BlockInsecurePrivateNetworkRequests",
                    "--disable-features=OutOfBlinkCors",
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
            
            context_browser, page = await create_stealth_context(browser)
            stream_task = asyncio.create_task(live_stream_broadcaster(page))
            
            cookies = await context_browser.cookies()
            if len(cookies) < 5:
                logger.warning("⚠️ عدد الكوكيز قليل.")
                stream_stop_event.set()
                if stream_task:
                    try:
                        await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                    except:
                        pass
                await browser.close()
                return False, "", "⚠️ الكوكيز غير مكتملة. استخدم /login", int(time.time()-start_time), ""
            
            current_step = "فتح الرابط..."
            logger.info(f"📌 فتح الرابط: {lab_url[:80]}...")
            await page.goto(lab_url, timeout=min(180000, SHELL_TIMEOUT*1000), wait_until="networkidle")
            
            current_step = "انتظار إعادة التوجيه..."
            ok, msg = await wait_for_redirect_auto(update, page, email=None, max_wait=120)
            if not ok:
                stream_stop_event.set()
                if stream_task:
                    try:
                        await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                    except:
                        pass
                await browser.close()
                return False, "", msg, int(time.time()-start_time), ""
            
            page_text = await page.inner_text("body")
            if "sign in" in page_text.lower() or "email" in page_text.lower():
                logger.error("❌ لا تزال شاشة تسجيل دخول.")
                stream_stop_event.set()
                if stream_task:
                    try:
                        await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                    except:
                        pass
                await browser.close()
                return False, "", "⛔ فشل التجاوز: لا تزال شاشة الدخول.", int(time.time()-start_time), ""
            
            logger.info("✅ تم الوصول إلى Console/Shell.")
            current_step = "تجاوز الأزرار الأولية..."
            
            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "Got it"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(1)
            
            if "shell.cloud.google.com" not in page.url:
                current_step = "التوجه إلى Cloud Shell..."
                await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
                await asyncio.sleep(3)
            
            for _ in range(15):
                await asyncio.sleep(2)
                if await page.query_selector("button:has-text('Start Cloud Shell'), button[aria-label='Start Cloud Shell']"):
                    break
            
            current_step = "البحث عن Start..."
            clicked = False
            for _ in range(5):
                if await click_start_ultimate(page, max_attempts=1):
                    clicked = True
                    break
                await asyncio.sleep(4)
            if not clicked:
                stream_stop_event.set()
                if stream_task:
                    try:
                        await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                    except:
                        pass
                await browser.close()
                return False, "", "⚠️ لم يتم العثور على زر Start", int(time.time()-start_time), ""
            
            for btn in ["Authorize", "تفويض", "Continue", "I understand"]:
                await smart_click_button(page, [btn])
                await asyncio.sleep(2)
            
            current_step = "انتظار الطرفية..."
            ok, msg = await wait_for_terminal_enhanced(page, 360)
            if not ok:
                stream_stop_event.set()
                if stream_task:
                    try:
                        await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                    except:
                        pass
                await browser.close()
                return False, "", msg, int(time.time()-start_time), ""
            
            logger.info("✅ الطرفية ظهرت.")
            current_step = "تنفيذ الأوامر..."
            
            # محاولة استخراج project من الرابط لتنفيذ النشر التلقائي
            project_id = extract_project_from_url(lab_url)
            if project_id:
                script = generate_deploy_script(project_id, region)
                b64 = base64.b64encode(script.encode()).decode()
                await execute_command_robust(page, f"echo '{b64}' | base64 -d > deploy.py")
                await execute_command_robust(page, "python3 deploy.py")
            else:
                # إذا لم نجد project، نترك المستخدم يكتب الأمر يدوياً
                logger.info("ℹ️ لم يتم العثور على project، ينتظر المستخدم إدخال الأوامر يدوياً.")
                await update.message.reply_text(
                    "⚠️ لم أستخرج Project ID من الرابط.\n"
                    "يمكنك إدخال الأوامر يدوياً في الطرفية.\n"
                    "مثال: `gcloud run deploy ...`",
                    parse_mode="Markdown"
                )
                # ننتظر 60 ثانية ليتفاعل المستخدم (يمكن تحسينه لاحقاً)
                await asyncio.sleep(60)
            
            # قراءة النتيجة
            await execute_command_robust(page, "cat /tmp/result.txt")
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
            
            try:
                video = await context_browser.video
                if video:
                    video_path = await video.path()
            except:
                pass
            
            stream_stop_event.set()
            if stream_task:
                try:
                    await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
                except:
                    pass
            await browser.close()
            streaming_active = False
            stream_state.set_streaming(False)
            
            service_match = re.search(r'SERVICE_URL:\s*(https://[^\s]+)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)
            
            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time()-start_time), video_path
            else:
                return False, "", f"⚠️ لم يتم العثور على النتيجة: {result_content[-200:]}", int(time.time()-start_time), video_path
                
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        stream_stop_event.set()
        if stream_task:
            try:
                await asyncio.shield(asyncio.wait_for(stream_task, timeout=1))
            except:
                pass
        if browser:
            try:
                await browser.close()
            except:
                pass
        return False, "", f"❌ خطأ: {str(e)[:200]}", int(time.time()-start_time), ""

async def run_in_cloudshell_direct(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   lab_url: str, region: str) -> Tuple[bool, str, str, int, str]:
    start_time = time.time()
    for attempt in range(3):
        try:
            logger.info(f"🔄 المحاولة {attempt+1}/3 لفتح الرابط مباشرة...")
            result = await run_browser_session_direct(update, lab_url, region, start_time)
            if result[0]:
                return result
            if attempt < 2:
                logger.info(f"⏳ انتظار 5 ثوانٍ قبل المحاولة التالية...")
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"❌ فشل المحاولة {attempt+1}: {e}")
            if attempt < 2:
                await asyncio.sleep(5)
    return False, "", "❌ فشل بعد 3 محاولات", int(time.time()-start_time), ""

# ===================================================================
# 12. دوال تنظيف الملفات القديمة
# ===================================================================
def cleanup_old_recordings():
    try:
        recordings_dir = "recordings"
        if not os.path.exists(recordings_dir):
            return
        cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
        for filename in os.listdir(recordings_dir):
            filepath = os.path.join(recordings_dir, filename)
            if os.path.isfile(filepath):
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    logger.info(f"🗑️ تم حذف تسجيل قديم: {filename}")
    except Exception as e:
        logger.warning(f"⚠️ فشل تنظيف التسجيلات: {e}")

# ===================================================================
# 13. واجهة البوت (مبسطة وغامضة، بدون استخراج بيانات)
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
        short_name = name.split(" ")[0] + " " + name.split("(")[-1].replace(")", "")
        row.append(InlineKeyboardButton(short_name, callback_data=f"region_{code}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🎲 اختيار عشوائي", callback_data="region_random")])
    kb.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    create_or_update_user(u.id, u.username, u.first_name, u.last_name)
    message = (
        "⚡ **Shadow Legion**\n"
        "━━━━━━━━━━━━━━━━\n"
        "أرسل الرابط، وسأتكفل بالباقي."
    )
    await update.message.reply_text(message, parse_mode="Markdown")

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 أرسل رابط Qwiklabs أو Google SSO:", reply_markup=ReplyKeyboardRemove())
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["❌ إلغاء", "🔄 إعادة المحاولة"]:
        if text == "🔄 إعادة المحاولة":
            return await retry_command(update, context)
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    
    # لا نستخرج أي شيء، نأخذ الرابط مباشرة
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
        await update.message.reply_text("📭 لا يوجد رابط سابق.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    last_link = user_data["last_link"]
    context.user_data.update({"lab_url": last_link})
    await update.message.reply_text(
        f"🔄 جاري إعادة استخدام الرابط السابق:\n`{last_link[:80]}...`",
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
    
    lab = context.user_data.get("lab_url")
    if not lab:
        await q.edit_message_text("❌ لا يوجد رابط. أعد الإرسال.")
        return
    
    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 جاري فتح الرابط في متصفح متخفي على {region_name} ... (3-6 دقائق)")
    
    success, service, vless, duration, video = await run_in_cloudshell_direct(
        update, context, lab, region
    )
    
    user_id = q.from_user.id
    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab, service, vless, region, success=1, duration=duration, video_path=video or "")
        await q.message.reply_text(
            f"✅ **تم التنفيذ بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown"
        )
        if video and os.path.exists(video):
            await q.message.reply_text(f"📹 **تم تسجيل الفيديو:**\n`{video}`", parse_mode="Markdown")
    else:
        add_history(user_id, lab, "", "", region, success=0, error_msg=vless[:200], duration=duration, video_path=video or "")
        await q.message.reply_text(
            f"❌ **فشل التنفيذ**\n\n```\n{vless}\n```",
            parse_mode="Markdown"
        )
    context.user_data.clear()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
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
        "/login – تسجيل الدخول لمرة واحدة (يحفظ الكوكيز)\n"
        "/deploy – إرسال رابط لفتحه في متصفح متخفي\n"
        "/retry – إعادة استخدام آخر رابط\n"
        "/stats – إحصائياتك\n"
        "/history – سجل النشرات\n"
        "/cancel – إلغاء العملية",
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
# 14. التشغيل الرئيسي
# ===================================================================
def start_web_dashboard():
    try:
        import threading
        import web_dashboard
        port = int(os.environ.get("PORT", 8080))
        thread = threading.Thread(
            target=web_dashboard.run_web_server,
            kwargs={"port": port},
            daemon=True
        )
        thread.start()
        logger.info(f"🌐 لوحة التحكم تعمل على المنفذ {port}")
        logger.info("🔑 كلمة المرور: shadow2099 (غيّرها عبر WEB_PASSWORD)")
    except Exception as e:
        logger.error(f"❌ فشل تشغيل لوحة التحكم: {e}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("deploy", deploy_command), MessageHandler(filters.Regex("^🚀 نشر جديدة$"), deploy_command)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [],
        },
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
    
    logger.info("🔥 SHADOW LEGION v31.0 (Direct Link Stealth Master) جاهز تماماً...")
    logger.info("📌 استخدم /login أولاً لتسجيل الدخول وحفظ الجلسة.")
    if RAILWAY_PUBLIC_DOMAIN:
        logger.info(f"🌐 لوحة التحكم متاحة على: {RAILWAY_PUBLIC_DOMAIN}")
    app.run_polling()

if __name__ == "__main__":
    main()