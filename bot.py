#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   SHADOW LEGION v999 – FULL CREDS + REGION SELECTION          ║
║   الطول: 800+ سطر  │  يسأل عن البريد وكلمة المرور           ║
║   يسجل الدخول تلقائياً  │  أزرار متطورة  │  احترافي          ║
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
from typing import Optional, List, Dict, Tuple

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
    raise ValueError("❌ TOKEN غير موجود في البيئة")

DB_PATH = "shadow_creds.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (Full Creds + Region) بدأ التشغيل...")

# حالات المحادثة
WAITING_LINK, WAITING_REGION, CONFIRM_DEPLOY, WAITING_EMAIL, WAITING_PASSWORD = range(5)

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
}

# ===================================================================
# 2. قاعدة البيانات المتقدمة (6 جداول)
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            password TEXT,
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
        CREATE TABLE IF NOT EXISTS region_stats (
            region_code TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            preferred_region TEXT
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات المتقدمة (6 جداول) جاهزة")

init_db()

# ===================================================================
# 3. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, email, password, deploy_count, status, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "email": row[1],
            "password": row[2],
            "deploy_count": row[3],
            "status": row[4],
            "last_activity": row[5]
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

def build_vless_link(service_url: str, seed: str = "shadow_v999") -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5((seed + str(time.time()) + os.urandom(4).hex()).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#FullTunnel"

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
# 5. استخراج التوكن مع تسجيل الدخول
# ===================================================================
async def extract_token_with_login(link: str, project_id: str, email: str, password: str) -> str:
    if not email or not password:
        raise Exception("❌ البريد أو كلمة المرور غير مضبوطة. استخدم /set_creds")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--incognito",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        # 1. فتح الرابط
        logger.info(f"🌐 فتح الرابط: {link}")
        await page.goto(link, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # 2. تسجيل الدخول
        try:
            email_field = await page.query_selector("input[type='email'], input#identifierId")
            if email_field:
                logger.info("📧 جاري تسجيل الدخول...")
                await page.fill("input[type='email'], input#identifierId", email)
                await page.click("button:has-text('Next'), button#identifierNext")
                await page.wait_for_timeout(3000)

                await page.wait_for_selector("input[type='password'], input[name='Passwd']", timeout=15000)
                await page.fill("input[type='password'], input[name='Passwd']", password)
                await page.click("button:has-text('Next'), button#passwordNext")
                await page.wait_for_timeout(5000)
                logger.info("✅ تم تسجيل الدخول")
            else:
                logger.info("✅ لا توجد صفحة تسجيل دخول، نكمل مباشرة")
        except Exception as e:
            logger.warning(f"⚠️ فشل تسجيل الدخول: {e}")

        # 3. التوجه إلى Cloud Run Console
        console_url = f"https://console.cloud.google.com/run?project={project_id}&hl=en"
        logger.info(f"🔗 التوجه إلى Console: {console_url}")
        await page.goto(console_url, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(8000)

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
            logger.info("✅ تم استخراج التوكن")
            return token
        raise Exception("لم أجد التوكن بعد تسجيل الدخول")

async def get_master_token(user_id: int, link: str, project_id: str, email: str, password: str) -> str:
    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        logger.info("♻️ استخدام التوكن المخبأ")
        return cached
    token = await extract_token_with_login(link, project_id, email, password)
    if token and test_token_validity(token, project_id):
        save_cached_token(user_id, token, project_id)
        return token
    raise Exception("تعذر الحصول على توكن صالح")

# ===================================================================
# 6. فحص المناطق والنشر
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            allowed = [loc["locationId"] for loc in data.get("locations", []) if loc.get("state") == "ENABLED"]
            if allowed:
                return allowed
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب المناطق: {e}")
    return ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]

def deploy_service(project_id: str, token: str, region: str) -> Tuple[str, str]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"my-app-{int(time.time())}"
    payload = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]
                }
            }
        }
    }
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code not in (200, 201):
        raise Exception(f"فشل النشر ({resp.status_code})")
    service_url = resp.json().get("status", {}).get("url")
    if not service_url:
        service_url = f"https://{service_name}-{region}.run.app"
    return service_url, build_vless_link(service_url)

# ===================================================================
# 7. أزرار متطورة (Pagination + Confirm + Preferences)
# ===================================================================
PER_PAGE = 4

