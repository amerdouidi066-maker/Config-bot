#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v999 – COOKIE SUPPORT (يدوي + تلقائي)
يستخدم الكوكيز المستخرجة يدوياً أو تلقائياً من المتصفح.
"""

import os
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
    raise ValueError("❌ TOKEN غير موجود")

DB_PATH = "shadow_cookie_manual.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (Cookie Manual) بدأ التشغيل...")

WAITING_LINK, WAITING_REGION, CONFIRM_DEPLOY = range(3)

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
# 2. قاعدة البيانات
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle'
        );
        CREATE TABLE IF NOT EXISTS cookie_cache (
            user_id INTEGER PRIMARY KEY,
            cookie_string TEXT,
            expiry TIMESTAMP,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER,
            project_id TEXT,
            regions TEXT,
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
    """)
    conn.commit()
    conn.close()
init_db()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT deploy_count, status FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"deploy_count": row[0], "status": row[1]} if row else None

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", list(kwargs.values()) + [user_id])
    else:
        cols = ",".join(kwargs.keys())
        vals = list(kwargs.values())
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {','.join(['?']*len(vals))})", [user_id] + vals)
    conn.commit()
    conn.close()

def get_cached_cookies(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT cookie_string, expiry, project_id FROM cookie_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0], row[2]
    return None, None

def save_cached_cookies(user_id, cookie_string, project_id, expiry_seconds=3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cookie_cache (user_id, cookie_string, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, cookie_string, expiry.isoformat(), project_id))
    conn.commit()
    conn.close()

def save_scan_cache(user_id, project_id, regions):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO scan_cache (user_id, project_id, regions) VALUES (?,?,?)",
              (user_id, project_id, json.dumps(regions)))
    conn.commit()
    conn.close()

