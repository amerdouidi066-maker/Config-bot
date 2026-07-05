#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v999 – TOKEN HUNTER (FINAL FULL VERSION)
يبحث عن التوكن في 7 أماكن مختلفة
يسجل الدخول تلقائياً
يسأل عن المنطقة عبر أزرار
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

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

# ========== الإعدادات ==========
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود في البيئة")

DB_PATH = "shadow_hunter_final.db"
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (Token Hunter Final) بدأ التشغيل...")

# حالات المحادثة
WAITING_LINK, WAITING_REGION = range(2)

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
# 1. قاعدة البيانات
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            password TEXT,
            deploy_count INTEGER DEFAULT 0
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
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

init_db()

# ===================================================================
# 2. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, password, deploy_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"email": row[0], "password": row[1], "deploy_count": row[2]} if row else None

def update_user(user_id, email=None, password=None, deploy_count=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        if email is not None:
            c.execute("UPDATE users SET email=? WHERE user_id=?", (email, user_id))
        if password is not None:
            c.execute("UPDATE users SET password=? WHERE user_id=?", (password, user_id))
        if deploy_count is not None:
            c.execute("UPDATE users SET deploy_count=? WHERE user_id=?", (deploy_count, user_id))
    else:
        c.execute("INSERT INTO users (user_id, email, password) VALUES (?,?,?)",
                  (user_id, email or "", password or ""))
    conn.commit()
    conn.close()

def get_cached_token(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0]
    return None

def save_cached_token(user_id, token, project_id="", expiry_seconds=3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?,?,?,?)",
              (user_id, token, expiry.isoformat(), project_id))
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
    raw = hashlib.md5(("shadow_hunter" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#HunterTunnel"

def test_token(token, project_id):
    try:
        r = requests.get(f"https://run.googleapis.com/v1/projects/{project_id}/locations",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# 4. استخراج التوكن – يبحث في 7 أماكن
# ===================================================================
async def extract_token_advanced(link: str, project_id: str, email: str, password: str) -> str:
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
            viewport={"width": 1280, "height": 720}
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
        except Exception as e:
            logger.warning(f"⚠️ فشل تسجيل الدخول: {e}")

        # 3. التوجه إلى Cloud Run Console
        console_url = f"https://console.cloud.google.com/run?project={project_id}&hl=en"
        logger.info(f"🔗 التوجه إلى Console: {console_url}")
        await page.goto(console_url, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(8000)

        # 4. انتظار تحميل الصفحة
        try:
            await page.wait_for_selector("body", timeout=30000)
            await page.wait_for_timeout(5000)
        except:
            pass

        # 5. البحث عن التوكن في 7 أماكن
        token = await page.evaluate("""
            () => {
                // المكان 1: localStorage
                const keys = ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token', 'token'];
                for (let k of keys) {
                    let v = localStorage.getItem(k);
                    if (v && v.length > 40) return v;
                }

                // المكان 2: sessionStorage
                for (let i=0; i<sessionStorage.length; i++) {
                    let k = sessionStorage.key(i);
                    if (k && (k.includes('token')||k.includes('oauth')||k.includes('access'))) {
                        let v = sessionStorage.getItem(k);
                        if (v && v.length > 40) return v;
                    }
                }

                // المكان 3: cookies
                let cookies = document.cookie.split(';');
                for (let c of cookies) {
                    let parts = c.trim().split('=');
                    if (parts[0] && (parts[0].includes('token')||parts[0].includes('oauth'))) {
                        if (parts[1] && parts[1].length > 40) return parts[1];
                    }
                }

                // المكان 4: gapi object
                if (window.gapi && window.gapi.auth) {
                    try {
                        let tokenObj = window.gapi.auth.getToken();
                        if (tokenObj && tokenObj.access_token && tokenObj.access_token.length > 40) {
                            return tokenObj.access_token;
                        }
                    } catch(e) {}
                }

                // المكان 5: localStorage تحت مفتاح 'gapi'
                let gapi = localStorage.getItem('gapi');
                if (gapi) {
                    try {
                        let parsed = JSON.parse(gapi);
                        if (parsed && parsed.token && parsed.token.length > 40) {
                            return parsed.token;
                        }
                        if (parsed && parsed.access_token && parsed.access_token.length > 40) {
                            return parsed.access_token;
                        }
                    } catch(e) {}
                }

                // المكان 6: sessionStorage بحث شامل ثانٍ
                for (let i=0; i<sessionStorage.length; i++) {
                    let k = sessionStorage.key(i);
                    if (k && (k.includes('token')||k.includes('oauth'))) {
                        let v = sessionStorage.getItem(k);
                        if (v && v.length > 40) return v;
                    }
                }

                // المكان 7: meta tags
                let metaToken = document.querySelector('meta[name="csrf-token"]');
                if (metaToken && metaToken.content && metaToken.content.length > 40) {
                    return metaToken.content;
                }

                return null;
            }
        """)

        # 6. إذا لم نجد، ننتظر 5 ثوانٍ ونحاول مرة أخرى
        if not token or len(token) < 40:
            logger.info("⏳ لم نجد التوكن، ننتظر 5 ثوانٍ ونحاول مجدداً...")
            await page.wait_for_timeout(5000)
            token = await page.evaluate("""
                () => {
                    for (let k of ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token']) {
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
                    return null;
                }
            """)

        await browser.close()

        if token and len(token) > 40:
            logger.info(f"✅ تم استخراج التوكن (الطول: {len(token)})")
            return token

        raise Exception("لم أجد التوكن في أي من الأماكن الـ 7")

async def get_master_token(user_id, link, project_id, email, password):
    cached = get_cached_token(user_id)
    if cached and test_token(cached, project_id):
        logger.info("♻️ استخدام التوكن المخبأ")
        return cached
    token = await extract_token_advanced(link, project_id, email, password)
    if token and test_token(token, project_id):
        save_cached_token(user_id, token, project_id)
        return token
    raise Exception("تعذر الحصول على توكن صالح")

# ===================================================================
# 5. فحص المناطق والنشر
# ===================================================================
def fetch_regions(project_id, token):
    try:
        r = requests.get(f"https://run.googleapis.com/v1/projects/{project_id}/locations",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            allowed = [loc["locationId"] for loc in data.get("locations", []) if loc.get("state") == "ENABLED"]
            if allowed:
                return allowed
    except:
        pass
    return ["us-central1"]

def deploy_service(project_id, token, region):
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
    return service_url, build_vless(service_url)

# ===================================================================
# 6. أزرار اختيار المنطقة
# ===================================================================
def build_region_keyboard(regions):
    keyboard = []
    for r in regions:
        display = KNOWN_REGIONS.get(r, r)
        keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"region_{r}")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

# ===================================================================
# 7. معالجات البوت
# ===================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user and user.get("email"):
        await update.message.reply_text(
            f"🔥 **Shadow VPN – Token Hunter**\n"
            f"📧 بريدك: {user['email']}\n"
            f"📊 عدد النشر: {user['deploy_count']}\n\n"
            "أرسل رابط Qwiklabs لبدء النشر."
        )
    else:
        await update.message.reply_text(
            "🔥 **Shadow VPN – Token Hunter**\n"
            "يرجى تعيين بريدك وكلمة المرور أولاً:\n"
            "/set_creds <البريد> <كلمة_السر>"
        )

async def set_creds(update: Update, context):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد وكلمة المرور بنجاح!")
    except:
        await update.message.reply_text("❌ الاستخدام: /set_creds <البريد> <كلمة_السر>")

async def receive_link(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد project_id في الرابط")
        return WAITING_LINK

    user = get_user(user_id)
    if not user or not user.get("email") or not user.get("password"):
        await update.message.reply_text("❌ يرجى تعيين البريد وكلمة المرور أولاً:\n/set_creds <البريد> <كلمة_السر>")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text(
        "🔄 **جاري الدخول إلى الـ Lab وبدء التجهيز...**\n"
        "✔ تم التحقق من صلاحية الرابط، سيتم ربط الحساب وبدء عملية الإنشاء..."
    )

    try:
        token = await get_master_token(user_id, text, project_id, user["email"], user["password"])
        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions

        region_list = "\n".join([f"  - {r}" for r in regions])
        await update.message.reply_text(
            f"📡 **جاري تحليل سياسات المشروع لاستخراج المناطق المسموح بها...**\n"
            f"✔ تم اكتشاف {len(regions)} منطقة مسموح بها:\n{region_list}"
        )

        keyboard = build_region_keyboard(regions)
        await update.message.reply_text(
            "👇 **اختر المنطقة التي تريد النشر عليها:**",
            reply_markup=keyboard
        )
        return WAITING_REGION

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ خطأ: {error_msg}")
        await update.message.reply_text(f"❌ فشل:\n{error_msg[:300]}")
        return ConversationHandler.END

async def region_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    region = data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    lab_url = context.user_data.get("lab_url")

    if not token or not project_id:
        await query.edit_message_text("❌ انتهت الجلسة، أعد إرسال الرابط")
        return ConversationHandler.END

    await query.edit_message_text(f"🚀 **جاري النشر على المنطقة {KNOWN_REGIONS.get(region, region)}...**")

    try:
        service_url, vless = deploy_service(project_id, token, region)
        user = get_user(user_id)
        update_user(user_id, deploy_count=(user["deploy_count"] + 1) if user else 1)
        add_history(user_id, lab_url, service_url, vless, region, success=1)

        result = (
            f"✅ **تم النشر بنجاح!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌍 **المنطقة المستخدمة:** `{KNOWN_REGIONS.get(region, region)}`\n"
            f"🌐 **رابط Cloud Run:**\n`{service_url}`\n\n"
            f"🔗 **رابط VLESS:**\n`{vless}`\n\n"
            f"📌 الرابط صالح لمدة ساعة أو حتى انتهاء المشروع."
        )
        await query.message.reply_text(result)

    except Exception as e:
        error_msg = str(e)[:300]
        logger.error(f"❌ فشل النشر: {error_msg}")
        add_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
        await query.message.reply_text(
            f"❌ **فشل النشر:**\n`{error_msg}`\n\n"
            f"💡 حاول اختيار منطقة أخرى أو أعد إرسال الرابط."
        )

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 8. تشغيل البوت
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_creds", set_creds))
    app.add_handler(conv)

    logger.info("✅ SHADOW LEGION v999 (Token Hunter Final) جاهز للعمل")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()