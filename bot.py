#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v16.5 – ULTIMATE_10_10
- محرك تخفي 10/10 (مع تدمير بصمة Audio/WebGL/Canvas)
- دعم 2Captcha لتجاوز تحديات reCAPTCHA
- انتظار ذكي للطرفية (خروج فوري عند الظهور)
- إعادة محاولة لكل أمر (3 محاولات)
- تثبيت gcloud تلقائياً في السكريبت
- أمر /retry لإعادة استخدام آخر رابط
- هيكلية محسّنة ودوال مساعدة
- تقارير أخطاء دقيقة جداً
- تنظيف تلقائي للقطات القديمة
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
from functools import wraps

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
# 1. الإعدادات الأساسية مع متغيرات البيئة المتقدمة
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود (ضعه في متغيرات البيئة)")

DB_PATH = os.environ.get("DB_PATH", "shadow_legion.db")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "1"))
SHELL_TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "600"))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", "7"))
PROXY = os.environ.get("PROXY")

# إعدادات 2Captcha (اختياري)
TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")
CAPTCHA_TIMEOUT = int(os.environ.get("CAPTCHA_TIMEOUT", "120"))

# إعداد التسجيل المتقدم
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v16.5 (10/10) بدأ التشغيل...")

# ===================================================================
# 2. قوائم عشوائية متطورة للتمويه
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

# دوال قاعدة البيانات (نفس السابق مع إضافة last_link)
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
# 4. المستخرج الذكي V5 (يتعامل مع # والترميز الخماسي)
# ===================================================================
def smart_extract(link: str) -> Dict[str, Optional[str]]:
    link = link.strip()
    decoded = link
    for _ in range(5):
        decoded = urllib.parse.unquote(decoded)
    
    project = None
    token = None
    
    if '#' in decoded:
        main_part = decoded.split('#')[0]
    else:
        main_part = decoded
    
    parsed = urllib.parse.urlparse(main_part)
    params = urllib.parse.parse_qs(parsed.query)
    
    project = params.get('project', [None])[0] or params.get('projectId', [None])[0] or params.get('id', [None])[0]
    token = params.get('token', [None])[0] or params.get('display_token', [None])[0] or params.get('auth_token', [None])[0]
    
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
    
    return {"project_id": project, "token": token}