def get_scan_cache(user_id, project_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT regions FROM scan_cache WHERE user_id=? AND project_id=?", (user_id, project_id))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def add_history(user_id, lab_url, service_url, vless, region, success=1, error_msg=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()

def increment_deploy_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET deploy_count = deploy_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ===================================================================
# 3. دوال مساعدة
# ===================================================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'/projects/([^/?]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5(("cookie_manual" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#CookieManualTunnel"

def test_cookies(cookie_string, project_id):
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {
            "Cookie": cookie_string,
            "X-Goog-User-Project": project_id
        }
        r = requests.get(url, headers=headers, timeout=15)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# 4. استخراج الكوكيز من Playwright (محاولة تلقائية)
# ===================================================================
async def extract_cookies_auto(link: str, project_id: str) -> Tuple[Optional[str], bool, List[str]]:
    steps = []
    try:
        steps.append("🚀 فتح الرابط في متصفح متخفي...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--incognito"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            steps.append("⏳ فتح الرابط...")
            await page.goto(link, timeout=60000, wait_until="networkidle")
            await page.wait_for_timeout(3000)

            try:
                btn = await page.query_selector("text=Open Console")
                if btn:
                    await btn.click()
                    steps.append("✅ النقر على Open Console")
                else:
                    cl = await page.query_selector('a[href*="console.cloud.google.com"]')
                    if cl:
                        await cl.click()
                        steps.append("✅ النقر على رابط Console")
                    else:
                        await page.goto(f"https://console.cloud.google.com/run?project={project_id}&hl=en", timeout=60000)
                        steps.append("⚠️ التوجه مباشرة إلى Cloud Run")
            except:
                pass

            for attempt in range(15):
                if "console.cloud.google.com" in page.url:
                    steps.append(f"✅ تم التوجيه (المحاولة {attempt+1})")
                    break
                await page.wait_for_timeout(3000)

            steps.append("⏳ انتظار تحميل الصفحة...")
            await page.wait_for_timeout(8000)

            # استخراج الكوكيز من المتصفح
            steps.append("🍪 استخراج الكوكيز من الجلسة...")
            cookies = await context.cookies()
            steps.append(f"✅ تم استخراج {len(cookies)} كوكي")

            # تحويل الكوكيز إلى سلسلة
            cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

            # إضافة كوكيز Console
            console_cookies = await context.cookies("https://console.cloud.google.com")
            if console_cookies:
                for c in console_cookies:
                    if c not in cookies:
                        cookie_string += f"; {c['name']}={c['value']}"
                steps.append(f"✅ تمت إضافة كوكيز Console")

            await browser.close()

            if cookie_string and len(cookie_string) > 100:
                steps.append("✅ تم استخراج الكوكيز بنجاح")
                return cookie_string, False, steps
            else:
                steps.append("❌ الكوكيز المستخرجة غير كافية")
                return None, True, steps

    except Exception as e:
        steps.append(f"❌ خطأ: {str(e)[:100]}")
        return None, True, steps

# ===================================================================
# 5. الحصول على الكوكيز (يدوي أو تلقائي)
# ===================================================================
async def get_master_cookies(user_id, link, project_id):
    # 1. التحقق من المخبأ
    cached, cached_project = get_cached_cookies(user_id)
    if cached and cached_project == project_id and test_cookies(cached, project_id):
        return cached, False, ["♻️ استخدام الكوكيز المخبأة"]

    # 2. محاولة الاستخراج التلقائي
    cookie_str, expired, steps = await extract_cookies_auto(link, project_id)
    if cookie_str and not expired and test_cookies(cookie_str, project_id):
        save_cached_cookies(user_id, cookie_str, project_id)
        return cookie_str, False, steps

    # 3. إذا فشل، نطلب من المستخدم إدخال الكوكيز يدوياً
    steps.append("⚠️ فشل الاستخراج التلقائي، استخدم /set_cookie لإدخال الكوكيز يدوياً")
    return None, True, steps

# ===================================================================
# 6. أمر /set_cookie (إدخال الكوكيز يدوياً)
# ===================================================================
async def set_cookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        # نأخذ النص كاملاً بعد الأمر
        cookie_string = " ".join(context.args)
        if len(cookie_string) < 50:
            await update.message.reply_text("❌ الكوكيز قصيرة جداً، تأكد من نسخها كاملة.")
            return
        # نحفظها في الجلسة مؤقتاً
        context.user_data["manual_cookie"] = cookie_string
        await update.message.reply_text(
            "✅ **تم حفظ الكوكيز يدوياً!**\n"
            "الآن أرسل `/set_project <project_id>` ثم `/deploy` لبدء النشر."
        )
    except:
        await update.message.reply_text("❌ /set_cookie <نص_الكوكيز>")

async def set_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        project_id = context.args[0]
        context.user_data["project_id"] = project_id
        await update.message.reply_text(f"✅ تم حفظ project_id: `{project_id}`")
    except:
        await update.message.reply_text("❌ /set_project <project_id>")

async def deploy_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cookie_str = context.user_data.get("manual_cookie")
    project_id = context.user_data.get("project_id")

    if not cookie_str or not project_id:
        await update.message.reply_text(
            "❌ يرجى تعيين الكوكيز و project_id أولاً:\n"
            "/set_cookie <نص_الكوكيز>\n"
            "/set_project <project_id>"
        )
        return

    if not test_cookies(cookie_str, project_id):
        await update.message.reply_text("❌ الكوكيز غير صالحة أو منتهية. جرب /set_cookie مرة أخرى.")
        return

    # حفظ الكوكيز في المخبأ
    save_cached_cookies(user_id, cookie_str, project_id)

    regions = fetch_regions(cookie_str, project_id)
    save_scan_cache(user_id, project_id, regions)
    context.user_data["regions"] = regions
    context.user_data["cookie_str"] = cookie_str
    context.user_data["current_page"] = 0

    keyboard = build_region_keyboard(regions, 0)
    await update.message.reply_text(
        "🌍 **اختر منطقة النشر:**",
        reply_markup=keyboard
    )
    return WAITING_REGION

# ===================================================================
# 7. فحص المناطق والنشر
# ===================================================================
def fetch_regions(cookie_str, project_id):
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {"Cookie": cookie_str, "X-Goog-User-Project": project_id}
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            allowed = [loc["locationId"] for loc in data.get("locations", []) if loc.get("state") == "ENABLED"]
            if allowed:
                return allowed
    except:
        pass
    return ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]

def deploy_service(cookie_str, project_id, region):
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
    headers = {"Cookie": cookie_str, "X-Goog-User-Project": project_id, "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code not in (200, 201):
        raise Exception(f"فشل النشر (كود {resp.status_code})")
    service_url = resp.json().get("status", {}).get("url")
    if not service_url:
        service_url = f"https://{service_name}-{region}.run.app"
    return service_url, build_vless(service_url)

# ===================================================================
# 8. الأزرار
# ===================================================================
PER_PAGE = 4

def build_region_keyboard(regions, page=0, preferred=None):
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
        InlineKeyboardButton("⭐ تعيين مفضلة", callback_data="set_pref"),
        InlineKeyboardButton("📊 إحصائيات", callback_data="stats_regions"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)

def confirm_keyboard(region):
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_regions")]
    ])

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تشغيل خدمة سريعة", callback_data="quick_deploy")],
        [InlineKeyboardButton("📊 حالة الاشتراك", callback_data="subscription_status")],
        [InlineKeyboardButton("📜 سجل عملياتي", callback_data="my_history")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")]
    ])

