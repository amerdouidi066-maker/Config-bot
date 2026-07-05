#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║     SHADOW LEGION v999 – ULTIMATE + MAIN MENU BUTTONS         ║
║   الطول: 900+ سطر  │  أزرار رئيسية متطورة  │  7 طبقات مقاومة ║
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
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
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

USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)
DB_PATH = "shadow_ultimate.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (القائمة الرئيسية بأزرار) بدأ التشغيل...")

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
}

# ===================================================================
# 2. قاعدة البيانات المتقدمة
# ===================================================================
def init_ultimate_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT, password TEXT,
            region TEXT DEFAULT 'us-central1',
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            manual_token TEXT,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT, expiry TIMESTAMP, project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER, project_id TEXT,
            allowed_regions TEXT, scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, project_id)
        );
        CREATE TABLE IF NOT EXISTS deploy_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, lab_url TEXT, service_url TEXT,
            vless_link TEXT, region_used TEXT,
            deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1, error_msg TEXT
        );
        CREATE TABLE IF NOT EXISTS failure_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, error_type TEXT,
            error_detail TEXT, logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS region_analytics (
            region_code TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات المتقدمة جاهزة")

init_ultimate_db()

# ===================================================================
# 3. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, email, password, region, deploy_count, status, manual_token, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "email": row[1], "password": row[2],
            "region": row[3], "deploy_count": row[4], "status": row[5],
            "manual_token": row[6], "last_activity": row[7]
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
    c.execute("INSERT OR REPLACE INTO scan_cache (user_id, project_id, allowed_regions) VALUES (?,?,?)",
              (user_id, project_id, json.dumps(regions)))
    conn.commit()
    conn.close()

def get_scan_cache(user_id: int, project_id: str) -> Optional[List[str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT allowed_regions FROM scan_cache WHERE user_id=? AND project_id=?", (user_id, project_id))
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
    c = conn.cursor()
    if success:
        c.execute("INSERT INTO region_analytics (region_code, success_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET success_count = success_count + 1", (region,))
    else:
        c.execute("INSERT INTO region_analytics (region_code, fail_count) VALUES (?,1) ON CONFLICT(region_code) DO UPDATE SET fail_count = fail_count + 1", (region,))
    conn.commit()
    conn.close()

def log_failure(user_id: int, error_type: str, error_detail: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO failure_logs (user_id, error_type, error_detail) VALUES (?,?,?)",
              (user_id, error_type, error_detail[:500]))
    conn.commit()
    conn.close()

# ===================================================================
# 4. دوال مساعدة
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'/projects/([^/?]+)', decoded)
    return match.group(1) if match else None

def build_vless_link(service_url: str, seed: str = "shadow_v999") -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5((seed + str(time.time()) + os.urandom(4).hex()).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#ShadowUltimate"

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
# 5. استخراج التوكن بـ Playwright
# ===================================================================
def extract_token_playwright_ultimate(email: str, password: str, project_id: str, max_retries: int = 3) -> str:
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
                    viewport={"width": 1280, "height": 720}
                )
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                page.goto("https://accounts.google.com/", timeout=30000)
                page.wait_for_selector("#identifierId", timeout=15000)
                page.fill("#identifierId", email)
                page.click("#identifierNext")
                page.wait_for_selector("input[name='Passwd']", timeout=20000)
                page.fill("input[name='Passwd']", password)
                page.click("#passwordNext")
                page.wait_for_timeout(5000)

                token = None
                for target_url in [
                    f"https://console.cloud.google.com/run?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}&hl=en"
                ]:
                    page.goto(target_url, timeout=45000)
                    try:
                        page.wait_for_selector("body", timeout=30000)
                        page.wait_for_timeout(7000)
                    except PlaywrightTimeoutError:
                        pass
                    token = page.evaluate("""
                        () => {
                            for (let k of ['access_token','id_token','gapi_token','oauth_token','gc_token']) {
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
                    if token and len(token) > 40:
                        browser.close()
                        return token
                browser.close()
        except Exception as e:
            last_exception = str(e)
            logger.warning(f"⚠️ المحاولة {attempt} فشلت: {e}")
        time.sleep(5)
    raise Exception(f"فشل استخراج التوكن بعد {max_retries} محاولات: {last_exception}")

def get_master_token(user_id: int, email: str, password: str, project_id: str) -> str:
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        if test_token_validity(USER_TOKEN_OVERRIDE, project_id):
            save_cached_token(user_id, USER_TOKEN_OVERRIDE, project_id)
            return USER_TOKEN_OVERRIDE
    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        return cached
    token = extract_token_playwright_ultimate(email, password, project_id)
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

def deploy_with_fallback(project_id: str, token: str, preferred: str, all_regions: List[str]) -> Tuple[str, str, str]:
    regions_to_try = [preferred] + [r for r in all_regions if r != preferred]
    last_error = ""
    for region in regions_to_try:
        try:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            service_name = f"shadow-{int(time.time())}-{region[:5]}"
            payload = {
                "apiVersion": "serving.knative.dev/v1",
                "kind": "Service",
                "metadata": {"name": service_name},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}],
                            "timeoutSeconds": 300
                        }
                    }
                }
            }
            url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code in (200, 201):
                service_url = resp.json().get("status", {}).get("url")
                if not service_url:
                    service_url = f"https://{service_name}-{region}.run.app"
                vless = build_vless_link(service_url)
                return service_url, region, vless
            else:
                last_error = f"{region}: كود {resp.status_code}"
        except Exception as e:
            last_error = f"{region}: {str(e)[:100]}"
        time.sleep(2)
    raise Exception(f"فشل النشر على كل المناطق. آخر خطأ: {last_error}")

# ===================================================================
# 7. أزرار متطورة (القائمة الرئيسية + التصفح)
# ===================================================================
PER_PAGE = 4

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """لوحة الأزرار الرئيسية التي تظهر عند /start"""
    keyboard = [
        [InlineKeyboardButton("🔑 تعيين البريد وكلمة المرور", callback_data="set_creds_btn")],
        [InlineKeyboardButton("🚀 بدء النشر (أرسل الرابط)", callback_data="deploy_btn")],
        [InlineKeyboardButton("📊 حالتك", callback_data="status_btn")],
        [InlineKeyboardButton("❌ إلغاء / مساعدة", callback_data="help_btn")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_ultimate_keyboard(regions: List[str], page: int = 0) -> InlineKeyboardMarkup:
    total = len(regions)
    if not regions:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ لا توجد مناطق", callback_data="noop")]])
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    start, end = page * PER_PAGE, min((page + 1) * PER_PAGE, total)
    keyboard = []
    keyboard.append([InlineKeyboardButton(f"📋 {page+1}/{total_pages} | إجمالي {total} منطقة", callback_data="noop")])
    for i in range(start, end):
        code = regions[i]
        display = KNOWN_REGIONS.get(code, code)
        keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"select_{code}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton("🔄 إعادة فحص", callback_data="rescan"),
        InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
        InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
    ])
    return InlineKeyboardMarkup(keyboard)

def build_confirm_keyboard(region: str) -> InlineKeyboardMarkup:
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])

# ===================================================================
# 8. معالجات الأوامر والأزرار الرئيسية
# ===================================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v999 – القائمة الرئيسية**\nاختر أحد الخيارات أدناه:",
        reply_markup=main_menu_keyboard()
    )

async def button_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار الرئيسية (من القائمة)"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "set_creds_btn":
        await query.edit_message_text(
            "📧 **أرسل بريدك الإلكتروني** (أو اكتب /cancel للإلغاء):"
        )
        return WAITING_EMAIL

    elif data == "deploy_btn":
        user = get_user(user_id)
        if not user or not user.get("email") or not user.get("password"):
            await query.edit_message_text(
                "❌ يجب تعيين البريد وكلمة المرور أولاً.\nاستخدم زر 'تعيين البريد وكلمة المرور'."
            )
            return
        await query.edit_message_text(
            "🔗 **أرسل رابط Qwiklabs الآن:**"
        )
        return WAITING_LINK

    elif data == "status_btn":
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("❌ لا توجد بيانات مسجلة.")
            return
        token_status = "✅" if get_cached_token(user_id) else "❌"
        msg = (
            f"📧 البريد: {user['email']}\n"
            f"📊 عدد النشر: {user['deploy_count']}\n"
            f"🔑 التوكن: {token_status}\n"
            f"🔄 الحالة: {user['status']}"
        )
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard())
        return

    elif data == "help_btn":
        await query.edit_message_text(
            "❓ **المساعدة:**\n"
            "• استخدم 'تعيين البريد' لحفظ بيانات دخول Google.\n"
            "• استخدم 'بدء النشر' لإرسال رابط Qwiklabs.\n"
            "• يمكنك أيضاً استخدام الأوامر: /set_creds, /status, /cancel",
            reply_markup=main_menu_keyboard()
        )
        return

    return ConversationHandler.END

# ===================================================================
# 9. استقبال البريد وكلمة المرور (خطوتين)
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
# 10. استقبال الرابط وعرض الأزرار (معدل)
# ===================================================================
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح. أرسل رابطاً يبدأ بـ http")
        return WAITING_LINK
    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id في الرابط")
        return WAITING_LINK
    user = get_user(user_id)
    if not user or not user["email"] or not user["password"]:
        await update.message.reply_text(
            "❌ بيانات الدخول غير مسجلة. استخدم زر 'تعيين البريد' أولاً.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id
    await update.message.reply_text("🔄 جاري التجهيز (قد يستغرق 30-60 ثانية)...")
    try:
        token = get_master_token(user_id, user["email"], user["password"], project_id)
        context.user_data["token"] = token
        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)
        context.user_data["regions"] = regions
        context.user_data["current_page"] = 0
        keyboard = build_ultimate_keyboard(regions, 0)
        await update.message.reply_text(
            f"📡 **تم اكتشاف {len(regions)} منطقة.**\nاختر المنطقة:",
            reply_markup=keyboard
        )
        return WAITING_REGION
    except Exception as e:
        log_failure(user_id, "INIT_FAIL", str(e))
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")
        return ConversationHandler.END

# ===================================================================
# 11. معالج الأزرار الثانوية (التصفح، الاختيار، التأكيد، إلخ)
# ===================================================================
async def button_secondary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "noop":
        return

    # العودة للقائمة الرئيسية
    if data == "main_menu":
        await query.edit_message_text(
            "🔥 **القائمة الرئيسية**\nاختر أحد الخيارات:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # إلغاء
    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    # إعادة فحص
    if data == "rescan":
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة، أعد الإرسال")
            return ConversationHandler.END
        await query.edit_message_text("🔄 جاري إعادة الفحص...")
        try:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)
            context.user_data["regions"] = regions
            context.user_data["current_page"] = 0
            keyboard = build_ultimate_keyboard(regions, 0)
            await query.edit_message_text(f"📡 تم إعادة الفحص: {len(regions)} منطقة", reply_markup=keyboard)
            return WAITING_REGION
        except Exception as e:
            await query.edit_message_text(f"❌ فشل إعادة الفحص: {str(e)[:150]}")
            return WAITING_REGION

    # الإحصائيات
    if data == "stats":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT region_code, success_count, fail_count FROM region_analytics")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("📊 لا توجد إحصائيات بعد")
            return
        msg = "📊 **إحصائيات المناطق:**\n"
        for r in rows:
            msg += f"• {r[0]}: ✅ {r[1]} | ❌ {r[2]}\n"
        await query.edit_message_text(msg)
        return

    # تغيير الصفحة
    if data.startswith("page_"):
        page = int(data.replace("page_", ""))
        regions = context.user_data.get("regions", [])
        if not regions:
            await query.edit_message_text("❌ لا توجد مناطق")
            return ConversationHandler.END
        context.user_data["current_page"] = page
        keyboard = build_ultimate_keyboard(regions, page)
        await query.edit_message_text(f"📡 صفحة {page+1}:", reply_markup=keyboard)
        return WAITING_REGION

    # اختيار منطقة → تأكيد
    if data.startswith("select_"):
        region = data.replace("select_", "")
        context.user_data["pending_region"] = region
        keyboard = build_confirm_keyboard(region)
        await query.edit_message_text(
            f"⚠️ **تأكيد النشر**\nالمنطقة: {KNOWN_REGIONS.get(region, region)}\nهل أنت متأكد؟",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY

    # رجوع من التأكيد
    if data == "back":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        keyboard = build_ultimate_keyboard(regions, page)
        await query.edit_message_text("📡 اختر المنطقة:", reply_markup=keyboard)
        return WAITING_REGION

    # تأكيد النشر
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
            service_url, used_region, vless = deploy_with_fallback(project_id, token, region, all_regions)
            user = get_user(user_id)
            update_user(user_id, deploy_count=(user["deploy_count"] + 1) if user else 1, status="completed")
            add_deploy_history(user_id, lab_url, service_url, vless, used_region, success=1)
            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"🌍 المنطقة المستخدمة: {KNOWN_REGIONS.get(used_region, used_region)}\n"
                f"🌐 رابط Cloud Run:\n{service_url}\n\n"
                f"🔗 رابط VLESS:\n{vless}"
            )
            await query.message.reply_text(result, reply_markup=main_menu_keyboard())
        except Exception as e:
            error_msg = str(e)[:300]
            log_failure(user_id, "DEPLOY_FAIL", error_msg)
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(f"❌ فشل النشر:\n{error_msg}")
        context.user_data.clear()
        return ConversationHandler.END

    return WAITING_REGION

# ===================================================================
# 12. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # محادثة رئيسية للأزرار
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_main_handler, pattern="^(set_creds_btn|deploy_btn|status_btn|help_btn)$")
        ],
        states={
            WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(button_secondary_handler, pattern="^(select_|page_|rescan|stats|cancel|noop|main_menu)")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(button_secondary_handler, pattern="^(confirm_|back)")],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("❌ تم الإلغاء"))],
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (القائمة الرئيسية بأزرار) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()