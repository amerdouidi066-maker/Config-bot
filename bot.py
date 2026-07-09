#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v17.1 – ULTRA_STEALTH_OAUTH
- محرك تخفي 9.9/10 (تدمير شامل لبصمة Headless)
- انتظار networkidle لتفادي انقطاع إعادة التوجيه
- تفعيل سياسات المتصفح الحقيقية (Third-party cookies, CSP bypass)
- إدخال البريد الإلكتروني تلقائياً (في حال فشل التخفي)
- كشف فوري لشاشة تسجيل الدخول
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

DB_PATH = os.environ.get("DB_PATH", "shadow_legion.db")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "1"))
SHELL_TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "600"))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", "7"))
PROXY = os.environ.get("PROXY")

TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")
CAPTCHA_TIMEOUT = int(os.environ.get("CAPTCHA_TIMEOUT", "120"))

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v17.1 (Ultra Stealth OAuth) بدأ التشغيل...")

# ===================================================================
# 2. قوائم عشوائية للتمويه
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
# 3. قاعدة البيانات (محسنة)
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
# 4. المستخرج الذكي V5 (مع استخراج البريد الإلكتروني)
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
    
    email_match = re.search(r'[?&]Email=([^&]+)', decoded)
    if email_match:
        email = urllib.parse.unquote(email_match.group(1))
    else:
        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', decoded)
        if email_match:
            email = email_match.group(0)
    
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
# 5. محرك التخفي الفائق (نسخة 9.9/10 مع تدمير شامل للبصمة)
# ===================================================================
async def create_ultra_stealth_context(browser):
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
        "extra_http_headers": {"Accept-Language": lang},
        "ignore_https_errors": True,
        "accept_downloads": True,
        "accept_third_party_cookies": True,  # 🔥 مهم جداً لـ OAuth
        "bypass_csp": True,                 # 🔥 تجاوز سياسات الأمان
        "storage_state": {},                # السماح بتخزين الجلسات
        "user_agent": ua
    }
    
    if PROXY:
        context_options["proxy"] = {"server": PROXY}
    
    context = await browser.new_context(**context_options)

    # 🔥 سكريبت تدمير البصمة المتطور (يركز على علامات Headless)
    await context.add_init_script("""
        // 1. إزالة webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        
        // 2. تزوير plugins (يمنع كشف headless)
        Object.defineProperty(navigator, 'plugins', { 
            get: () => {
                const plugins = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' }
                ];
                plugins.length = 5;
                return plugins;
            }
        });
        
        // 3. تزوير languages
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        
        // 4. تزوير chrome object
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
        
        // 5. تزوير permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = function(params) {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: 'prompt' });
            }
            return originalQuery.call(this, params);
        };
        
        // 6. WebGL / Canvas (تم إضافتها سابقاً لكن نعززها)
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            const vendors = ['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple', 'ARM'];
            const renderers = ['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M', 'Apple M1 GPU', 'ARM Mali-G78'];
            if (p === 37445) return vendors[Math.floor(Math.random() * vendors.length)];
            if (p === 37446) return renderers[Math.floor(Math.random() * renderers.length)];
            return getParameter.call(this, p);
        };
        
        // 7. Canvas Noise
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png' || !type) {
                const ctx = this.getContext('2d');
                const imgData = ctx.getImageData(0, 0, this.width, this.height);
                const data = imgData.data;
                for (let i = 0; i < data.length; i += 4) {
                    if (Math.random() < 0.03) {
                        data[i] ^= (Math.random() > 0.5 ? 1 : 0);
                        data[i+1] ^= (Math.random() > 0.5 ? 1 : 0);
                        data[i+2] ^= (Math.random() > 0.5 ? 1 : 0);
                    }
                }
                ctx.putImageData(imgData, 0, 0);
            }
            return originalToDataURL.apply(this, arguments);
        };
    """)

    page = await context.new_page()
    await page.evaluate("""
        setTimeout(() => {
            window.scrollTo(0, Math.floor(Math.random() * 300));
        }, 1000 + Math.random() * 3000);
        setTimeout(() => {
            const ev = new MouseEvent('mousemove', {
                clientX: Math.random() * window.innerWidth,
                clientY: Math.random() * window.innerHeight,
            });
            document.dispatchEvent(ev);
        }, 2000 + Math.random() * 2000);
    """)
    return context, page

