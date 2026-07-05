#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   SHADOW LEGION v999 – ULTIMATE LONG PROFESSIONAL EDITION     ║
║   الطول: 850+ سطر  │  جميع الميزات الاحترافية               ║
║   Incognito  │  اختيار السيرفرات  │  إحصائيات  │  سجل تاريخي ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import re
import time
import json
import hashlib
import logging
import sqlite3
import urllib.parse
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ===================================================================
# 1. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود. أضفه في Railway Variables.")

USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)
DB_PATH = "shadow_ultimate_long.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (النسخة الطويلة الاحترافية) بدأ التشغيل...")

# حالات المحادثة
WAITING_LINK, WAITING_REGION, CONFIRM_DEPLOY, WAITING_EMAIL, WAITING_PASSWORD = range(5)

# قاعدة بيانات المناطق العالمية (محدثة)
KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا (الوسطى)",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "us-west1": "🇺🇸 أوريغون",
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
    "asia-southeast1": "🇸🇬 سنغافورة",
    "asia-east1": "🇹🇼 تايوان",
    "australia-southeast1": "🇦🇺 سيدني",
    "southamerica-east1": "🇧🇷 ساو باولو",
    "northamerica-northeast1": "🇨🇦 مونتريال"
}

# ===================================================================
# 2. قاعدة البيانات المتقدمة (8 جداول)
# ===================================================================
def init_ultimate_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            region TEXT DEFAULT 'us-central1',
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT,
            expiry TIMESTAMP,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER,
            project_id TEXT,
            regions TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, project_id)
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
            error_msg TEXT
        );
        CREATE TABLE IF NOT EXISTS failure_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            error_type TEXT,
            error_detail TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS region_stats (
            region_code TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            preferred_region TEXT,
            auto_deploy BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE DEFAULT CURRENT_DATE,
            total_deploys INTEGER DEFAULT 0,
            successful_deploys INTEGER DEFAULT 0,
            failed_deploys INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات المتقدمة (8 جداول) جاهزة")

init_ultimate_db()

# ===================================================================
# 3. دوال قاعدة البيانات (مفصلة بالكامل)
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, region, deploy_count, status, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "region": row[1],
            "deploy_count": row[2],
            "status": row[3],
            "last_activity": row[4]
        }
    return None

def update_user(user_id: int, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", list(kwargs.values()) + [user_id])
    else:
        if "last_activity" not in kwargs:
            kwargs["last_activity"] = datetime.now().isoformat()
        cols = ",".join(kwargs.keys())
        vals = list(kwargs.values())
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {','.join(['?']*len(vals))})", [user_id] + vals)
    conn.commit()
    conn.close()

def get_cached_token(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0]
    return None

def save_cached_token(user_id: int, token: str, project_id: str = "", expiry_seconds: int = 3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, token, expiry.isoformat(), project_id))
    conn.commit()
    conn.close()