# ===================================================================
# 9. معالجات البوت
# ===================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    update_user(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        f"مرحباً بك في بوت تشغيل الخدمات السحابية! 😊\n\n"
        f"نوع اشتراكك الحالي: **عادي (استخدام شخصي)**\n\n"
        "استخدم الأزرار أدناه.\n"
        "إذا فشل الاستخراج التلقائي، استخدم:\n"
        "/set_cookie <نص_الكوكيز>\n"
        "/set_project <project_id>\n"
        "/deploy",
        reply_markup=main_menu_keyboard()
    )

async def button_main_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "quick_deploy":
        await query.edit_message_text("🔗 أرسل رابط Google Cloud Console الخاص بك:")
        return WAITING_LINK
    elif data == "subscription_status":
        user = get_user(user_id)
        deploy_count = user["deploy_count"] if user else 0
        await query.edit_message_text(f"📊 حالة اشتراكك:\n• النوع: عادي\n• عدد النشر: {deploy_count}", reply_markup=main_menu_keyboard())
        return
    elif data == "my_history":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT region_used, service_url, deployed_at, success FROM deploy_history WHERE user_id=? ORDER BY deployed_at DESC LIMIT 5", (user_id,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("📭 لا توجد عمليات نشر سابقة.", reply_markup=main_menu_keyboard())
            return
        msg = "📜 آخر 5 عمليات نشر:\n"
        for i, row in enumerate(rows, 1):
            icon = "✅" if row[3] == 1 else "❌"
            msg += f"{i}. {icon} {row[0]}\n   📅 {row[2][:16]}\n"
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard())
        return
    elif data == "help_menu":
        await query.edit_message_text(
            "❓ المساعدة:\n"
            "• أرسل الرابط (استخراج تلقائي).\n"
            "• إذا فشل، استخدم /set_cookie و /set_project و /deploy يدوياً.",
            reply_markup=main_menu_keyboard()
        )
        return
    return ConversationHandler.END