def build_region_keyboard(regions: List[str], page: int = 0, preferred: str = None) -> InlineKeyboardMarkup:
    total = len(regions)
    if not regions:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ لا توجد مناطق", callback_data="noop")]])
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    start, end = page * PER_PAGE, min((page + 1) * PER_PAGE, total)
    keyboard = []
    status_text = f"📋 الصفحة {page+1}/{total_pages} | إجمالي {total} منطقة"
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
        InlineKeyboardButton("⭐ تعيين مفضلة", callback_data="pref_btn"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)

def build_confirm_keyboard(region: str) -> InlineKeyboardMarkup:
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 بدء النشر (أرسل الرابط)", callback_data="deploy_btn")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats_btn")],
        [InlineKeyboardButton("⭐ المنطقة المفضلة", callback_data="pref_info_btn")],
        [InlineKeyboardButton("🔑 تعيين البريد", callback_data="set_creds_btn")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_btn")]
    ])

# ===================================================================
# 8. معالجات البوت
# ===================================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user and user.get("email"):
        await update.message.reply_text(
            "🔥 **Shadow Legion – Full Edition**\n"
            f"📧 بريدك: {user['email']}\n"
            "اختر أحد الخيارات أدناه:",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "🔥 **Shadow Legion – Full Edition**\n"
            "يرجى تعيين بريدك وكلمة المرور أولاً.\n"
            "استخدم زر 'تعيين البريد' أو الأمر /set_creds",
            reply_markup=main_menu_keyboard()
        )

