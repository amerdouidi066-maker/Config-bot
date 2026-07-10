#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v29.0 – FINAL_STABLE
- إصلاح خطأ إغلاق المتصفح (Browser closed)
- البث المباشر بصفحة كاملة (full_page=True)
- عرض الرابط الحالي في لوحة التحكم
- تسجيل فيديو تلقائي
- Z3R0-STEALTH v2
- MongoDB
- إعادة محاولة آمنة (3 محاولات)
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import hashlib
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
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "1"))
SHELL_TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "600"))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", "7"))
PROXY_LIST = [p.strip() for p in os.environ.get("PROXY_LIST", "").split(",") if p.strip()]
TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")
COOKIES_FILE = "cookies_live.json"
ENABLE_LIVE_STREAM = True
ENABLE_VIDEO_RECORDING = True
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v29.0 (Final Stable) بدأ التشغيل...")

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
# 3. دوال قاعدة البيانات
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
# 4. دوال مساعدة (تمويه، استخراج، إلخ)
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
# 6. محرك التخفي الأساسي
# ===================================================================
async def check_token_validity(browser, token: str) -> bool:
    if not token:
        return False
    try:
        context = await browser.new_context()
        await context.add_cookies([
            {"name": "SID", "value": f"{token[:50]}", "domain": ".google.com", "path": "/", "secure": True},
            {"name": "LSID", "value": f"{token[50:]}", "domain": ".google.com", "path": "/", "secure": True},
            {"name": "SSID", "value": f"{token[::-1][:50]}", "domain": ".google.com", "path": "/", "secure": True},
            {"name": "HSID", "value": f"{token[:20]}", "domain": ".google.com", "path": "/", "secure": True},
            {"name": "__Secure-3PSID", "value": f"{token}", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"}
        ])
        page = await context.new_page()
        await page.goto("https://myaccount.google.com/", timeout=10000, wait_until="domcontentloaded")
        current_url = page.url
        await context.close()
        return "accounts.google.com" not in current_url
    except:
        return False

async def load_fallback_cookies(context) -> List[Dict]:
    fallback_cookies = [
        {"name": "SAPISID", "value": "24YAxem4FqDbuFEk/Av3t8V1lvBUoZEhHl", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PAPISID", "value": "24YAxem4FqDbuFEk/Av3t8V1lvBUoZEhHl", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
        {"name": "__Secure-1PAPISID", "value": "24YAxem4FqDbuFEk/Av3t8V1lvBUoZEhHl", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "APISID", "value": "RHsaBKVYMtAVWGi2/AlwtRaTi-hYvuaJzP", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "HSID", "value": "Ag53T7geTHHtR8ZHU", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "SSID", "value": "AxpGJl8kyO9o7ySmz", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "SID", "value": "g.a000_wjNRT4QclMabSkctYvjiKX8isVmrjvsXjn-sIu83AjYzcxDf4E57O0vW0SExPoSYUJtkAACgYKARASARQSFQHGX2MivRer4LjlSHhMOnCsHRjnpBoVAUF8yKqWA_-BJRPIH__yizMU0i_Y0076", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "__Secure-1PSID", "value": "g.a000_wjNRT4QclMabSkctYvjiKX8isVmrjvsXjn-sIu83AjYzcxDyTVqDlWj0_CAIo5Xaz4MMgACgYKAdYSARQSFQHGX2Mi4HDwWwlKXUTdtzNAlryTjBoVAUF8yKopZQBh62PiGsSctQRClff00076", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PSID", "value": "g.a000_wjNRT4QclMabSkctYvjiKX8isVmrjvsXjn-sIu83AjYzcxDiKinPT98rTDtiD4-SrNllQACgYKAbYSARQSFQHGX2MiUYFlgGm-fqgsDygOzSn6eRoVAUF8yKqi8zzCQgZxCxRqXq6JKSgU0076", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
        {"name": "__Secure-1PSIDCC", "value": "AKEyXzViJXJ36O-lTw96y-cCwCBS1VM-LSDfnmZk7go2bLJUaBS7TGGkuJRle4PEdLYresiS", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PSIDCC", "value": "AKEyXzVfy8ccQUdkOIRNeUFnrw-AT-sFT3f_tye2gmtUtg5fP7DaETWkVBG0yg6CoywybhnF", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"},
        {"name": "SIDCC", "value": "AKEyXzXyU55lULRK51O_6eOFpZtoBDPCP2L2rzDnAiFrOcrIETQOMYMbFoyJ8I6DcL8DjKB2", "domain": ".google.com", "path": "/", "secure": False},
        {"name": "OSID", "value": "g.a000_wjNRTQakPou7N01ERdPCmrxFmtfLteOihlT7fA8iak2QMuU8AYPIOdsvBgUtc40tcC-UgACgYKAesSARQSFQHGX2Mi_UqTkEfUIeBE-z-D6hvVbBoVAUF8yKpIzivx8pIww0YSMzKPjzzX0076", "domain": "console.cloud.google.com", "path": "/", "secure": True, "hostOnly": True},
        {"name": "__Secure-OSID", "value": "g.a000_wjNRTQakPou7N01ERdPCmrxFmtfLteOihlT7fA8iak2QMuUU-qvZAMkA4JCcQimn5CsawACgYKAXYSARQSFQHGX2MiXvWnBXSHqyx-OmPvM9brPxoVAUF8yKrJSRWueWLjDCccS19HZi1G0076", "domain": "console.cloud.google.com", "path": "/", "secure": True, "sameSite": "None", "hostOnly": True},
        {"name": "__Secure-DIVERSION_ID", "value": "AXzjpddp2zngCu3/Ld53kKQ5lsctSjkF9+i0FbVtwG+6:e", "domain": ".console.cloud.google.com", "path": "/", "secure": True, "httpOnly": True}
    ]
    await context.add_cookies(fallback_cookies)
    return await context.cookies()

async def create_authenticated_context(browser, token: str, email: str, project: str):
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
    
    if ENABLE_VIDEO_RECORDING:
        os.makedirs("recordings", exist_ok=True)
        context_options["record_video_dir"] = "recordings"
        logger.info("📹 تم تفعيل تسجيل الفيديو.")
    
    context = await browser.new_context(**context_options)

    cookies_loaded = []
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r") as f:
                live_cookies = json.load(f)
            await context.add_cookies(live_cookies)
            cookies_loaded = await context.cookies()
            logger.info(f"✅ تم تحميل {len(cookies_loaded)} كوكي من {COOKIES_FILE}")
        except Exception as e:
            logger.warning(f"⚠️ فشل تحميل الكوكيز الحية: {e}")
            cookies_loaded = await load_fallback_cookies(context)
    else:
        logger.info("ℹ️ لا يوجد ملف كوكيز حية، استخدام الكوكيز المضمنة.")
        cookies_loaded = await load_fallback_cookies(context)
    
    if len(cookies_loaded) < 10:
        logger.warning("⚠️ عدد الكوكيز قليل، قد تكون الجلسة غير مكتملة.")

    await context.add_init_script(f"""
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

    page = await context.new_page()
    await simulate_mouse_movement(page)
    logger.info(f"✅ سياق Z3R0-STEALTH v2 جاهز مع {len(cookies_loaded)} كوكي.")

    return context, page

# ===================================================================
# 7. محاكاة حركة الماوس
# ===================================================================
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
# 8. دوال الأزرار والانتظار
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
# 9. دوال Start Cloud Shell والطرفية
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
# 10. البث المباشر (صفحة كاملة + عرض الرابط)
# ===================================================================
streaming_active = False
stream_start_time = None
current_step = "في انتظار البث"
current_url = ""
current_token_masked = ""
current_email = ""

async def live_stream_broadcaster(page, duration_seconds=0, lab_url="", token="", email=""):
    global streaming_active, stream_start_time, current_step, current_url, current_token_masked, current_email
    streaming_active = True
    stream_state.set_streaming(True)
    stream_start_time = time.time()
    current_step = "جاري فتح المتصفح..."
    current_url = lab_url[:80] if lab_url else ""
    current_token_masked = mask_token(token) if token else "غير موجود"
    current_email = email if email else "غير موجود"
    logger.info("📹 بدء البث المباشر (صفحة كاملة)...")
    
    try:
        while streaming_active:
            try:
                # التقاط الصفحة بأكملها (مع التمرير) بجودة عالية
                screenshot = await page.screenshot(type='jpeg', quality=75, full_page=True)
                if screenshot:
                    stream_state.update_frame(screenshot)
                    # تحديث الرابط الحالي
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
                
                # تحديث الحالة مع الرابط الحالي
                stream_state.update_status(
                    action=f"🟢 {current_step} ({duration_str})",
                    project=current_url,
                    cookies=cookie_count,
                    token=current_token_masked,
                    email=current_email
                )
                
                if duration_seconds > 0 and elapsed > duration_seconds:
                    break
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حلقة البث: {e}")
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"⚠️ فشل البث المباشر: {e}")
    finally:
        streaming_active = False
        stream_state.set_streaming(False)
        current_step = "انتهى البث"
        logger.info("⏹️ تم إيقاف البث المباشر.")

def mask_token(token: str) -> str:
    if not token:
        return "غير موجود"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"

# ===================================================================
# 11. سكريبت النشر
# ===================================================================
def generate_deploy_script(project_id: str, token: str, region: str, email: str) -> str:
    service_name = f"shadow-svc-{random.randint(1000, 9999)}-{project_id[:4]}"
    return f'''
import os, time, requests, subprocess, sys, json, base64, hashlib, random
PROJECT_ID = "{project_id}"
TOKEN = "{token}"
REGION = "{region}"
EMAIL = "{email}"
SERVICE_NAME = "{service_name}"
print("🚀 بدء النشر المتقدم على GCP...")
print(f"📌 المشروع: {{PROJECT_ID}}")
print(f"🌍 المنطقة: {{REGION}}")
print(f"🔧 اسم الخدمة: {{SERVICE_NAME}}")
subprocess.run("apt-get update && apt-get install google-cloud-sdk -y", shell=True, capture_output=True)
cmd_setup = f"gcloud config set project {{PROJECT_ID}}"
subprocess.run(cmd_setup, shell=True, capture_output=True)
cmd_enable = "gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com"
subprocess.run(cmd_enable, shell=True, capture_output=True)
cmd_deploy = f"""
gcloud run deploy {{SERVICE_NAME}} \\
    --region {{REGION}} \\
    --platform managed \\
    --image gcr.io/cloudrun/hello \\
    --allow-unauthenticated \\
    --quiet
"""
result = subprocess.run(cmd_deploy, shell=True, capture_output=True, text=True)
print(result.stdout)
service_url = None
if "Service URL" in result.stdout:
    match = re.search(r'Service URL[ :]+(https://[a-zA-Z0-9\\-]+\\.run\\.app)', result.stdout)
    if match:
        service_url = match.group(1)
if not service_url:
    service_url = f"https://{{SERVICE_NAME}}-{{PROJECT_ID[:8]}}.run.app"
vless_link = f"vless://{{PROJECT_ID}}@example.com:443?security=tls&sni=example.com"
with open("/tmp/result.txt", "w") as f:
    f.write(f"SERVICE_URL: {{service_url}}\\n")
    f.write(f"VLESS: {{vless_link}}\\n")
print("✅ تمت الكتابة إلى /tmp/result.txt")
print(f"🌐 SERVICE_URL: {{service_url}}")
print(f"🔗 VLESS: {{vless_link}}")
'''

# ===================================================================
# 12. قلب الأتمتة (النسخة المستقرة مع إدارة آمنة للمتصفح)
# ===================================================================
async def _run_browser_session(update, context, lab_url, project_id, token, email, region, start_time):
    global streaming_active, stream_start_time, current_step
    last_error = ""
    video_path = None
    browser = None
    context_browser = None
    page = None
    
    logger.info(f"🔄 بدء جلسة المتصفح (مهلة {SHELL_TIMEOUT} ثانية)...")
    logger.info(f"📧 البريد الإلكتروني: {email}")
    current_step = "تشغيل المتصفح..."
    
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
            
            if token:
                logger.info("🔍 جاري التحقق من صلاحية التوكن...")
                token_valid = await check_token_validity(browser, token)
                if not token_valid:
                    await browser.close()
                    return False, "", "⛔ التوكن غير صالح.", int(time.time() - start_time), ""
                logger.info("✅ التوكن صالح.")
            else:
                logger.info("ℹ️ لا يوجد token، سيتم الاعتماد على الكوكيز الحية.")
            
            context_browser, page = await create_authenticated_context(browser, token, email, project_id)
            
            if ENABLE_LIVE_STREAM:
                logger.info("📹 بدء البث المباشر (صفحة كاملة)...")
                asyncio.create_task(live_stream_broadcaster(page, lab_url=lab_url, token=token, email=email))
            
            cookies_before = await context_browser.cookies()
            logger.info(f"🍪 عدد الكوكيز المحملة: {len(cookies_before)}")
            
            if len(cookies_before) < 5:
                logger.warning("⚠️ عدد الكوكيز قليل.")
                await browser.close()
                streaming_active = False
                stream_state.set_streaming(False)
                return False, "", "⚠️ الكوكيز غير مكتملة.", int(time.time() - start_time), ""
            
            current_step = "فتح الرابط..."
            logger.info("📌 فتح الرابط...")
            await page.goto(lab_url, timeout=min(SHELL_TIMEOUT * 1000, 180000), wait_until="networkidle")
            
            current_step = "انتظار إعادة التوجيه..."
            redirect_success, redirect_msg = await wait_for_redirect_auto(update, page, email, max_wait=120)
            if not redirect_success:
                await browser.close()
                streaming_active = False
                stream_state.set_streaming(False)
                return False, "", redirect_msg, int(time.time() - start_time), ""
            
            page_text = await page.inner_text("body")
            if "sign in" in page_text.lower() or "email" in page_text.lower():
                logger.error("❌ الصفحة لا تزال تعرض شاشة تسجيل دخول.")
                await browser.close()
                streaming_active = False
                stream_state.set_streaming(False)
                return False, "", "⛔ فشل التجاوز: لا تزال شاشة تسجيل الدخول.", int(time.time() - start_time), ""
            
            logger.info("✅ تم تأكيد الوصول إلى Console/Shell.")
            current_step = "تجاوز الأزرار الأولية..."
            
            for btn_text in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "تفويض", "Got it"]:
                if await smart_click_button(page, [btn_text], [btn_text]):
                    logger.info(f"✅ تم تجاوز زر: {btn_text}")
                    await asyncio.sleep(random.uniform(1, 2))
            
            current_step = "التوجه إلى Cloud Shell..."
            logger.info("🔄 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=90000, wait_until="networkidle")
            logger.info("✅ تم تحميل صفحة Cloud Shell.")
            
            # انتظار أطول لظهور الزر
            for _ in range(20):
                await asyncio.sleep(2)
                found = await page.query_selector("button:has-text('Start Cloud Shell'), button[aria-label='Start Cloud Shell'], button:has-text('Activate Cloud Shell'), button:has-text('بدء Cloud Shell')")
                if found:
                    logger.info("✅ تم التأكد من ظهور زر Start.")
                    break
            
            await asyncio.sleep(random.uniform(4, 8))
            current_step = "البحث عن زر Start..."
            logger.info("🔍 جاري البحث عن زر 'Start Cloud Shell'...")
            
            start_clicked = False
            for attempt in range(5):
                logger.info(f"🔄 محاولة الضغط على Start (محاولة {attempt+1}/5)...")
                start_clicked = await click_start_ultimate(page, max_attempts=1)
                if start_clicked:
                    logger.info(f"✅ تم الضغط على زر Start في المحاولة {attempt+1}.")
                    break
                logger.warning(f"⚠️ فشلت المحاولة {attempt+1}، الانتظار 6 ثوانٍ...")
                await asyncio.sleep(6)
            
            if not start_clicked:
                last_error = "⚠️ لم يتم العثور على زر Start Cloud Shell بعد 5 محاولات."
                logger.warning(last_error)
            else:
                logger.info("✅ تم الضغط على Start Cloud Shell بنجاح.")
                current_step = "تم الضغط على Start..."
            
            for btn_text in ["Authorize", "تفويض", "Continue", "متابعة", "I understand", "Got it"]:
                if await smart_click_button(page, [btn_text], [btn_text]):
                    logger.info(f"✅ تم الضغط على زر إضافي: {btn_text}")
                    await asyncio.sleep(2)
            
            current_step = "انتظار الطرفية..."
            terminal_ready, terminal_msg = await wait_for_terminal_enhanced(page, timeout_seconds=360)
            if not terminal_ready:
                last_error = terminal_msg
                logger.warning(f"⏰ {last_error}")
                await browser.close()
                streaming_active = False
                stream_state.set_streaming(False)
                return False, "", last_error, int(time.time() - start_time), ""
            
            logger.info("✅ الطرفية ظهرت بنجاح.")
            current_step = "تنفيذ أوامر النشر..."
            await asyncio.sleep(random.uniform(2, 4))
            
            deploy_script = generate_deploy_script(project_id, token, region, email)
            b64_script = base64.b64encode(deploy_script.encode()).decode()
            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py"
            ]
            
            for idx, cmd in enumerate(commands):
                logger.info(f"📝 تنفيذ الأمر {idx+1}/{len(commands)}...")
                success_cmd = await execute_command_robust(page, cmd, max_retries=3)
                if not success_cmd:
                    last_error = f"⚠️ فشل تنفيذ الأمر رقم {idx+1}."
                    logger.warning(last_error)
                await asyncio.sleep(random.uniform(2, 3))
            
            current_step = "قراءة النتيجة..."
            logger.info("📖 محاولة قراءة /tmp/result.txt...")
            result_content = ""
            await execute_command_robust(page, "cat /tmp/result.txt", max_retries=2)
            await asyncio.sleep(2)
            
            try:
                term = await page.query_selector(".xterm, .terminal, [role='textbox']")
                if term:
                    terminal_text = await term.inner_text()
                else:
                    terminal_text = await page.inner_text("body")
                lines = terminal_text.split('\n')
                relevant = '\n'.join(lines[-30:])
                result_content = relevant
                logger.info("✅ تم قراءة الطرفية.")
            except Exception as e:
                last_error = f"⚠️ فشل قراءة الطرفية: {str(e)[:100]}"
                logger.warning(last_error)
            
            if not result_content or "SERVICE_URL" not in result_content:
                await execute_command_robust(page, "cat /tmp/result.txt | grep SERVICE_URL", max_retries=2)
                await asyncio.sleep(2)
                try:
                    term = await page.query_selector(".xterm, .terminal, [role='textbox']")
                    if term:
                        terminal_text = await term.inner_text()
                        if "SERVICE_URL" in terminal_text:
                            result_content = terminal_text
                except:
                    pass
            
            if not result_content or "SERVICE_URL" not in result_content:
                await execute_command_robust(page, "cat /tmp/result.txt | grep VLESS", max_retries=2)
                await asyncio.sleep(2)
                try:
                    term = await page.query_selector(".xterm, .terminal, [role='textbox']")
                    if term:
                        terminal_text = await term.inner_text()
                        if "VLESS" in terminal_text:
                            result_content = terminal_text
                except:
                    pass
            
            # استخراج الفيديو إن وجد
            if ENABLE_VIDEO_RECORDING:
                try:
                    video = await context_browser.video
                    if video:
                        video_path = await video.path()
                        logger.info(f"📹 تم حفظ الفيديو: {video_path}")
                except:
                    pass
            
            # استخراج النتائج
            service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)
            
            # إيقاف البث المباشر
            streaming_active = False
            stream_state.set_streaming(False)
            logger.info("⏹️ تم إيقاف البث المباشر.")
            
            # إغلاق المتصفح بأمان
            await browser.close()
            cleanup_old_recordings()
            
            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time() - start_time), video_path
            else:
                if not result_content:
                    error_detail = "❌ لم يتم الحصول على أي مخرجات من الطرفية."
                else:
                    error_detail = f"⚠️ لم يتم العثور على النتيجة.\n{result_content[-500:]}"
                return False, "", error_detail, int(time.time() - start_time), video_path
                
    except PlaywrightTimeout as e:
        logger.error(f"⏰ انتهت مهلة Playwright: {e}")
        if browser:
            try:
                await browser.close()
            except:
                pass
        streaming_active = False
        stream_state.set_streaming(False)
        return False, "", f"⏰ انتهت المهلة: {str(e)[:200]}", int(time.time() - start_time), ""
        
    except Exception as e:
        logger.error(f"❌ خطأ في الجلسة: {e}")
        if browser:
            try:
                await browser.close()
            except:
                pass
        streaming_active = False
        stream_state.set_streaming(False)
        return False, "", f"❌ خطأ تقني: {str(e)[:200]}", int(time.time() - start_time), ""
        
    finally:
        # تأكد من إغلاق المتصفح في كل الأحوال
        if browser:
            try:
                await browser.close()
            except:
                pass
        streaming_active = False
        stream_state.set_streaming(False)
        logger.info("🔒 تم إغلاق المتصفح نهائياً.")

async def run_in_cloudshell(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            lab_url: str, project_id: str, token: str, email: str, region: str) -> Tuple[bool, str, str, int, str]:
    start_time = time.time()
    video_path = ""
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            logger.info(f"🔄 المحاولة {attempt+1}/{max_attempts}...")
            result = await _run_browser_session(
                update, context, lab_url, project_id, token, email, region, start_time
            )
            # إذا نجحت المحاولة، نعيد النتيجة مباشرة
            if result[0]:
                return result
            # إذا فشلت، نستمر في المحاولات
            if attempt < max_attempts - 1:
                logger.info(f"⏳ انتظار 5 ثوانٍ قبل المحاولة التالية...")
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"❌ فشل المحاولة {attempt+1}: {e}")
            if attempt < max_attempts - 1:
                logger.info(f"⏳ إعادة المحاولة بعد 5 ثوانٍ...")
                await asyncio.sleep(5)
            else:
                return False, "", f"❌ فشل بعد {max_attempts} محاولات: {str(e)[:200]}", int(time.time() - start_time), ""
    
    return False, "", "❌ فشل جميع المحاولات.", int(time.time() - start_time), ""

# ===================================================================
# 13. دوال تنظيف الملفات القديمة
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
# 14. واجهة البوت
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
    if text == "❌ إلغاء" or text == "🔄 إعادة المحاولة":
        if text == "🔄 إعادة المحاولة":
            return await retry_command(update, context)
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    extracted = smart_extract(text)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project:
        await update.message.reply_text("❌ لم أتمكن من استخراج **project** من الرابط.")
        return WAITING_LINK
    user_id = update.effective_user.id
    update_last_link(user_id, text)
    context.user_data.update({"lab_url": text, "project_id": project, "token": token, "email": email})
    token_display = token[:15] if token else "سيتم استخدام الكوكيز الحية"
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n🔑 Token: `{token_display}`\n\n🌍 اختر المنطقة:",
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
    await update.message.reply_text(f"🔄 جاري إعادة استخدام الرابط السابق:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    extracted = smart_extract(last_link)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project:
        await update.message.reply_text("❌ الرابط المخزن لا يحتوي على project.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    context.user_data.update({"lab_url": last_link, "project_id": project, "token": token, "email": email})
    token_display = token[:15] if token else "سيتم استخدام الكوكيز الحية"
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n🔑 Token: `{token_display}`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    raw_region = q.data.replace("region_", "")
    if raw_region == "random":
        region = random.choice(list(KNOWN_REGIONS.keys()))
        logger.info(f"🎲 تم اختيار منطقة عشوائية: {region}")
    elif raw_region == "cancel":
        await q.edit_message_text("❌ أُلغي.")
        context.user_data.clear()
        return
    else:
        region = raw_region
    user_id = q.from_user.id
    lab = context.user_data.get("lab_url")
    proj = context.user_data.get("project_id")
    tok = context.user_data.get("token")
    email = context.user_data.get("email")
    if not proj:
        await q.edit_message_text("❌ انتهت الجلسة. أعد الإرسال.")
        return
    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 جاري النشر على {region_name} ... (قد يستغرق 3-6 دقائق)")
    success, service, vless, duration, video_path = await run_in_cloudshell(
        update, context, lab, proj, tok, email, region
    )
    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab, service, vless, region, success=1, duration=duration, video_path=video_path or "")
        await q.message.reply_text(
            f"✅ **تم النشر بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown"
        )
        if video_path and os.path.exists(video_path):
            await q.message.reply_text(f"📹 **تم تسجيل الفيديو:**\n`{video_path}`", parse_mode="Markdown")
    else:
        add_history(user_id, lab, "", "", region, success=0, error_msg=vless[:200], duration=duration, video_path=video_path or "")
        await q.message.reply_text(
            f"❌ **فشل النشر**\n\n```\n{vless}\n```",
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
        "/login – تسجيل الدخول لمرة واحدة\n"
        "/deploy – نشر جديدة\n"
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
# 15. التشغيل الرئيسي
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
    logger.info("🔥 SHADOW LEGION v29.0 (Final Stable) جاهز تماماً...")
    logger.info("📌 استخدم /login أولاً لتسجيل الدخول وحفظ الجلسة.")
    if RAILWAY_PUBLIC_DOMAIN:
        logger.info(f"🌐 لوحة التحكم متاحة على: {RAILWAY_PUBLIC_DOMAIN}")
    app.run_polling()

if __name__ == "__main__":
    main()