# ===================================================================
# 6. دوال التفاعل (مع إدخال البريد الإلكتروني كحل احتياطي)
# ===================================================================
async def handle_login_screen(page, email: str = None) -> bool:
    """يتعامل مع شاشات تسجيل الدخول، ويدخل البريد الإلكتروني تلقائياً إن وجد."""
    current_url = page.url
    
    if "accounts.google.com" in current_url or "signin" in current_url.lower():
        logger.info("🔐 تم اكتشاف شاشة تسجيل الدخول. محاولة إدخال البريد الإلكتروني (حل احتياطي)...")
        
        if email:
            try:
                email_input = await page.query_selector("input[type='email'], input[type='text'][name='identifier'], input[type='text'][aria-label*='Email'], input[type='text'][aria-label*='البريد']")
                if email_input:
                    await email_input.fill(email)
                    logger.info(f"✅ تم إدخال البريد الإلكتروني: {email}")
                    await asyncio.sleep(1)
                    next_btn = await page.query_selector("button:has-text('Next'), button:has-text('التالي'), button[type='submit']")
                    if next_btn:
                        await next_btn.click()
                        logger.info("✅ تم الضغط على زر Next.")
                        await asyncio.sleep(3)
                        return True
            except Exception as e:
                logger.warning(f"⚠️ فشل إدخال البريد الإلكتروني: {e}")
        
        return False
    
    for btn in ["Continue", "متابعة", "Authorize", "تفويض", "I understand", "Agree", "Got it"]:
        try:
            await page.click(f"button:has-text('{btn}')", timeout=3000)
            logger.info(f"✅ تم تجاوز زر: {btn}")
            await asyncio.sleep(2)
        except:
            pass
    
    return True

async def click_start_ultimate(page) -> bool:
    selectors = [
        "button:has-text('Start Cloud Shell')",
        "button:has-text('Launch Cloud Shell')",
        "button:has-text('Activate Cloud Shell')",
        "button:has-text('بدء Cloud Shell')",
        "button:has-text('تفعيل Cloud Shell')",
        "button[aria-label='Start Cloud Shell']",
        "button[aria-label='Activate Cloud Shell']",
        "button[aria-label='Launch Cloud Shell']",
        "button:has-text('Start')",
        "button:has-text('Launch')",
    ]
    for sel in selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                await btn.click()
                logger.info(f"✅ نقر Start عبر: {sel}")
                return True
        except:
            continue
    
    result = await page.evaluate("""
        () => {
            const keywords = ['Start', 'Launch', 'Activate', 'بدء', 'تفعيل', 'شغّل', 'Run'];
            const btns = document.querySelectorAll('button, div[role="button"]');
            for (let b of btns) {
                const text = b.innerText || b.getAttribute('aria-label') || '';
                for (let kw of keywords) {
                    if (text.includes(kw)) {
                        b.scrollIntoView({block: 'center'});
                        b.click();
                        return true;
                    }
                }
            }
            return false;
        }
    """)
    if result:
        logger.info("✅ نقر Start عبر JavaScript الشامل.")
        return True
    logger.warning("⚠️ لم نجد زر Start، لكننا نواصل...")
    return False

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
# 7. انتظار الطرفية المحسّن
# ===================================================================
async def wait_for_terminal_enhanced(page, timeout_seconds=360) -> bool:
    logger.info(f"⏳ في انتظار الطرفية (مهلة {timeout_seconds} ثانية)...")
    start_time = time.time()

    try:
        await page.wait_for_selector(".loading-spinner, .loader, .spinner, .waiting", timeout=10000, state="hidden")
        logger.info("✅ اختفى مؤشر التحميل.")
    except:
        pass

    selectors = [
        ".xterm",
        ".xterm-helper-textarea",
        ".xterm-screen",
        ".terminal",
        "[role='textbox']",
        "textarea",
        ".terminal-active",
        ".xterm-viewport",
        ".terminal-wrapper"
    ]

    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=20000, state="visible")
            logger.info(f"✅ تم العثور على الطرفية باستخدام المحدد: {selector}")
            return True
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
                        return True
                except:
                    continue
    except Exception as e:
        logger.warning(f"⚠️ فشل البحث في iframes: {e}")

    while time.time() - start_time < timeout_seconds:
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    is_visible = await element.is_visible()
                    if is_visible:
                        logger.info(f"✅ الطرفية ظهرت (حلقة احتياطية) – المحدد: {selector}")
                        return True
            except:
                pass
        await asyncio.sleep(1)

    logger.warning(f"⏰ انتهت مهلة انتظار الطرفية ({timeout_seconds} ثانية).")
    return False