async def receive_link(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK
    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id.")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("⏳ جاري فتح الرابط واستخراج الكوكيز (قد يستغرق 30-60 ثانية)...")

    cookie_str, expired, steps = await get_master_cookies(user_id, text, project_id)

    for step in steps:
        await update.message.reply_text(f"📌 {step}")
        await asyncio.sleep(0.3)

    if expired or not cookie_str:
        await update.message.reply_text(
            "❌ فشل استخراج الكوكيز!\n"
            "استخدم الأمر اليدوي:\n"
            "/set_cookie <نص_الكوكيز>\n"
            "/set_project <project_id>\n"
            "/deploy"
        )
        return ConversationHandler.END

    context.user_data["cookie_str"] = cookie_str

    regions = fetch_regions(cookie_str, project_id)
    save_scan_cache(user_id, project_id, regions)
    context.user_data["regions"] = regions
    context.user_data["current_page"] = 0

    region_list = "\n".join([f"  - {r}" for r in regions])
    await update.message.reply_text(
        f"✅ تم استخراج الكوكيز!\n"
        f"🆔 Project ID: `{project_id}`\n"
        f"📡 المناطق المكتشفة ({len(regions)}):\n{region_list}\n\n"
        "👇 اختر المنطقة:",
        reply_markup=build_region_keyboard(regions, 0)
    )
    return WAITING_REGION

async def region_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"📍 استلام callback: {data}")

    if data == "noop":
        return
    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء", reply_markup=main_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        keyboard = build_region_keyboard(regions, page)
        await query.edit_message_text("🌍 اختر منطقة النشر:", reply_markup=keyboard)
        return WAITING_REGION
    if data == "rescan":
        project_id = context.user_data.get("project_id")
        cookie_str = context.user_data.get("cookie_str")
        await query.edit_message_text("🔄 جاري إعادة فحص المناطق...")
        try:
            regions = fetch_regions(cookie_str, project_id)
            save_scan_cache(user_id, project_id, regions)
            context.user_data["regions"] = regions
            context.user_data["current_page"] = 0
            keyboard = build_region_keyboard(regions, 0)
            await query.edit_message_text(f"📡 تم إعادة الفحص: {len(regions)} منطقة", reply_markup=keyboard)
            return WAITING_REGION
        except Exception as e:
            await query.edit_message_text(f"❌ فشل إعادة الفحص: {str(e)[:150]}")
            return WAITING_REGION
    if data == "stats_regions":
        await query.edit_message_text("📊 لا توجد إحصائيات كافية بعد.")
        return WAITING_REGION
    if data == "set_pref":
        await query.edit_message_text("⭐ اختر منطقة أولاً ثم اضغط 'تعيين مفضلة'.")
        return WAITING_REGION
    if data.startswith("page_"):
        page = int(data.replace("page_", ""))
        regions = context.user_data.get("regions", [])
        context.user_data["current_page"] = page
        keyboard = build_region_keyboard(regions, page)
        await query.edit_message_text(f"📡 صفحة {page+1}:", reply_markup=keyboard)
        return WAITING_REGION
    if data.startswith("select_"):
        region = data.replace("select_", "")
        context.user_data["pending_region"] = region
        keyboard = confirm_keyboard(region)
        await query.edit_message_text(
            f"⚠️ تأكيد النشر على {KNOWN_REGIONS.get(region, region)}",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY
    await query.edit_message_text(f"📩 ضغطة غير متوقعة: `{data}`")
    return WAITING_REGION

async def confirm_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"✅ استلام confirm: {data}")

    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        keyboard = build_region_keyboard(regions, page)
        await query.edit_message_text("🌍 اختر منطقة النشر:", reply_markup=keyboard)
        return WAITING_REGION

    if data.startswith("confirm_"):
        region = data.replace("confirm_", "")
        cookie_str = context.user_data.get("cookie_str")
        project_id = context.user_data.get("project_id")
        lab_url = context.user_data.get("lab_url")

        if not cookie_str or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة، أعد إرسال الرابط.")
            return ConversationHandler.END

        # اختبار صلاحية الكوكيز قبل النشر
        if not test_cookies(cookie_str, project_id):
            await query.message.reply_text("⚠️ انتهت صلاحية الكوكيز، حاول استخراج جديدة.")
            return ConversationHandler.END

        await query.edit_message_text(f"🚀 جاري النشر على {region}...")

        try:
            service_url, vless = deploy_service(cookie_str, project_id, region)
            increment_deploy_count(user_id)
            add_history(user_id, lab_url, service_url, vless, region, success=1)

            result = (
                f"✅ تم النشر بنجاح!\n"
                f"🌍 المنطقة: {region}\n"
                f"🌐 رابط Cloud Run:\n{service_url}\n\n"
                f"🔗 رابط VLESS:\n{vless}"
            )
            await query.message.reply_text(result)

        except Exception as e:
            error_msg = str(e)[:300]
            add_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(f"❌ فشل النشر: {error_msg}")

        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text(f"📩 ضغطة غير متوقعة في التأكيد: `{data}`")
    return CONFIRM_DEPLOY

async def cancel(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ===================================================================
# 10. التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_main_handler, pattern="^(quick_deploy|subscription_status|my_history|help_menu)$")],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(select_|page_|rescan|set_pref|stats_regions|cancel|noop|back_to_regions|.*)$")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(confirm_callback, pattern="^(confirm_|back_to_regions|.*)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_cookie", set_cookie_command))
    app.add_handler(CommandHandler("set_project", set_project_command))
    app.add_handler(CommandHandler("deploy", deploy_manual))
    app.add_handler(conv)

    logger.info("🚀 Shadow Legion – Cookie Manual جاهز للعمل")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()