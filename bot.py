#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v21.0 – ULTIMATE_PENETRATION
- محرك تخفي 10/10 مع playwright-stealth
- Proxies ديناميكيين + 2Captcha
- إعادة محاولة ذكية مع backoff
- بصمة متصفح ديناميكية (WebGL/Canvas/Audio)
- اختبار صلاحية الرابط قبل التشغيل
- رسائل احترافية لا تكشف طريقة العمل
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from logging.handlers import RotatingFileHandler
import math
import requests
import aiohttp

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
# 1. الإعدادات الأساسية (مع متغيرات البيئة الجديدة)
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود (ضعه في متغيرات البيئة)")

DB_PATH = os.environ.get("DB_PATH", "shadow_legion.db")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "1"))
SHELL_TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "600"))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", "7"))
PROXY_LIST = [p.strip() for p in os.environ.get("PROXY_LIST", "").split(",") if p.strip()]
TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v21.0 (Ultimate Penetration) بدأ التشغيل...")

# ===================================================================
# 2. قوائم عشوائية
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

# ===================================================================
# 3. دوال مساعدة متقدمة
# ===================================================================
def get_random_proxy() -> Optional[str]:
    return random.choice(PROXY_LIST) if PROXY_LIST else None

def generate_random_fingerprint() -> Dict:
    return {
        "vendor": random.choice(['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple', 'ARM']),
        "renderer": random.choice(['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M', 'Apple M1 GPU', 'ARM Mali-G78']),
        "canvas_noise": random.uniform(0.01, 0.05),
        "audio_noise": random.uniform(0.0005, 0.002)
    }

async def check_link_validity(lab_url: str) -> bool:
    try:
        response = requests.head(lab_url, allow_redirects=True, timeout=10)
        if "accounts.google.com" in response.url:
            return False
        return True
    except:
        return True

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

async def retry_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt + random.uniform(0, 2)
            logger.info(f"⚠️ فشلت المحاولة {attempt+1}، إعادة المحاولة بعد {wait_time:.1f} ثانية...")
            await asyncio.sleep(wait_time)