def clear_cached_token(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM token_cache WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def save_scan_cache(user_id: int, project_id: str, regions: List[str]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO scan_cache (user_id, project_id, regions) VALUES (?,?,?)",
              (user_id, project_id, json.dumps(regions)))
    conn.commit()
    conn.close()

def get_scan_cache(user_id: int, project_id: str) -> Optional[List[str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT regions FROM scan_cache WHERE user_id=? AND project_id=?", (user_id, project_id))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()
    # تحديث إحصائيات المنطقة
    c = conn.cursor()
    if success:
        c.execute("INSERT INTO region_stats (region_code, success_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET success_count = success_count + 1, last_used = CURRENT_TIMESTAMP", (region,))
    else:
        c.execute("INSERT INTO region_stats (region_code, fail_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET fail_count = fail_count + 1", (region,))
    # تحديث التحليلات اليومية
    c.execute("INSERT INTO analytics (date, total_deploys, successful_deploys, failed_deploys) VALUES (CURRENT_DATE, 1, ?, ?) ON CONFLICT(date) DO UPDATE SET total_deploys = total_deploys + 1, successful_deploys = successful_deploys + ?, failed_deploys = failed_deploys + ?",
              (1 if success else 0, 1 if success else 0, 1 if success else 0, 1 if not success else 0))
    conn.commit()
    conn.close()

def log_failure(user_id: int, error_type: str, error_detail: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO failure_logs (user_id, error_type, error_detail) VALUES (?,?,?)",
              (user_id, error_type, error_detail[:500]))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_preferred_region(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT preferred_region FROM user_preferences WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_preferred_region(user_id: int, region: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_preferences (user_id, preferred_region) VALUES (?,?)",
              (user_id, region))
    conn.commit()
    conn.close()

def get_auto_deploy(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT auto_deploy FROM user_preferences WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def set_auto_deploy(user_id: int, enabled: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_preferences (user_id, auto_deploy) VALUES (?,?)",
              (user_id, 1 if enabled else 0))
    conn.commit()
    conn.close()

# ===================================================================
# 4. دوال مساعدة (احترافية)
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'/projects/([^/?]+)', decoded)
    return m.group(1) if m else None

def build_vless_link(service_url: str, seed: str = "shadow_v999") -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5((seed + str(time.time()) + os.urandom(4).hex()).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#UltimateTunnel"

def test_token_validity(token: str, project_id: str) -> bool:
    if not token or len(token) < 40:
        return False
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# 5. استخراج التوكن بـ Playwright (Async + Incognito + 3 استراتيجيات)
# ===================================================================
async def extract_token_playwright_ultimate(link: str, project_id: str, max_retries: int = 3) -> str:
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--incognito",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-gpu"
                    ]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                    locale="en-US",
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                """)

                # 1. فتح الرابط
                logger.info(f"🌐 محاولة {attempt}: فتح الرابط {link}")
                await page.goto(link, timeout=60000)
                await page.wait_for_timeout(5000)

                # 2. البحث عن Open Console
                console_opened = False
                try:
                    console_btn = await page.query_selector("text=Open Console")
                    if console_btn:
                        logger.info("✅ العثور على Open Console")
                        await console_btn.click()
                        console_opened = True
                    else:
                        console_link = await page.query_selector('a[href*="console.cloud.google.com"]')
                        if console_link:
                            logger.info("✅ العثور على رابط Console")
                            await console_link.click()
                            console_opened = True
                except Exception as e:
                    logger.warning(f"⚠️ فشل النقر على Console: {e}")

                # 3. التوجه إلى Cloud Run
                if not console_opened:
                    console_url = f"https://console.cloud.google.com/run?project={project_id}&hl=en"
                    logger.info(f"🔗 التوجه مباشرة إلى: {console_url}")
                    await page.goto(console_url, timeout=60000)
                    await page.wait_for_timeout(8000)
                else:
                    pages = context.pages
                    if len(pages) > 1:
                        page = pages[-1]
                        await page.wait_for_load_state()
                    await page.wait_for_timeout(7000)

                # 4. استخراج التوكن
                token = await page.evaluate("""
                    () => {
                        const keys = ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token'];
                        for (let k of keys) {
                            let v = localStorage.getItem(k);
                            if (v && v.length > 40) return v;
                        }
                        for (let i=0; i<sessionStorage.length; i++) {
                            let k = sessionStorage.key(i);
                            if (k && (k.includes('token')||k.includes('oauth'))) {
                                let v = sessionStorage.getItem(k);
                                if (v && v.length > 40) return v;
                            }
                        }
                        let cookies = document.cookie.split(';');
                        for (let c of cookies) {
                            let parts = c.trim().split('=');
                            if (parts[0] && (parts[0].includes('token')||parts[0].includes('oauth'))) {
                                if (parts[1] && parts[1].length > 40) return parts[1];
                            }
                        }
                        return null;
                    }
                """)

                await browser.close()

                if token and len(token) > 40:
                    logger.info("✅ تم استخراج التوكن بنجاح")
                    return token
                raise Exception("لم أجد التوكن في هذه المحاولة")

        except Exception as e:
            last_exception = str(e)
            logger.warning(f"⚠️ المحاولة {attempt} فشلت: {e}")
            await asyncio.sleep(5)

    raise Exception(f"فشل استخراج التوكن بعد {max_retries} محاولات: {last_exception}")

# ===================================================================
# 6. الطبقة العليا للتوكن (4 مصادر)
# ===================================================================
async def get_master_token(user_id: int, link: str, project_id: str) -> str:
    # المصدر 1: التوكن اليدوي
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        if test_token_validity(USER_TOKEN_OVERRIDE, project_id):
            save_cached_token(user_id, USER_TOKEN_OVERRIDE, project_id)
            return USER_TOKEN_OVERRIDE

    # المصدر 2: التوكن المخبأ
    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        logger.info("♻️ استخدام التوكن المخبأ")
        return cached

    # المصدر 3: استخراج جديد
    token = await extract_token_playwright_ultimate(link, project_id)
    if token and test_token_validity(token, project_id):
        save_cached_token(user_id, token, project_id)
        return token

    raise Exception("تعذر الحصول على توكن صالح من أي مصدر")

# ===================================================================
# 7. فحص المناطق (مع احتياطي واسع)
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            allowed = []
            for loc in data.get("locations", []):
                loc_id = loc.get("locationId")
                if loc.get("state") == "ENABLED" and loc_id:
                    allowed.append(loc_id)
            if allowed:
                logger.info(f"✅ تم اكتشاف {len(allowed)} منطقة عبر API")
                return allowed
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب المناطق: {e}")

    # الاحتياطي
    fallback = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    logger.info(f"🔄 استخدام المناطق الاحتياطية: {fallback}")
    return fallback

# ===================================================================
# 8. النشر مع إعادة محاولة على مناطق بديلة
# ===================================================================
def deploy_with_fallback(project_id: str, token: str, preferred: str, all_regions: List[str]) -> Tuple[str, str, str]:
    regions_to_try = [preferred] + [r for r in all_regions if r != preferred]
    last_error = ""

    for region in regions_to_try:
        try:
            logger.info(f"🚀 محاولة النشر على المنطقة: {region}")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            service_name = f"shadow-app-{int(time.time())}-{region[:5]}"
            payload = {
                "apiVersion": "serving.knative.dev/v1",
                "kind": "Service",
                "metadata": {"name": service_name},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "image": "ajndjd2/ahmed-vip1",
                                    "ports": [{"containerPort": 8080}],
                                    "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
                                }
                            ],
                            "timeoutSeconds": 300,
                        }
                    }
                },
            }

            url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
            response = requests.post(url, headers=headers, json=payload, timeout=120)

            if response.status_code in (200, 201):
                data = response.json()
                service_url = data.get("status", {}).get("url")
                if not service_url:
                    service_url = f"https://{service_name}-{region}.run.app"
                vless = build_vless_link(service_url)
                logger.info(f"✅ تم النشر بنجاح على {region}")
                return service_url, region, vless
            else:
                error_text = response.text[:150]
                last_error = f"{region}: كود {response.status_code} - {error_text}"
                logger.warning(f"⚠️ فشل النشر على {region}")

        except Exception as e:
            last_error = f"{region}: {str(e)[:100]}"
            logger.warning(f"⚠️ استثناء على {region}: {e}")

        await asyncio.sleep(2)

    raise Exception(f"فشل النشر على كل المناطق. آخر خطأ: {last_error}")

# ===================================================================
# 9. أزرار متطورة (القائمة الرئيسية + التصفح + التأكيد + التفضيلات)
# ===================================================================
PER_PAGE = 4

def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🚀 بدء النشر (أرسل الرابط)", callback_data="deploy_btn")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats_btn")],
        [InlineKeyboardButton("⭐ تعيين المنطقة المفضلة", callback_data="pref_btn")],
        [InlineKeyboardButton("⚡ النشر التلقائي", callback_data="auto_btn")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_btn")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_ultimate_keyboard(regions: List[str], page: int = 0, preferred: str = None) -> InlineKeyboardMarkup:
    total = len(regions)
    if not regions:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ لا توجد مناطق", callback_data="noop")]])

    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    start, end = page * PER_PAGE, min((page + 1) * PER_PAGE, total)

    keyboard = []
    status_text = f"📋 الصفحة {page+1}/{total_pages} | {total} منطقة"
    if preferred:
        status_text += f" | ⭐ مفضلة: {KNOWN_REGIONS.get(preferred, preferred)}"
    keyboard.append([InlineKeyboardButton(status_text, callback_data="noop")])

    for i in range(start, end):
        code = regions[i]
        display = KNOWN_REGIONS.get(code, code)
        star = " ⭐" if code == preferred else ""
        keyboard.append([InlineKeyboardButton(f"🌍 {display}{star}", callback_data=f"select_{code}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"page_{page+1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton("🔄 إعادة فحص", callback_data="rescan"),
        InlineKeyboardButton("⚡ نشر تلقائي", callback_data="auto_deploy"),
        InlineKeyboardButton("🔙 القائمة", callback_data="main_menu")
    ])
    return InlineKeyboardMarkup(keyboard)

def build_confirm_keyboard(region: str) -> InlineKeyboardMarkup:
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("⭐ تعيين كمنطقة مفضلة", callback_data=f"set_pref_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])

# ===================================================================
# 10. معالجات البوت (الرئيسية)
# ===================================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v999 – النسخة الاحترافية الطويلة**\n"
        "اختر أحد الخيارات أدناه:",
        reply_markup=main_menu_keyboard()
    )

async def button_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "deploy_btn":
        await query.edit_message_text("🔗 **أرسل رابط Qwiklabs الآن:**")
        return WAITING_LINK

    elif data == "stats_btn":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT deploy_count, status FROM users WHERE user_id=?", (user_id,))
        user_row = c.fetchone()
        c.execute("SELECT region_code, success_count, fail_count FROM region_stats ORDER BY success_count DESC LIMIT 5")
        stats_rows = c.fetchall()
        conn.close()

        msg = "📊 **إحصائياتك:**\n"
        if user_row:
            msg += f"📦 عدد النشر: {user_row[0]}\n🔄 الحالة: {user_row[1]}\n\n"

        if stats_rows:
            msg += "🏆 **أفضل 5 مناطق:**\n"
            for r in stats_rows:
                msg += f"• {KNOWN_REGIONS.get(r[0], r[0])}: ✅ {r[1]} | ❌ {r[2]}\n"
        else:
            msg += "📭 لا توجد إحصائيات بعد."

        await query.edit_message_text(msg, reply_markup=main_menu_keyboard())
        return

    elif data == "pref_btn":
        await query.edit_message_text(
            "⭐ **تعيين المنطقة المفضلة:**\n"
            "أرسل رمز المنطقة (مثل: us-central1) أو استخدم الأزرار في قائمة النشر."
        )
        return WAITING_REGION

    elif data == "auto_btn":
        current = get_auto_deploy(user_id)
        new_state = not current
        set_auto_deploy(user_id, new_state)
        status = "مفعل" if new_state else "معطل"
        await query.edit_message_text(
            f"⚡ **النشر التلقائي:** {status}\n"
            f"{'✅ سيتم النشر تلقائياً عند إرسال الرابط' if new_state else '❌ سيُطلب منك اختيار المنطقة'}",
            reply_markup=main_menu_keyboard()
        )
        return

    elif data == "help_btn":
        await query.edit_message_text(
            "❓ **المساعدة:**\n"
            "• أرسل رابط Qwiklabs لبدء النشر.\n"
            "• اختر المنطقة من الأزرار.\n"
            "• استخدم النشر التلقائي لتجاوز الاختيار.\n"
            "• يمكنك تعيين منطقة مفضلة لتظهر أولاً.",
            reply_markup=main_menu_keyboard()
        )
        return

    return ConversationHandler.END

# ===================================================================
# 11. استقبال الرابط ومعالجته
# ===================================================================
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("🔄 **جاري الدخول إلى الـ Lab وبدء التجهيز...**\n✔ تم التحقق من صلاحية الرابط، سيتم ربط الحساب وبدء عملية الإنشاء...")

    try:
        token = await get_master_token(user_id, text, project_id)
        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions
        context.user_data["current_page"] = 0

        # المنطقة المفضلة
        preferred = get_preferred_region(user_id)
        if preferred and preferred in regions:
            context.user_data["default_region"] = preferred
        else:
            context.user_data["default_region"] = regions[0] if regions else "us-central1"

        region_list = "\n".join([f"  - {r}" for r in regions])
        await update.message.reply_text(
            f"📡 **جاري تحليل سياسات المشروع لاستخراج المناطق المسموح بها...**\n"
            f"✔ تم اكتشاف {len(regions)} منطقة مسموح بها:\n{region_list}"
        )

        # التحقق من النشر التلقائي
        if get_auto_deploy(user_id):
            default_region = context.user_data["default_region"]
            await update.message.reply_text(f"⚡ **النشر التلقائي مفعل.** سيتم النشر على المنطقة المفضلة: {KNOWN_REGIONS.get(default_region, default_region)}")

            try:
                service_url, used_region, vless = await deploy_with_fallback(project_id, token, default_region, regions)
                increment_deploy_count(user_id)
                add_deploy_history(user_id, text, service_url, vless, used_region, success=1)

                result = (
                    f"✅ **تم النشر التلقائي بنجاح!**\n"
                    f"🌍 المنطقة: {KNOWN_REGIONS.get(used_region, used_region)}\n"
                    f"🌐 رابط Cloud Run:\n{service_url}\n\n"
                    f"🔗 رابط VLESS:\n{vless}"
                )
                await update.message.reply_text(result)
                context.user_data.clear()
                return ConversationHandler.END
            except Exception as e:
                await update.message.reply_text(f"⚠️ فشل النشر التلقائي: {str(e)[:100]}\nسيتم عرض المناطق للاختيار.")

        # عرض الأزرار
        keyboard = build_ultimate_keyboard(regions, 0, preferred)
        await update.message.reply_text(
            "👇 **اختر المنطقة التي تريد النشر عليها:**",
            reply_markup=keyboard
        )
        return WAITING_REGION

    except Exception as e:
        log_failure(user_id, "INIT_FAIL", str(e))
        await update.message.reply_text(f"❌ فشل:\n{str(e)[:200]}")
        return ConversationHandler.END

# ===================================================================
# 12. معالج الأزرار الثانوية (التفاعل الكامل)
# ===================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "noop":
        return

    # القائمة الرئيسية
    if data == "main_menu":
        await query.edit_message_text(
            "🔥 **القائمة الرئيسية**\nاختر أحد الخيارات:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # النشر التلقائي السريع
    if data == "auto_deploy":
        default_region = context.user_data.get("default_region", "us-central1")
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        lab_url = context.user_data.get("lab_url")
        all_regions = context.user_data.get("regions", [])

        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة")
            return ConversationHandler.END

        await query.edit_message_text(f"⚡ **جاري النشر التلقائي على {KNOWN_REGIONS.get(default_region, default_region)}...**")

        try:
            service_url, used_region, vless = await deploy_with_fallback(project_id, token, default_region, all_regions)
            increment_deploy_count(user_id)
            add_deploy_history(user_id, lab_url, service_url, vless, used_region, success=1)

            result = (
                f"✅ **تم النشر التلقائي!**\n"
                f"🌍 المنطقة: {KNOWN_REGIONS.get(used_region, used_region)}\n"
                f"🌐 رابط Cloud Run:\n{service_url}\n\n"
                f"🔗 رابط VLESS:\n{vless}"
            )
            await query.message            await query.message.reply_text(result)
        except Exception as e:
            await query.message.reply_text(f"❌ فشل النشر:\n{str(e)[:300]}")
        context.user_data.clear()
        return ConversationHandler.END

    # إعادة فحص
    if data == "rescan":
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة")
            return ConversationHandler.END
        await query.edit_message_text("🔄 جاري إعادة الفحص...")
        try:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)
            context.user_data["regions"] = regions
            context.user_data["current_page"] = 0
            preferred = get_preferred_region(user_id)
            keyboard = build_ultimate_keyboard(regions, 0, preferred)
            await query.edit_message_text(f"📡 تم إعادة الفحص: {len(regions)} منطقة", reply_markup=keyboard)
            return WAITING_REGION
        except Exception as e:
            await query.edit_message_text(f"❌ فشل إعادة الفحص: {str(e)[:150]}")
            return WAITING_REGION

    # تغيير الصفحة
    if data.startswith("page_"):
        page = int(data.replace("page_", ""))
        regions = context.user_data.get("regions", [])
        if not regions:
            await query.edit_message_text("❌ لا توجد مناطق")
            return ConversationHandler.END
        context.user_data["current_page"] = page
        preferred = get_preferred_region(user_id)
        keyboard = build_ultimate_keyboard(regions, page, preferred)
        await query.edit_message_text(f"📡 صفحة {page+1}:", reply_markup=keyboard)
        return WAITING_REGION

    # اختيار منطقة → تأكيد
    if data.startswith("select_"):
        region = data.replace("select_", "")
        context.user_data["pending_region"] = region
        keyboard = build_confirm_keyboard(region)
        await query.edit_message_text(
            f"⚠️ **تأكيد النشر**\n"
            f"المنطقة: {KNOWN_REGIONS.get(region, region)}\n"
            f"هل أنت متأكد من النشر عليها؟",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY

    # تعيين منطقة مفضلة
    if data.startswith("set_pref_"):
        region = data.replace("set_pref_", "")
        set_preferred_region(user_id, region)
        await query.edit_message_text(
            f"⭐ **تم تعيين {KNOWN_REGIONS.get(region, region)} كمنطقة مفضلة!**\n"
            f"ستظهر أولاً في القوائم المستقبلية.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # رجوع من التأكيد
    if data == "back":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        preferred = get_preferred_region(user_id)
        keyboard = build_ultimate_keyboard(regions, page, preferred)
        await query.edit_message_text("📡 اختر المنطقة:", reply_markup=keyboard)
        return WAITING_REGION

    # تأكيد النشر النهائي
    if data.startswith("confirm_"):
        region = data.replace("confirm_", "")
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        lab_url = context.user_data.get("lab_url")
        all_regions = context.user_data.get("regions", [])

        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة")
            return ConversationHandler.END

        await query.edit_message_text(f"🚀 **جاري النشر على {KNOWN_REGIONS.get(region, region)}...**")

        try:
            service_url, used_region, vless = await deploy_with_fallback(project_id, token, region, all_regions)
            increment_deploy_count(user_id)
            add_deploy_history(user_id, lab_url, service_url, vless, used_region, success=1)

            # تحديث المنطقة المفضلة إذا لم تكن موجودة
            if not get_preferred_region(user_id):
                set_preferred_region(user_id, used_region)

            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 **المنطقة المستخدمة:** `{KNOWN_REGIONS.get(used_region, used_region)}`\n"
                f"🌐 **رابط Cloud Run:**\n`{service_url}`\n\n"
                f"🔗 **رابط VLESS:**\n`{vless}`\n\n"
                f"📌 **ملاحظة:** الرابط صالح لمدة ساعة أو حتى انتهاء المشروع."
            )
            await query.message.reply_text(result, reply_markup=main_menu_keyboard())
        except Exception as e:
            error_msg = str(e)[:300]
            log_failure(user_id, "DEPLOY_FAIL", error_msg)
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(
                f"❌ **فشل النشر:**\n`{error_msg}`\n\n"
                f"💡 **حلول:**\n"
                f"• حاول اختيار منطقة أخرى.\n"
                f"• تحقق من صلاحية التوكن (أعد إرسال الرابط).\n"
                f"• تأكد من أن المشروع لا يزال نشطاً.",
                reply_markup=main_menu_keyboard()
            )
        context.user_data.clear()
        return ConversationHandler.END

    return WAITING_REGION

# ===================================================================
# 13. التشغيل الرئيسي
# ===================================================================
def main():
    """الوظيفة الرئيسية لتشغيل البوت"""
    app = ApplicationBuilder().token(TOKEN).build()

    # محادثة رئيسية واحدة تجمع كل الحالات
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_main_handler, pattern="^(deploy_btn|stats_btn|pref_btn|auto_btn|help_btn)$")
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(button_handler, pattern="^(select_|page_|rescan|auto_deploy|main_menu|noop)$")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(button_handler, pattern="^(confirm_|back|set_pref_)")]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("❌ تم الإلغاء"))],
    )

    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (النسخة الاحترافية الطويلة) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()