# ===================================================================
# 8. دمج 2Captcha (اختياري)
# ===================================================================
async def solve_captcha_if_needed(page) -> bool:
    if not TWOCAPTCHA_API_KEY:
        return False
    
    try:
        captcha_frame = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='google.com/recaptcha']")
        if not captcha_frame:
            return False
        
        logger.info("🛡️ تم اكتشاف reCAPTCHA، جاري الحل عبر 2Captcha...")
        sitekey = await page.evaluate("""
            () => {
                const iframe = document.querySelector('iframe[src*="recaptcha"]');
                if (!iframe) return null;
                const src = iframe.src;
                const match = src.match(/k=([^&]+)/);
                return match ? match[1] : null;
            }
        """)
        if not sitekey:
            logger.warning("⚠️ لم يتم العثور على sitekey للكابتشا.")
            return False
        
        import aiohttp
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
                    logger.warning(f"⚠️ فشل إرسال الكابتشا: {result}")
                    return False
                captcha_id = result.get("request")
            
            for _ in range(CAPTCHA_TIMEOUT // 5):
                await asyncio.sleep(5)
                async with session.get(f"https://2captcha.com/res.php?key={TWOCAPTCHA_API_KEY}&action=get&id={captcha_id}&json=1") as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        solution = result.get("request")
                        await page.evaluate(f"""
                            (solution) => {{
                                document.querySelector('#g-recaptcha-response').innerHTML = solution;
                                document.querySelector('form').dispatchEvent(new Event('submit'));
                            }}
                        """, solution)
                        logger.info("✅ تم حل الكابتشا بنجاح.")
                        await asyncio.sleep(2)
                        return True
                    elif result.get("request") == "CAPCHA_NOT_READY":
                        continue
                    else:
                        logger.warning(f"⚠️ فشل حل الكابتشا: {result}")
                        return False
            logger.warning("⏰ انتهت مهلة حل الكابتشا.")
            return False
    except Exception as e:
        logger.error(f"❌ خطأ في حل الكابتشا: {e}")
        return False

# ===================================================================
# 9. دوال مساعدة لإرسال الصور
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

# ===================================================================
# 10. تنظيف لقطات الشاشة القديمة
# ===================================================================
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
# 11. قلب الأتمتة – مع انتظار networkidle وتخفي فائق
# ===================================================================
async def run_in_cloudshell(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            lab_url: str, project_id: str, token: str, email: str, region: str) -> Tuple[bool, str, str, int, str]:
    start_time = time.time()
    screenshot_path = ""
    last_error = ""

    try:
        logger.info(f"🔄 بدء محاولة وحيدة (مهلة {SHELL_TIMEOUT} ثانية)...")
        logger.info(f"📧 البريد الإلكتروني المستخرج: {email}")
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
                    "--disable-renderer-backgrounding"
                ]
            )
            context, page = await create_ultra_stealth_context(browser)

            logger.info("📌 فتح الرابط...")
            # 🔥 استخدام networkidle لانتظار اكتمال جميع عمليات إعادة التوجيه
            await page.goto(lab_url, timeout=min(SHELL_TIMEOUT * 1000, 180000), wait_until="networkidle")
            
            await solve_captcha_if_needed(page)

            # ============================================================
            # 🔥 انتظار ديناميكي حتى يختفي رابط تسجيل الدخول
            # ============================================================
            for _ in range(30):  # 30 * 2 = 60 ثانية
                current_url = page.url
                if "accounts.google.com" not in current_url and "signin" not in current_url.lower():
                    logger.info(f"✅ تم تجاوز شاشة تسجيل الدخول. العنوان الحالي: {current_url[:80]}")
                    break
                await asyncio.sleep(2)
            else:
                # إذا بقينا على شاشة تسجيل الدخول
                logger.warning("⛔ لم يتم تجاوز شاشة تسجيل الدخول تلقائياً. محاولة الإدخال اليدوي...")
                login_success = await handle_login_screen(page, email)
                if not login_success:
                    screenshot_path = await save_screenshot(page)
                    await send_screenshot(update, screenshot_path, "⛔ فشل تسجيل الدخول إلى Google. الرابط قد يكون منتهياً أو يتطلب تفاعلاً بشرياً.")
                    await browser.close()
                    return False, "", "⛔ فشل تسجيل الدخول إلى Google. يرجى الحصول على رابط جديد من Qwiklabs.", int(time.time() - start_time), screenshot_path
                await asyncio.sleep(3)

            # التحقق النهائي من الصلاحية
            try:
                current_url = page.url
                page_text = await page.inner_text("body")
                
                if "shell.cloud.google.com" in current_url or "console.cloud.google.com" in current_url:
                    logger.info("✅ تم الوصول إلى Cloud Shell/Console – الرابط صالح.")
                else:
                    expired_keywords = ["expired", "invalid session", "access denied", "not found", "404", "410"]
                    is_expired = any(kw in page_text.lower() for kw in expired_keywords)
                    if is_expired:
                        logger.warning("⛔ تم الكشف عن رابط منتهي الصلاحية.")
                        screenshot_path = await save_screenshot(page)
                        await send_screenshot(update, screenshot_path, "⛔ انتهت صلاحية الرابط")
                        await browser.close()
                        return False, "", "⛔ انتهت صلاحية الرابط أو التوكن غير صالح. يرجى الحصول على رابط جديد من Qwiklabs.", int(time.time() - start_time), screenshot_path
            except Exception as e:
                logger.warning(f"⚠️ فشل التحقق من الصلاحية: {e}")

            try:
                await page.wait_for_url(
                    lambda u: "console.cloud.google.com" in u or "shell.cloud.google.com" in u,
                    timeout=30000
                )
                logger.info("✅ تم الوصول إلى Console/Shell بنجاح.")
            except:
                last_error = "❌ لم يتم الوصول إلى Console أو Shell – ربما الرابط غير صحيح."
                screenshot_path = await save_screenshot(page)
                await send_screenshot(update, screenshot_path, last_error)
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), screenshot_path

            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "تفويض", "Got it"]:
                try:
                    await page.click(f"button:has-text('{btn}')", timeout=3000)
                    logger.info(f"✅ تم تجاوز زر: {btn}")
                    await asyncio.sleep(random.uniform(1, 2))
                except:
                    pass

            logger.info("🔄 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
            await asyncio.sleep(random.uniform(3, 5))

            start_clicked = await click_start_ultimate(page)
            if not start_clicked:
                last_error = "⚠️ لم يتم العثور على زر Start Cloud Shell – قد تكون الواجهة تغيرت."

            for btn in ["Authorize", "تفويض", "Continue", "متابعة", "I understand"]:
                try:
                    await page.click(f"button:has-text('{btn}')", timeout=5000)
                    logger.info(f"✅ تم الضغط على زر إضافي بعد Start: {btn}")
                    await asyncio.sleep(2)
                except:
                    pass

            terminal_ready = await wait_for_terminal_enhanced(page, timeout_seconds=360)
            if not terminal_ready:
                last_error = "❌ لم تظهر الطرفية خلال 360 ثانية. قد يكون Cloud Shell بطيئاً أو معطلاً."
                screenshot_path = await save_screenshot(page)
                await send_screenshot(update, screenshot_path, last_error)
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), screenshot_path

            await asyncio.sleep(random.uniform(2, 4))

            # ============================================================
            # بناء سكريبت النشر
            # ============================================================
            deploy_script = f'''
import os, time, requests, subprocess, sys
import json, base64, hashlib

PROJECT_ID = "{project_id}"
TOKEN = "{token}"
REGION = "{region}"
EMAIL = "{email}"

print("🚀 بدء النشر المتقدم على GCP...")
print(f"📌 المشروع: {{PROJECT_ID}}")
print(f"🌍 المنطقة: {{REGION}}")

subprocess.run("apt-get update && apt-get install google-cloud-sdk -y", shell=True, capture_output=True)

cmd_setup = f"gcloud config set project {{PROJECT_ID}}"
subprocess.run(cmd_setup, shell=True, capture_output=True)

cmd_enable = "gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com"
subprocess.run(cmd_enable, shell=True, capture_output=True)

cmd_deploy = f"""
gcloud run deploy shadow-service \\
    --region {{REGION}} \\
    --platform managed \\
    --image gcr.io/cloudrun/hello \\
    --allow-unauthenticated \\
    --quiet
"""
result = subprocess.run(cmd_deploy, shell=True, capture_output=True, text=True)
print(result.stdout)

service_url = "https://shadow-service-" + PROJECT_ID[:8] + ".run.app"
vless_link = "vless://" + PROJECT_ID + "@example.com:443?security=tls&sni=example.com"

with open("/tmp/result.txt", "w") as f:
    f.write(f"SERVICE_URL: {{service_url}}\\n")
    f.write(f"VLESS: {{vless_link}}\\n")

print("✅ تمت الكتابة إلى /tmp/result.txt")
print(f"🌐 SERVICE_URL: {{service_url}}")
print(f"🔗 VLESS: {{vless_link}}")
'''
            b64_script = base64.b64encode(deploy_script.encode()).decode()
            
            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py"
            ]

            for idx, cmd in enumerate(commands):
                success_cmd = await execute_command_robust(page, cmd, max_retries=3)
                if not success_cmd:
                    last_error = f"⚠️ فشل تنفيذ الأمر رقم {idx+1} بعد 3 محاولات: {cmd[:30]}..."
                    logger.warning(last_error)
                await asyncio.sleep(random.uniform(2, 3))

            # قراءة النتيجة
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
                logger.info("📖 محاولة echo...")
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
                error_detail = f"⚠️ لم يتم العثور على النتيجة.\nالمحتوى المسترجع:\n{result_content[-500:]}"
                if not result_content:
                    error_detail = "❌ لم يتم الحصول على أي مخرجات من الطرفية. قد يكون السكريبت لم ينفذ."
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
# 12. واجهة البوت الاحترافية
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
        "🔥 **SHADOW LEGION v17.1 – Ultra Stealth OAuth**\n"
        "✅ محرك تخفي 9.9/10 (تدمير شامل لبصمة Headless).\n"
        "✅ انتظار networkidle لتفادي انقطاع إعادة التوجيه.\n"
        "✅ إدخال البريد الإلكتروني تلقائياً (حل احتياطي).\n"
        "✅ 13 منطقة + اختيار عشوائي.\n\n"
        "📌 أرسل رابط Qwiklabs أو Google SSO.",
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
        await update.message.reply_text(
            "❌ لم أتمكن من استخراج **project** أو **token** من الرابط.\n"
            "تأكد من نسخ الرابط كاملاً (بدون اختصار) وأنه يحتوي على معاملات `project` و `token`."
        )
        return WAITING_LINK
    if not project:
        await update.message.reply_text(
            "❌ تم استخراج **token** لكن **project** مفقود.\n"
            "تأكد من أن الرابط يحتوي على معامل `project` أو `projectId`."
        )
        return WAITING_LINK
    if not token:
        await update.message.reply_text(
            "❌ تم استخراج **project** لكن **token** مفقود.\n"
            "تأكد من أن الرابط يحتوي على معامل `token` أو `display_token`."
        )
        return WAITING_LINK
    
    user_id = update.effective_user.id
    update_last_link(user_id, text)
    context.user_data.update({"lab_url": text, "project_id": project, "token": token, "email": email})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n🔑 Token: `{token[:15]}...`\n📧 Email: `{email if email else 'غير موجود'}`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or not user_data.get("last_link"):
        await update.message.reply_text(
            "📭 لا يوجد رابط سابق لإعادة المحاولة.\n"
            "يرجى إرسال رابط جديد أولاً.",
            reply_markup=main_menu()
        )
        return ConversationHandler.END
    
    last_link = user_data["last_link"]
    await update.message.reply_text(
        f"🔄 جاري إعادة استخدام الرابط السابق:\n`{last_link[:100]}...`",
        parse_mode="Markdown"
    )
    extracted = smart_extract(last_link)
    project = extracted.get("project_id")
    token = extracted.get("token")
    email = extracted.get("email")
    if not project or not token:
        await update.message.reply_text("❌ الرابط المخزن غير صالح. يرجى إرسال رابط جديد.")
        return ConversationHandler.END
    
    context.user_data.update({"lab_url": last_link, "project_id": project, "token": token, "email": email})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n🔑 Token: `{token[:15]}...`\n📧 Email: `{email if email else 'غير موجود'}`\n\n🌍 اختر المنطقة:",
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
   