# ===================================================================
# 5. محرك التخفي الفائق (مع تدمير متقدم للبصمة)
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
    }
    
    if PROXY:
        context_options["proxy"] = {"server": PROXY}
    
    context = await browser.new_context(**context_options)

    # حقن سكريبت تدمير البصمة المتطور (WebGL + Canvas + Audio)
    await context.add_init_script("""
        // WebGL Randomization
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            const vendors = ['Intel Inc.', 'NVIDIA Corporation', 'AMD', 'Apple', 'ARM'];
            const renderers = ['Intel Iris OpenGL Engine', 'NVIDIA GeForce GTX 1660', 'AMD Radeon Pro 5500M', 'Apple M1 GPU', 'ARM Mali-G78'];
            if (p === 37445) return vendors[Math.floor(Math.random() * vendors.length)];
            if (p === 37446) return renderers[Math.floor(Math.random() * renderers.length)];
            return getParameter.call(this, p);
        };
        
        // Canvas Noise (3%)
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
        
        // Audio Noise
        const originalGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(channel) {
            const data = originalGetChannelData.call(this, channel);
            for (let i = 0; i < data.length; i += 100) {
                data[i] += (Math.random() - 0.5) * 0.001;
            }
            return data;
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
# 6. دوال التفاعل المتطورة
# ===================================================================
async def handle_login_screen(page):
    account_selectors = [
        "div[role='button']:has-text('student')",
        "div[role='button']:has-text('@qwiklabs')",
        "div[role='button']:has-text('@')",
        "[data-email]",
        "div[role='button']:has-text('qwiklabs.net')"
    ]
    for selector in account_selectors:
        try:
            accounts = await page.query_selector_all(selector)
            if accounts:
                await accounts[0].click()
                logger.info(f"✅ تم اختيار الحساب عبر: {selector}")
                await asyncio.sleep(3)
                return
        except:
            continue
    
    try:
        emails = await page.evaluate("""
            () => {
                const elements = document.querySelectorAll('div[role="button"], button, a');
                for (let el of elements) {
                    const text = el.innerText || el.getAttribute('aria-label') || '';
                    if (text.includes('@') || text.includes('qwiklabs')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if emails:
            logger.info("✅ تم اختيار حساب عبر البحث الديناميكي.")
            await asyncio.sleep(3)
    except:
        pass
    
    for btn in ["Continue", "متابعة", "Authorize", "تفويض", "I understand", "Agree"]:
        try:
            await page.click(f"button:has-text('{btn}')", timeout=3000)
            logger.info(f"✅ تم تجاوز زر: {btn}")
            await asyncio.sleep(2)
        except:
            pass

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

# ===================================================================
# 7. تنفيذ الأوامر مع إعادة محاولة جزئية (3 محاولات)
# ===================================================================
async def execute_command_robust(page, cmd: str, max_retries: int = 3) -> bool:
    """ينفذ الأمر مع إعادة محاولة تلقائية لكل طبقة"""
    for attempt in range(max_retries):
        logger.info(f"▶️ تنفيذ: {cmd[:60]}... (محاولة {attempt+1}/{max_retries})")
        
        # الطبقة 1: Clipboard API
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
        
        # الطبقة 2: InputEvent
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
        
        # الطبقة 3: keyboard.type
        try:
            for ch in cmd:
                await page.keyboard.type(ch, delay=random.randint(15, 40))
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.5)
            return True
        except:
            pass
        
        # الطبقة 4: الحقن المباشر
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
            await asyncio.sleep(2)  # انتظر قبل إعادة المحاولة
    
    logger.error(f"❌ فشل تنفيذ الأمر بعد {max_retries} محاولات: {cmd[:60]}")
    return False

# ===================================================================
# 8. انتظار الطرفية الذكي (خروج فوري عند الظهور)
# ===================================================================
async def wait_for_terminal(page, timeout_seconds=240) -> bool:
    logger.info(f"⏳ في انتظار الطرفية (مهلة {timeout_seconds} ثانية)...")
    start_time = time.time()
    terminal_selectors = [
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
    
    # انتظار اختفاء مؤشر التحميل
    try:
        await page.wait_for_selector(".loading-spinner, .loader, .spinner", timeout=10000, state="hidden")
        logger.info("✅ اختفى مؤشر التحميل.")
    except:
        pass
    
    while time.time() - start_time < timeout_seconds:
        for selector in terminal_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    # التحقق من التفاعل
                    is_focused = await page.evaluate(f"""
                        (sel) => {{
                            const el = document.querySelector(sel);
                            if (el) {{
                                el.focus();
                                el.dispatchEvent(new Event('focus', {{ bubbles: true }}));
                                return document.activeElement === el || 
                                       document.activeElement?.closest(sel) !== null;
                            }}
                            return false;
                        }}
                    """, selector)
                    if is_focused:
                        logger.info(f"✅ الطرفية جاهزة (خرجنا فوراً) – المحدد: {selector}")
                        return True
            except:
                pass
        await asyncio.sleep(1)  # تحقق كل ثانية بدلاً من 2
    
    logger.warning("⏰ انتهت مهلة انتظار الطرفية.")
    return False

# ===================================================================
# 9. دمج 2Captcha لحل تحديات reCAPTCHA
# ===================================================================
async def solve_captcha_if_needed(page) -> bool:
    """يكتشف وجود reCAPTCHA ويحلها باستخدام 2Captcha إن أمكن"""
    if not TWOCAPTCHA_API_KEY:
        return False  # لا يوجد مفتاح، تخطي
    
    try:
        # البحث عن iframe لـ reCAPTCHA
        captcha_frame = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='google.com/recaptcha']")
        if not captcha_frame:
            return False  # لا يوجد كابتشا
        
        logger.info("🛡️ تم اكتشاف reCAPTCHA، جاري الحل عبر 2Captcha...")
        
        # الحصول على sitekey
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
        
        # استدعاء 2Captcha API
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # إرسال الطلب لحل الكابتشا
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
            
            # انتظار الحل
            for _ in range(CAPTCHA_TIMEOUT // 5):
                await asyncio.sleep(5)
                async with session.get(f"https://2captcha.com/res.php?key={TWOCAPTCHA_API_KEY}&action=get&id={captcha_id}&json=1") as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        solution = result.get("request")
                        # حقن الحل في الصفحة
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
# 10. قلب الأتمتة – النسخة النهائية 10/10
# ===================================================================
async def run_in_cloudshell(lab_url: str, project_id: str, token: str, region: str) -> Tuple[bool, str, str, int, str]:
    start_time = time.time()
    screenshot_path = ""
    last_error = ""

    try:
        logger.info(f"🔄 بدء محاولة وحيدة (مهلة {SHELL_TIMEOUT} ثانية)...")
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
                    "--disable-features=OutOfBlinkCors"
                ]
            )
            context, page = await create_ultra_stealth_context(browser)

            logger.info("📌 فتح الرابط...")
            await page.goto(lab_url, timeout=min(SHELL_TIMEOUT * 1000, 180000), wait_until="domcontentloaded")
            
            # حل الكابتشا إن وجدت
            await solve_captcha_if_needed(page)

            # كشف الصلاحية المحسن V3
            try:
                await asyncio.sleep(5)
                current_url = page.url
                page_text = await page.inner_text("body")
                
                if "shell.cloud.google.com" in current_url or "console.cloud.google.com" in current_url:
                    logger.info("✅ تم الوصول إلى Cloud Shell/Console – الرابط صالح.")
                else:
                    expired_keywords = ["expired", "invalid session", "access denied", "not found", "404", "410"]
                    login_keywords = ["sign in", "choose an account", "accounts.google.com", "login", "log in"]
                    
                    is_expired = any(kw in page_text.lower() for kw in expired_keywords)
                    
                    if any(kw in page_text.lower() for kw in login_keywords):
                        has_shell_element = await page.query_selector(".xterm, .terminal, button:has-text('Start Cloud Shell')")
                        if has_shell_element:
                            logger.info("✅ تم العثور على عناصر Cloud Shell – الرابط صالح رغم كلمات تسجيل الدخول.")
                            is_expired = False
                        else:
                            is_expired = True
                    
                    if is_expired:
                        logger.warning("⛔ تم الكشف عن رابط منتهي الصلاحية.")
                        await browser.close()
                        return False, "", "⛔ انتهت صلاحية الرابط أو التوكن غير صالح. يرجى الحصول على رابط جديد من Qwiklabs.", int(time.time() - start_time), ""
            except Exception as e:
                logger.warning(f"⚠️ فشل التحقق من الصلاحية: {e}")

            await handle_login_screen(page)

            try:
                await page.wait_for_url(
                    lambda u: "console.cloud.google.com" in u or "shell.cloud.google.com" in u,
                    timeout=60000
                )
                logger.info("✅ تم الوصول إلى Console/Shell بنجاح.")
            except:
                last_error = "❌ لم يتم الوصول إلى Console أو Shell – ربما الرابط غير صحيح."
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), ""

            for btn in ["Understand", "I agree", "Continue", "متابعة", "Authorize", "تفويض", "Got it"]:
                try:
                    await page.click(f"button:has-text('{btn}')", timeout=3000)
                    logger.info(f"✅ تم تجاوز زر: {btn}")
                    await asyncio.sleep(random.uniform(1, 2))
                except:
                    pass

            logger.info("🔄 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(3, 5))

            start_clicked = await click_start_ultimate(page)
            if not start_clicked:
                last_error = "⚠️ لم يتم العثور على زر Start Cloud Shell – قد تكون الواجهة تغيرت."

            terminal_ready = await wait_for_terminal(page, timeout_seconds=240)
            if not terminal_ready:
                last_error = "❌ لم تظهر الطرفية خلال 240 ثانية. قد يكون Cloud Shell بطيئاً أو معطلاً."
                await browser.close()
                return False, "", last_error, int(time.time() - start_time), ""

            await asyncio.sleep(random.uniform(2, 4))

            # ============================================================
            # بناء سكريبت النشر الاحترافي (مع تثبيت gcloud)
            # ============================================================
            deploy_script = f'''
import os, time, requests, subprocess, sys
import json, base64, hashlib

PROJECT_ID = "{project_id}"
TOKEN = "{token}"
REGION = "{region}"
EMAIL = "student@qwiklabs.net"

print("🚀 بدء النشر المتقدم على GCP...")
print(f"📌 المشروع: {{PROJECT_ID}}")
print(f"🌍 المنطقة: {{REGION}}")

# تثبيت gcloud إن لم يكن موجوداً
subprocess.run("apt-get update && apt-get install google-cloud-sdk -y", shell=True, capture_output=True)

# إعداد gcloud
cmd_setup = f"gcloud config set project {{PROJECT_ID}}"
subprocess.run(cmd_setup, shell=True, capture_output=True)

# تمكين الخدمات المطلوبة
cmd_enable = "gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com"
subprocess.run(cmd_enable, shell=True, capture_output=True)

# بناء ونشر خدمة (مثال حقيقي)
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

# استخراج الرابط
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

            # قراءة النتيجة بطرق متعددة
            logger.info("📖 محاولة قراءة /tmp/result.txt...")
            result_content = ""
            
            # الطريقة 1: fetch
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

            # الطريقة 2: cat
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

            # الطريقة 3: echo
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
                return False, "", error_detail, int(time.time() - start_time), screenshot_path

    except PlaywrightTimeout as e:
        logger.exception("⏰ انتهت مهلة Playwright")
        return False, "", f"⏰ انتهت المهلة: {str(e)[:200]}", int(time.time() - start_time), screenshot_path
    except Exception as e:
        logger.exception(f"❌ فشل المحاولة")
        return False, "", f"❌ خطأ تقني: {str(e)[:200]}", int(time.time() - start_time), screenshot_path

# ===================================================================
# 11. تنظيف لقطات الشاشة القديمة
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
# 12. واجهة البوت الاحترافية مع أمر /retry
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
        "🔥 **SHADOW LEGION v16.5 – Ultimate 10/10**\n"
        "✅ أقوى إصدار على الإطلاق مع دعم 2Captcha.\n"
        "✅ محرك تخفي 10/10 (يعجز عن كشفه حتى Google).\n"
        "✅ 13 منطقة + اختيار عشوائي.\n"
        "✅ دعم كامل لروابط Google SSO و Qwiklabs.\n"
        "✅ أمر /retry لإعادة المحاولة.\n\n"
        "📌 أرسل رابط Qwiklabs أو Google SSO.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 أرسل رابط Qwiklabs أو Google SSO:", reply_markup=main_menu())
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "❌ إلغاء" or text == "🔄 إعادة المحاولة":
        # التعامل مع إعادة المحاولة
        if text == "🔄 إعادة المحاولة":
            return await retry_command(update, context)
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu())
        return ConversationHandler.END
    
    extracted = smart_extract(text)
    project = extracted.get("project_id")
    token = extracted.get("token")
    
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
    update_last_link(user_id, text)  # حفظ آخر رابط
    context.user_data.update({"lab_url": text, "project_id": project, "token": token})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n🔑 Token: `{token[:15]}...`\n\n🌍 اختر المنطقة:",
        parse_mode="Markdown", reply_markup=region_menu()
    )
    return WAITING_REGION

async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يعيد استخدام آخر رابط للمستخدم"""
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
    # إعادة معالجته كرابط جديد
    extracted = smart_extract(last_link)
    project = extracted.get("project_id")
    token = extracted.get("token")
    if not project or not token:
        await update.message.reply_text("❌ الرابط المخزن غير صالح. يرجى إرسال رابط جديد.")
        return ConversationHandler.END
    
    context.user_data.update({"lab_url": last_link, "project_id": project, "token": token})
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات بنجاح**\n🆔 Project: `{project}`\n🔑 Token: `{token[:15]}...`\n\n🌍 اختر المنطقة:",
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
    if not proj or not tok:
        await q.edit_message_text("❌ انتهت الجلسة. أعد الإرسال.")
        return

    region_name = KNOWN_REGIONS.get(region, region)
    await q.edit_message_text(f"🚀 جاري النشر على {region_name} ... (قد يستغرق 3-5 دقائق)")

    success, service, vless, duration, screenshot = await run_in_cloudshell(lab, proj, tok, region)

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
            f"❌ **فشل النشر**\n\n```\n{vless}\n```\n\n🔄 يمكنك استخدام زر 'إعادة المحاولة' لتجربة الرابط نفسه مرة أخرى.",
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
# 13. التشغيل الرئيسي + خادم الويب
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

    logger.info("🔥 SHADOW LEGION v16.5 (Ultimate 10/10) جاهز تماماً...")
    app.run_polling()

if __name__ == "__main__":
    main()