async def button_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "set_creds_btn":
        await query.edit_message_text("📧 **أرسل بريدك الإلكتروني:**")
        return WAITING_EMAIL

    elif data == "deploy_btn":
        user = get_user(user_id)
        if not user or not user.get("email") or not user.get("password"):
            await query.edit_message_text("❌ يرجى تعيين البريد وكلمة المرور أولاً.\nاستخدم زر 'تعيين البريد'.")
            return ConversationHandler.END
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
        return ConversationHandler.END

    elif data == "pref_info_btn":
        preferred = get_preferred_region(user_id)
        if preferred:
            msg = f"⭐ منطقتك المفضلة: {KNOWN_REGIONS.get(preferred, preferred)}"
        else:
            msg = "⭐ لم تحدد منطقة مفضلة بعد.\nاختر منطقة من القائمة واضغط 'تعيين مفضلة'."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    elif data == "help_btn":
        await query.edit_message_text(
            "❓ **المساعدة:**\n"
            "• /set_creds <البريد> <كلمة_السر> – تعيين بيانات الدخول.\n"
            "• أرسل رابط Qwiklabs لبدء النشر.\n"
            "• اختر المنطقة من الأزرار.\n"
            "• يمكنك تعيين منطقة مفضلة.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    return ConversationHandler.END

# ===================================================================
# 9. استقبال البريد وكلمة المرور
# ===================================================================
async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    email = update.message.text.strip()
    if not email or "@" not in email:
        await update.message.reply_text("❌ بريد غير صالح. أرسل بريداً صحيحاً (أو /cancel)")
        return WAITING_EMAIL
    context.user_data["temp_email"] = email
    await update.message.reply_text("🔑 **أرسل كلمة المرور الآن:**")
    return WAITING_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    email = context.user_data.get("temp_email")
    if not email:
        await update.message.reply_text("❌ انتهت الجلسة، ابدأ من جديد بـ /start")
        return ConversationHandler.END
    update_user(user_id, email=email, password=password)
    context.user_data.clear()
    await update.message.reply_text(
        "✅ **تم حفظ البريد وكلمة المرور بنجاح!**",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ===================================================================
# 10. استقبال الرابط
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

    user = get_user(user_id)
    if not user or not user.get("email") or not user.get("password"):
        await update.message.reply_text("❌ يرجى تعيين البريد وكلمة المرور أولاً.\nاستخدم زر 'تعيين البريد' أو /set_creds")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("🔄 **جاري الدخول إلى الـ Lab وبدء التجهيز...**\n✔ تم التحقق من صلاحية الرابط، سيتم ربط الحساب وبدء عملية الإنشاء...")

    try:
        token = await get_master_token(user_id, text, project_id, user["email"], user["password"])
        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions
        context.user_data["current_page"] = 0

        preferred = get_preferred_region(user_id)
        if preferred and preferred in regions:
            context.user_data["preferred"] = preferred

        region_list = "\n".join([f"  - {r}" for r in regions])
        await update.message.reply_text(
            f"📡 **جاري تحليل سياسات المشروع لاستخراج المناطق المسموح بها...**\n"
            f"✔ تم اكتشاف {len(regions)} منطقة مسموح بها:\n{region_list}"
        )

        keyboard = build_region_keyboard(regions, 0, preferred)
        await update.message.reply_text(
            "👇 **اختر المنطقة التي تريد النشر عليها:**",
            reply_markup=keyboard
        )
        return WAITING_REGION

    except Exception as e:
        await update.message.reply_text(f"❌ فشل:\n{str(e)[:300]}")
        return ConversationHandler.END

# ===================================================================
# 11. معالج الأزرار الثانوية
# ===================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "noop":
        return

    # إلغاء
    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    # تعيين منطقة مفضلة
    if data == "pref_btn":
        pending = context.user_data.get("pending_region")
        if pending:
            set_preferred_region(user_id, pending)
            await query.edit_message_text(
                f"⭐ **تم تعيين {KNOWN_REGIONS.get(pending, pending)} كمنطقة مفضلة!**"
            )
            regions = context.user_data.get("regions", [])
            page = context.user_data.get("current_page", 0)
            preferred = get_preferred_region(user_id)
            keyboard = build_region_keyboard(regions, page, preferred)
            await query.message.reply_text("📡 اختر المنطقة:", reply_markup=keyboard)
            return WAITING_REGION
        else:
            await query.edit_message_text("⚠️ اختر منطقة أولاً ثم اضغط 'تعيين مفضلة'.")
            return WAITING_REGION

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
            keyboard = build_region_keyboard(regions, 0, preferred)
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
        keyboard = build_region_keyboard(regions, page, preferred)
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

    # رجوع من التأكيد
    if data == "back":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        preferred = get_preferred_region(user_id)
        keyboard = build_region_keyboard(regions, page, preferred)
        await query.edit_message_text("📡 اختر المنطقة:", reply_markup=keyboard)
        return WAITING_REGION

    # تأكيد النشر
    if data.startswith("confirm_"):
        region = data.replace("confirm_", "")
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        lab_url = context.user_data.get("lab_url")

        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة")
            return ConversationHandler.END

        await query.edit_message_text(f"🚀 **جاري النشر على {KNOWN_REGIONS.get(region, region)}...**")

        try:
            service_url, vless = deploy_service(project_id, token, region)
            increment_deploy_count(user_id)
            add_deploy_history(user_id, lab_url, service_url, vless, region, success=1)

            if not get_preferred_region(user_id):
                set_preferred_region(user_id, region)

            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 **المنطقة المستخدمة:** `{KNOWN_REGIONS.get(region, region)}`\n"
                f"🌐 **رابط Cloud Run:**\n`{service_url}`\n\n"
                f"🔗 **رابط VLESS:**\n`{vless}`\n\n"
                f"📌 الرابط صالح لمدة ساعة أو حتى انتهاء المشروع."
            )
            await query.message.reply_text(result, reply_markup=main_menu_keyboard())

        except Exception as e:
            error_msg = str(e)[:300]
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(
                f"❌ **فشل النشر:**\n`{error_msg}`\n\n"
                f"💡 حاول اختيار منطقة أخرى أو أعد إرسال الرابط.",
                reply_markup=main_menu_keyboard()
            )

        context.user_data.clear()
        return ConversationHandler.END

    return WAITING_REGION

# ===================================================================
# 12. أوامر مباشرة
# ===================================================================
async def set_creds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد وكلمة المرور!")
    except IndexError:
        await update.message.reply_text("❌ /set_creds <البريد> <كلمة_السر>")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 13. التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_main_handler, pattern="^(deploy_btn|stats_btn|pref_info_btn|set_creds_btn|help_btn)$")
        ],
        states={
            WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(button_handler, pattern="^(select_|page_|rescan|pref_btn|cancel|noop)$")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(button_handler, pattern="^(confirm_|back)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set_creds", set_creds_command))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (Full Creds + Region) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()