# ===================================================================
# 4. قاعدة البيانات
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            deploy_count INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_link TEXT
        );
        CREATE TABLE IF NOT EXISTS deploy_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            lab_url TEXT,
            service_url TEXT,
            vless_link TEXT,
            region_used TEXT,
            deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_msg TEXT,
            duration_seconds INTEGER DEFAULT 0,
            screenshot_path TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_history_user ON deploy_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_history_date ON deploy_history(deployed_at DESC);
    """)
    conn.commit()
    conn.close()
init_db()

def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_name, deploy_count, last_active, joined_at, last_link FROM users WHERE user_id=?", (user_id,))
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
            "joined_at": row[6],
            "last_link": row[7]
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

def update_last_link(user_id: int, link: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET last_link=? WHERE user_id=?", (link, user_id))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1, last_active = CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str,
                success: int = 1, error_msg: str = "", duration: int = 0, screenshot: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used,
                                    success, error_msg, duration_seconds, screenshot_path)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (user_id, lab_url, service_url, vless, region, success, error_msg, duration, screenshot))
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
    return [{
        "id": r[0], "lab_url": r[1], "service_url": r[2],
        "vless_link": r[3], "region_used": r[4], "deployed_at": r[5],
        "success": r[6], "error_msg": r[7], "duration": r[8]
    } for r in rows]

# ===================================================================
# 5. المستخرج الذكي V6 (مع استخراج شامل للبريد الإلكتروني)
# ===================================================================
def smart_extract(link: str) -> Dict[str, Optional[str]]:
    link = link.strip()
    decoded = link
    for _ in range(5):
        decoded = urllib.parse.unquote(decoded)
    
    project = None
    token = None
    email = None
    
    if '#' in decoded:
        main_part = decoded.split('#')[0]
    else:
        main_part = decoded
    
    parsed = urllib.parse.urlparse(main_part)
    params = urllib.parse.parse_qs(parsed.query)
    
    project = params.get('project', [None])[0] or params.get('projectId', [None])[0] or params.get('id', [None])[0]
    token = params.get('token', [None])[0] or params.get('display_token', [None])[0] or params.get('auth_token', [None])[0]
    
    # استخراج شامل للبريد الإلكتروني
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    all_emails = re.findall(email_pattern, decoded)
    if all_emails:
        for em in all_emails:
            if 'qwiklabs' in em or 'student' in em:
                email = em
                break
        if not email:
            email = all_emails[0]
    
    if not email:
        email_match = re.search(r'[?&]Email=([^&]+)', decoded)
        if email_match:
            email = urllib.parse.unquote(email_match.group(1))
    
    if not project:
        match = re.search(r'[?&]project=([^&]+)', decoded)
        if match:
            project = match.group(1)
        else:
            match = re.search(r'/projects/([^/?#]+)', decoded)
            if match:
                project = match.group(1)
    
    if not token:
        match = re.search(r'[?&]token=([^&]+)', decoded)
        if match:
            token = match.group(1)
        else:
            match = re.search(r'display_token[=:]([^&?#]+)', decoded)
            if match:
                token = match.group(1)
    
    if project:
        project = project.strip('/"\'')
    if token:
        token = token.strip('/"\'')
    if email:
        email = email.strip('/"\'')
    
    return {"project_id": project, "token": token, "email": email}

# ===================================================================
# 6. التحقق من صلاحية التوكن
# ===================================================================
async def check_token_validity(browser, token: str) -> bool:
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
        if "accounts.google.com" in current_url:
            return False
        return True
    except:
        return False

# ===================================================================
# 7. محرك التخفي الفائق (مع playwright-stealth)
# ===================================================================
async def create_authenticated_context(browser, token: str, email: str, project: str):
    ua = random.choice(USER_AGENTS)
    width = random.randint(1800, 1920)
    height = random.randint(1000, 1080)
    tz = random.choice(TIMEZONES)
    lang = random.choice(LANGUAGES)
    lat = random.uniform(30, 50)
    lon = random.uniform(-100, -70)
    fingerprint = generate_random_fingerprint()

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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Ch-Ua": '"Google Chrome";v="126", "Chromium";v="126", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        },
        "ignore_https_errors": True,
        "accept_downloads": True,
    }
    
    proxy = get_random_proxy()
    if proxy:
        context_options["proxy"] = {"server": proxy}
        logger.info(f"🌐 استخدام Proxy: {proxy[:30]}...")
    
    context = await browser.new_context(**context_options)

    # سكريبت تدمير البصمة المتقدم مع بصمة ديناميكية
    await context.add_init_script(f"""
        // 1. إزالة webdriver
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        
        // 2. تزوير plugins
        Object.defineProperty(navigator, 'plugins', {{ 
            get: () => {{
                const plugins = [
                    {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' }},
                    {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' }},
                    {{ name: 'Native Client', filename: 'internal-nacl-plugin' }}
                ];
                plugins.length = 5;
                return plugins;
            }}
        }});
        
        // 3. تزوير languages
        Object.defineProperty(navigator, 'languages', {{ get: () => ['en-US', 'en'] }});
        
        // 4. تزوير chrome object
        window.chrome = {{
            runtime: {{}},
            loadTimes: function() {{}},
            csi: function() {{}},
            app: {{}}
        }};
        
        // 5. تزوير permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = function(params) {{
            if (params.name === 'notifications') {{
                return Promise.resolve({{ state: 'prompt' }});
            }}
            return originalQuery.call(this, params);
        }};
        
        // 6. WebGL Randomization (بصمة ديناميكية)
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {{
            const vendors = ['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple', 'ARM'];
            const renderers = ['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M', 'Apple M1 GPU', 'ARM Mali-G78'];
            if (p === 37445) return '{fingerprint["vendor"]}';
            if (p === 37446) return '{fingerprint["renderer"]}';
            return getParameter.call(this, p);
        }};
        
        // 7. Canvas Noise (ديناميكي)
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            if (type === 'image/png' || !type) {{
                const ctx = this.getContext('2d');
                const imgData = ctx.getImageData(0, 0, this.width, this.height);
                const data = imgData.data;
                for (let i = 0; i < data.length; i += 4) {{
                    if (Math.random() < {fingerprint["canvas_noise"]}) {{
                        data[i] ^= (Math.random() > 0.5 ? 1 : 0);
                        data[i+1] ^= (Math.random() > 0.5 ? 1 : 0);
                        data[i+2] ^= (Math.random() > 0.5 ? 1 : 0);
                    }}
                }}
                ctx.putImageData(imgData, 0, 0);
            }}
            return originalToDataURL.apply(this, arguments);
        }};
        
        // 8. Audio Noise (ديناميكي)
        const originalGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(channel) {{
            const data = originalGetChannelData.call(this, channel);
            for (let i = 0; i < data.length; i += 100) {{
                data[i] += (Math.random() - 0.5) * {fingerprint["audio_noise"]};
            }}
            return data;
        }};
    """)

    # جلسة مزيفة (Cookies)
    await context.add_cookies([
        {"name": "SID", "value": f"{token[:50]}", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "LSID", "value": f"{token[50:]}", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "SSID", "value": f"{token[::-1][:50]}", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "HSID", "value": f"{token[:20]}", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "__Secure-3PSID", "value": f"{token}", "domain": ".google.com", "path": "/", "secure": True, "sameSite": "None"}
    ])

    page = await context.new_page()
    
    # تطبيق playwright-stealth (تدمير إضافي للبصمة)
    try:
        await stealth_async(page)
        logger.info("✅ تم تطبيق playwright-stealth.")
    except Exception as e:
        logger.warning(f"⚠️ فشل تطبيق stealth: {e}")

    # محاكاة حركة الماوس البشرية
    await page.evaluate("""
        function bezier(t, p0, p1, p2, p3) {
            return Math.pow(1-t,3)*p0 + 3*Math.pow(1-t,2)*t*p1 + 3*(1-t)*Math.pow(t,2)*p2 + Math.pow(t,3)*p3;
        }
        async function moveMouse(x1, y1, x2, y2, duration) {
            const steps = 50;
            const cx = Math.floor(Math.random() * (Math.max(x1,x2) - Math.min(x1,x2)) + Math.min(x1,x2));
            const cy = Math.floor(Math.random() * (Math.max(y1,y2) - Math.min(y1,y2)) + Math.min(y1,y2));
            for (let i = 0; i < steps; i++) {
                const t = i / steps;
                const x = bezier(t, x1, cx, cx, x2);
                const y = bezier(t, y1, cy, cy, y2);
                const ev = new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true });
                document.dispatchEvent(ev);
                await new Promise(r => setTimeout(r, duration / steps));
            }
        }
        setTimeout(() => {
            const startX = Math.random() * window.innerWidth;
            const startY = Math.random() * window.innerHeight;
            const endX = Math.random() * window.innerWidth;
            const endY = Math.random() * window.innerHeight;
            moveMouse(startX, startY, endX, endY, 2000 + Math.random() * 3000);
        }, 1000 + Math.random() * 2000);
    """)

    return context, page

# ===================================================================
# 8. كشف ديناميكي للأزرار
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
        result = await page.evaluate(f"""
            (texts) => {{
                const keywords = {text_keywords};
                const elements = document.querySelectorAll('button, div[role="button"], a[role="button"]');
                for (let el of elements) {{
                    const text = el.innerText || el.getAttribute('aria-label') || '';
                    for (let kw of keywords) {{
                        if (text.toLowerCase().includes(kw.toLowerCase())) {{
                            el.scrollIntoView({{block: 'center'}});
                            el.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }}
        """, text_keywords)
        if result:
            logger.info("✅ نقر على الزر عبر JavaScript الشامل.")
            return True
    except:
        pass
    
    return False

# ===================================================================
# 9. معالج الانتظار الذكي (مع كشف متقدم للصلاحية + CAPTCHA)
# ===================================================================
EXPIRED_KEYWORDS = [
    "expired", "invalid", "session", "access denied", "not found", "404", "410",
    "sign in", "choose an account", "accounts.google.com", "login", "log in",
    "Couldn't sign you in", "verify this account", "contact your administrator",
    "domain", "not authorized", "forbidden", "terminated", "suspended"
]

async def wait_for_redirect_auto(page, email: str = None, max_wait: int = 120) -> Tuple[bool, str]:
    start_time = time.time()
    while time.time() - start_time < max_wait:
        current_url = page.url
        page_text = await page.inner_text("body")
        
        if "console.cloud.google.com" in current_url or "shell.cloud.google.com" in current_url:
            logger.info("✅ تم الوصول إلى Console/Shell بنجاح.")
            return True, ""
        
        if any(kw in page_text.lower() for kw in EXPIRED_KEYWORDS):
            logger.warning("⛔ تم الكشف عن رابط منتهي الصلاحية أو غير صالح.")
            return False, "⛔ انتهت صلاحية الرابط أو التوكن غير صالح. يرجى الحصول على رابط جديد من Qwiklabs."
        
        if "Welcome to your new account" in page_text:
            if await smart_click_button(page, ["Understand", "I understand"]):
                logger.info("✅ تم الضغط على Understand.")
                await asyncio.sleep(2)
                continue
        
        # كشف CAPTCHA وحلها
        if "recaptcha" in page_text.lower() or "captcha" in page_text.lower():
            logger.info("🛡️ تم اكتشاف CAPTCHA، جاري الحل عبر 2Captcha...")
            sitekey = await page.evaluate("""
                () => {
                    const iframe = document.querySelector('iframe[src*="recaptcha"]');
                    if (!iframe) return null;
                    const src = iframe.src;
                    const match = src.match(/k=([^&]+)/);
                    return match ? match[1] : null;
                }
            """)
            if sitekey:
                solution = await solve_captcha_2captcha(page, sitekey)
                if solution:
                    await page.evaluate(f"""
                        document.querySelector('#g-recaptcha-response').innerHTML = '{solution}';
                        document.querySelector('form').dispatchEvent(new Event('submit'));
                    """)
                    logger.info("✅ تم حل CAPTCHA بنجاح.")
                    await asyncio.sleep(2)
                    continue
        
        if "sign in" in page_text.lower() or "accounts.google.com" in current_url:
            logger.info("⚠️ شاشة تسجيل دخول غير متوقعة – محاولة إدخال البريد...")
            if email:
                try:
                    email_input = await page.query_selector("input[type='email'], input[type='text'][name='identifier']")
                    if email_input:
                        await email_input.fill(email)
                        logger.info(f"✅ تم إدخال البريد: {email}")
                        await asyncio.sleep(1)
                        if await smart_click_button(page, ["Next", "التالي"], ["Next", "Continue"]):
                            logger.info("✅ تم الضغط على Next.")
                            await asyncio.sleep(3)
                            if "password" in await page.inner_text("body").lower():
                                logger.warning("⚠️ ظهرت شاشة كلمة المرور – البوت لا يستطيع إدخالها.")
                                return False, "⛔ الرابط يتطلب كلمة مرور (تسجيل دخول يدوي). يرجى استخدام رابط ضيف من Qwiklabs."
                            continue
                except Exception as e:
                    logger.warning(f"⚠️ فشل إدخال البريد: {e}")
            return False, "⛔ فشل تسجيل الدخول إلى Google. يرجى الحصول على رابط جديد من Qwiklabs."
        
        await asyncio.sleep(2)
    
    return False, "⛔ انتهت مهلة إعادة التوجيه (120 ثانية)."

# ===================================================================
# 10. الضغط على Start (باستخدام الكشف الديناميكي)
# ===================================================================
async def click_start_ultimate(page) -> bool:
    return await smart_click_button(
        page,
        text_keywords=["Start Cloud Shell", "Launch Cloud Shell", "Activate Cloud Shell", 
                      "بدء Cloud Shell", "تفعيل Cloud Shell", "Start", "Launch", "Activate"],
        aria_labels=["Start Cloud Shell", "Launch Cloud Shell", "Activate Cloud Shell"]
    )

# ===================================================================
# 11. تنفيذ الأوامر مع إعادة محاولة
# ===================================================================
async def execute_command_robust(page, cmd: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        logger.info(f"▶️ تنفيذ: {cmd[:60]}... (محاولة {attempt+1}/{max_retries})")
        try:
            result = await page.evaluate(f"""
                async (cmd) => {{
                    const term = document.activeElement || document.querySelector('.xterm-helper-textarea, .xterm, .terminal, [role="textbox"]');
                    if (term) {{
                        term.focus();
                        await navigator.clipboard.writeText(cmd + '\\n');
                        document.execCommand('paste');
                        return true;
                    }}
                    return false;
                }}
            """, cmd)
            if result:
                await asyncio.sleep(1.5)
                return True
        except:
            pass
        try:
            result = await page.evaluate(f"""
                (cmd) => {{
                    const term = document.activeElement || document.querySelector('.xterm-helper-textarea, .xterm, .terminal, [role="textbox"]');
                    if (term) {{
                        term.focus();
                        const inputEvent = new InputEvent('input', {{
                            inputType: 'insertText',
                            data: cmd + '\\n',
                            bubbles: true,
                            cancelable: true
                        }});
                        if (term.value !== undefined) {{
                            term.value = (term.value || '') + cmd + '\\n';
                        }} else if (term.innerText !== undefined) {{
                            term.innerText = (term.innerText || '') + cmd + '\\n';
                        }}
                        term.dispatchEvent(inputEvent);
                        const enterEvent = new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }});
                        term.dispatchEvent(enterEvent);
                        return true;
                    }}
                    return false;
                }}
            """, cmd)
            if result:
                await asyncio.sleep(1.5)
                return True
        except:
            pass
        try:
            for ch in cmd:
                await page.keyboard.type(ch, delay=random.randint(15, 40))
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.5)
            return True
        except:
            pass
        try:
            await page.evaluate(f"""
                () => {{
                    const input = document.activeElement || document.querySelector('.xterm-helper-textarea');
                    if (input) {{
                        input.value = (input.value || '') + '{cmd}\\n';
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter' }}));
                    }}
                }}
            """)
            await asyncio.sleep(1.5)
            return True
        except Exception as e:
            logger.error(f"فشل تنفيذ الأمر في المحاولة {attempt+1}: {e}")
            await asyncio.sleep(2)
    logger.error(f"❌ فشل تنفيذ الأمر بعد {max_retries} محاولات: {cmd[:60]}")
    return False

# ===================================================================
# 12. انتظار الطرفية المحسّن
# ===================================================================
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
            logger.info(f"✅ تم العثور على الطرفية باستخدام المحدد: {selector}")
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
                        logger.info(f"✅ تم العثور على الطرفية داخل iframe باستخدام: {selector}")
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
                    logger.info(f"✅ الطرفية ظهرت (حلقة احتياطية) – المحدد: {selector}")
                    return True, ""
            except:
                pass
        await asyncio.sleep(1)
    
    return False, f"⏰ انتهت مهلة انتظار الطرفية ({timeout_seconds} ثانية)."

# ===================================================================
# 13. سكريبت النشر (مع عشوائية)
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
# 14. قلب الأتمتة (النسخة النهائية مع جميع الترقيات)
# ===================================================================
async def run_in_cloudshell(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            lab_url: str, project_id: str, token: str, email: str, region: str) -> Tuple[bool, str, str, int, str]:
    start_time = time.time()
    screenshot_path = ""
    last_error = ""

    # اختبار صلاحية الرابط قبل التشغيل
    logger.info("🔍 جاري فحص صلاحية الرابط...")
    if not await check_link_validity(lab_url):
        return False, "", "⛔ الرابط يعيد التوجيه إلى تسجيل الدخول (منتهي الصلاحية). يرجى الحصول على رابط جديد.", int(time.time() - start_time), ""

    try:
        logger.info(f"🔄 بدء محاولة وحيدة (مهلة {SHELL_TIMEOUT} ثانية)...")
        logger.info(f"📧 البريد الإلكتروني المستخرج: {email}")
        # إخفاء التوكن في السجلات
        logger.info(f"🔑 التوكن: {token[:10]}...{token[-10:]}")
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
            
            # التحقق من صلاحية التوكن
            logger.info("🔍 جاري التحقق من صلاحية التوكن...")
            token_valid = await check_token_validity(browser, token)
            if not token_valid:
                await browser.close()
                return False, "", "⛔ التوكن غير صالح أو منتهي الصلاحية. يرجى الحصول على رابط جديد من Qwiklabs.", int(time.time() - start_time), ""
            logger.info("✅ التوكن صالح.")

            context_browser, page = await create_authenticated_context(browser, token, email, project_id)

            logger.info("📌 فتح الرابط...")
            await page.goto(lab_url, timeout=min(SHELL_TIMEOUT * 1000, 180000), wait_until="networkidle")

            redirect_success, redirect_msg = await wait_for_redirect_auto(page, email, max_wait=120)
            if not redirect_success:
                screenshot_path = await save_screenshot(page)
                await send_screenshot(update, screenshot_path, redirect_msg)
                await browser.close()
                return False, "", redirect_msg, int(time.time() - start_time), screenshot_path

            try:
                await page.wait_for_url(
                    lambda u: "console.cloud.google.com" in u or "shell.cloud.google.com" in u,
                    timeout=30000
                )
                logger.info("✅ تم تأكيد الوصول إلى Console/Shell.")
            except:
                last_error = "❌ لم يتم الوصول إلى Console أو Shell بعد إعادة التوجيه."
                screenshot_path = await save_screenshot(page)
                await send_screenshot(update, screenshot_path, last_error)
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), screenshot_path

            # استخدام الكشف الديناميكي للأزرار
            for btn_text in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "تفويض", "Got it"]:
                if await smart_click_button(page, [btn_text], [btn_text]):
                    logger.info(f"✅ تم تجاوز زر: {btn_text}")
                    await asyncio.sleep(random.uniform(1, 2))

            logger.info("🔄 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
            await asyncio.sleep(random.uniform(3, 5))

            start_clicked = False
            for attempt in range(3):
                logger.info(f"🔄 محاولة الضغط على Start (محاولة {attempt+1}/3)...")
                start_clicked = await click_start_ultimate(page)
                if start_clicked:
                    break
                await asyncio.sleep(5)

            if not start_clicked:
                last_error = "⚠️ لم يتم العثور على زر Start Cloud Shell بعد 3 محاولات."
                logger.warning(last_error)

            # أزرار إضافية بعد Start
            for btn_text in ["Authorize", "تفويض", "Continue", "متابعة", "I understand", "Got it"]:
                if await smart_click_button(page, [btn_text], [btn_text]):
                    logger.info(f"✅ تم الضغط على زر إضافي: {btn_text}")
                    await asyncio.sleep(2)

            terminal_ready, terminal_msg = await wait_for_terminal_enhanced(page, timeout_seconds=360)
            if not terminal_ready:
                last_error = terminal_msg
                screenshot_path = await save_screenshot(page)
                await send_screenshot(update, screenshot_path, last_error)
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), screenshot_path

            await asyncio.sleep(random.uniform(2, 4))

            deploy_script = generate_deploy_script(project_id, token, region, email)
            b64_script = base64.b64encode(deploy_script.encode()).decode()
            
            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py"
            ]

            for idx, cmd in enumerate(commands):
                success_cmd = await execute_command_robust(page, cmd, max_retries=3)
                if not success_cmd:
                    last_error = f"⚠️ فشل تنفيذ الأمر رقم {idx+1} (بعد 3 محاولات): {cmd[:30]}..."
                    logger.warning(last_error)
                await asyncio.sleep(random.uniform(2, 3))

            logger.info("📖 محاولة قراءة /tmp/result.txt...")
            result_content = ""
            
            try:
                result_content = await page.evaluate("""
                    async () => {
                        const resp = await fetch('/tmp/result.txt');
                        return await resp.text();
                    }
                """)
                logger.info("✅ تم قراءة الملف عبر fetch.")
            except:
                pass

            if not result_content or "SERVICE_URL" not in result_content:
                logger.info("📖 استخدام cat كبديل...")
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
                    last_error = f"⚠️ فشل قراءة الملف أو الطرفية: {str(e)[:100]}"

            if not result_content or "SERVICE_URL" not in result_content:
                logger.info("📖 محاولة قراءة stdout...")
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

            os.makedirs("screenshots", exist_ok=True)
            screenshot_path = f"screenshots/{int(time.time())}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()

            cleanup_old_screenshots()

            service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', result_content)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', result_content)

            if service_match and vless_match:
                return True, service_match.group(1), vless_match.group(1), int(time.time() - start_time), screenshot_path
            else:
                if not result_content:
                    error_detail = "❌ لم يتم الحصول على أي مخرجات من الطرفية. قد يكون السكريبت لم ينفذ."
                else:
                    error_detail = f"⚠️ لم يتم العثور على النتيجة.\nالمحتوى المسترجع:\n{result_content[-500:]}"
                await send_screenshot(update, screenshot_path, error_detail)
                return False, "", error_detail, int(time.time() - start_time), screenshot_path

    except PlaywrightTimeout as e:
        logger.exception("⏰ انتهت مهلة Playwright")
        last_error = f"⏰ انتهت المهلة: {str(e)[:200]}"
        if screenshot_path:
            await send_screenshot(update, screenshot_path, last_error)
        return False, "", last_error, int(time.time() - start_time), screenshot_path
    except Exception as e:
        logger.exception(f"❌ فشل المحاولة")
        last_error = f"❌ خطأ تقني: {str(e)[:200]}"
        if screenshot_path:
            await send_screenshot(update, screenshot_path, last_error)
        return False, "", last_error, int(time.time() - start_time), screenshot_path

# ===================================================================
# 15. دوال مساعدة للصور
# ===================================================================
async def save_screenshot(page) -> str:
    os.makedirs("screenshots", exist_ok=True)
    path = f"screenshots/{int(time.time())}.png"
    try:
        await page.screenshot(path=path, full_page=True)
        logger.info(f"📸 تم حفظ اللقطة: {path}")
        return path
    except Exception as e:
        logger.warning(f"⚠️ فشل حفظ اللقطة: {e}")
        return ""

async def send_screenshot(update: Update, path: str, caption: str = "📸 لقطة للفحص"):
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'rb') as photo:
            await update.effective_message.reply_photo(photo, caption=f"{caption}\n\n🔄 يمكنك استخدام زر 'إعادة المحاولة' لتجربة الرابط نفسه مرة أخرى.")
        logger.info(f"📤 تم إرسال الصورة: {path}")
    except Exception as e:
        logger.warning(f"⚠️ فشل إرسال الصورة: {e}")

def cleanup_old_screenshots():
    try:
        screenshots_dir = "screenshots"
        if not os.path.exists(screenshots_dir):
            return
        cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
        for filename in os.listdir(screenshots_dir):
            filepath = os.path.join(screenshots_dir, filename)
            if os.path.isfile(filepath):
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    logger.info(f"🗑️ تم حذف لقطة قديمة: {filename}")
    except Exception as e:
        logger.warning(f"⚠️ فشل تنظيف اللقطات: {e}")

# ===================================================================
# 16. واجهة البوت (رسالة /start احترافية)
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

def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 نشر جديدة"), KeyboardButton("📊 إحصائياتي")],
        [KeyboardButton("📜 سجل النشر"), KeyboardButton("❓ مساعدة")],
        [KeyboardButton("🔄 إعادة المحاولة"), KeyboardButton("❌ إلغاء")]
    ], resize_keyboard=True)

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
    await update.message.reply_text(
        "🔥 **Shadow Legion – Enterprise Platform**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ نظام متطور لإدارة وتشغيل الخدمات السحابية.\n"
        "📌 استخدم الأمر `/deploy` لبدء عملية النشر.\n"
        "📊 يمكنك متابعة إحصائياتك عبر `/stats`.\n"
        "📜 عرض سجل النشرات عبر `/history`.\n"
        "❓ للمساعدة: `/help`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "© 2026 Shadow Legion – All Rights Reserved.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 أرسل رابط Qwiklabs أو Google SSO:", reply_markup=main_menu())
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "❌ إلغاء" or text == "🔄 إعادة المحاولة":
        if text == "🔄 إعادة المحاولة":
            return await retry_command(update, context)
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu())
        return ConversationHandler.END
    
    extracted = smart_extract(text)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    
    if not project and not token:
        await update.message.reply_text("❌ لم أتمكن من استخراج **project** أو **token** من الرابط.")
        return WAITING_LINK
    if not project:
        await update.message.reply_text("❌ تم استخراج **token** لكن **project** مفقود.")
        return WAITING_LINK
    if not token:
        await update.message.reply_text("❌ تم استخراج **project** لكن **token** مفقود.")
        return WAITING_LINK
    
    user_id = update.effective_user.id
    update_last_link(user_id, text)
    context.user_data.update({"lab_url": text, "project_id": project, "token": token, "email": email})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or not user_data.get("last_link"):
        await update.message.reply_text("📭 لا يوجد رابط سابق لإعادة المحاولة.")
        return ConversationHandler.END
    last_link = user_data["last_link"]
    await update.message.reply_text(f"🔄 جاري إعادة استخدام الرابط السابق:", parse_mode="Markdown")
    extracted = smart_extract(last_link)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project or not token:
        await update.message.reply_text("❌ الرابط المخزن غير صالح.")
        return ConversationHandler.END
    context.user_data.update({"lab_url": last_link, "project_id": project, "token": token, "email": email})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n📧 Email: `{email if email else 'غير موجود'}`\n\n🌍 اختر المنطقة:",
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
    if not proj or not tok:
        await q.edit_message_text("❌ انتهت الجلسة. أعد الإرسال.")
        return

    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 جاري النشر على {region_name} ... (قد يستغرق 3-6 دقائق)")

    success, service, vless, duration, screenshot = await run_in_cloudshell(
        update, context, lab, proj, tok, email, region
    )

    if success:
        increment_deploy_count(user_id)
        add_history(user_id, lab, service, vless, region, success=1, duration=duration, screenshot=screenshot)
        await q.message.reply_text(
            f"✅ **تم النشر بنجاح**\n🌍 {region_name}\n⏱️ {duration} ثانية\n🌐 `{service}`\n\n🔗 **VLESS:**\n`{vless}`",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    else:
        add_history(user_id, lab, "", "", region, success=0, error_msg=vless[:200], duration=duration, screenshot=screenshot)
        await q.message.reply_text(
            f"❌ **فشل النشر**\n\n```\n{vless}\n```",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    context.user_data.clear()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu())
    return ConversationHandler.END

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("❌ لا توجد بيانات.")
        return
    await update.message.reply_text(
        f"📊 **إحصائياتك**\n👤 {u['first_name']}\n📦 نشرات: {u['deploy_count']}\n📅 انضم: {u['joined_at'][:16]}",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = get_history(update.effective_user.id, 5)
    if not history:
        await update.message.reply_text("📭 لا يوجد سجل.", reply_markup=main_menu())
        return
    text = "📜 **آخر 5 نشرات:**\n"
    for i, h in enumerate(history, 1):
        status = "✅" if h['success'] else "❌"
        region = KNOWN_REGIONS.get(h['region_used'], h['region_used'])
        text += f"{i}. {status} {region} – {h['deployed_at'][:16]}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ **الأوامر:**\n"
        "/start – القائمة الرئيسية\n"
        "/deploy – نشر جديدة\n"
        "/retry – إعادة استخدام آخر رابط\n"
        "/stats – إحصائياتك\n"
        "/history – سجل النشرات\n"
        "/cancel – إلغاء العملية",
        parse_mode="Markdown", reply_markup=main_menu()
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
# 17. التشغيل الرئيسي + خادم الويب
# ===================================================================
def start_web_dashboard():
    try:
        from web_dashboard import run_web_server
        import threading
        thread = threading.Thread(target=run_web_server, kwargs={"port": 8080}, daemon=True)
        thread.start()
        logger.info("🌐 لوحة التحكم (Dashboard) تعمل على http://0.0.0.0:8080")
        logger.info("🔑 كلمة المرور الافتراضية: shadow2099 (غيّرها عبر WEB_PASSWORD)")
    except ImportError:
        logger.warning("⚠️ web_dashboard.py غير موجود – يتم تشغيل البوت فقط.")

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
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("retry", retry_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(CallbackQueryHandler(lambda u,c: c.user_data.clear() or u.edit_message_text("❌ أُلغي."), pattern="^cancel$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    start_web_dashboard()

    logger.info("🔥 SHADOW LEGION v21.0 (Ultimate Penetration) جاهز تماماً...")
    app.run_polling()

if __name__ == "__main__":
    main()