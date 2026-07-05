#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v400 – Railway Edition
- أنت تختار المنطقة عبر أزرار
- استخراج توكن بطبقات متعددة
- قاعدة بيانات متكاملة
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
from playwright.sync_api import sync_playwright
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
    raise ValueError("❌ متغير TOKEN غير موجود في البيئة")

USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)

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

DB_PATH = "shadow_legion_400.db"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_LINK, WAITING_REGION = range(2)

# ===================================================================
# 2. قاعدة البيانات
# ===================================================================
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            password TEXT,
            region TEXT DEFAULT 'us-central1',
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            manual_token TEXT
        );
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT,
            expiry TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER,
            project_id TEXT,
            allowed_regions TEXT,
            scanned_at TIMESTAMP,
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

init_database()

# ===================================================================
# 3. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, email, password, region, deploy_count, status, manual_token FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "email": row[1],
            "password": row[2],
            "region": row[3],
            "deploy_count": row[4],
            "status": row[5],
            "manual_token": row[6],
        }
    return None

def update_user(user_id: int, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    else:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {placeholders})", [user_id] + list(kwargs.values()))
    conn.commit()
    conn.close()

def get_cached_token(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry FROM token_cache WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        token, expiry_str = row
        expiry = datetime.fromisoformat(expiry_str)
        if expiry > datetime.now():
            return token
    return None

def save_cached_token(user_id: int, token: str, expiry_seconds: int = 3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry) VALUES (?, ?, ?)",
              (user_id, token, expiry.isoformat()))
    conn.commit()
    conn.close()

def save_scan_cache(user_id: int, project_id: str, regions: List[str]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO scan_cache (user_id, project_id, allowed_regions, scanned_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
              (user_id, project_id, json.dumps(regions)))
    conn.commit()
    conn.close()

def get_scan_cache(user_id: int, project_id: str) -> Optional[List[str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT allowed_regions FROM scan_cache WHERE user_id = ? AND project_id = ?", (user_id, project_id))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()

# ===================================================================
# 4. دوال مساعدة
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[?&]project=([^&]+)', decoded)
    return match.group(1) if match else None

def build_vless_link(service_url: str, seed: str = "shadow_v400") -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    uid_raw = hashlib.md5((seed + str(time.time())).encode()).hexdigest()
    uid = f"{uid_raw[:8]}-{uid_raw[8:12]}-{uid_raw[12:16]}-{uid_raw[16:20]}-{uid_raw[20:32]}"
    return (
        f"vless://{uid}@{host}:443?"
        f"encryption=none&security=tls&sni=youtube.com&fp=chrome&"
        f"type=ws&host={host}&path=%2F%40nkka404#UserSelected"
    )

def test_token_validity(token: str, project_id: str) -> bool:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

# ===================================================================
# 5. استخراج التوكن عبر Playwright
# ===================================================================
def extract_token_playwright(email: str, password: str, project_id: str, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
                )
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                )
                page = ctx.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                logger.info("📧 جاري تسجيل الدخول...")
                page.goto("https://accounts.google.com/")
                page.fill("#identifierId", email)
                page.click("#identifierNext")
                page.wait_for_selector("input[name='Passwd']", timeout=20000)
                page.fill("input[name='Passwd']", password)
                page.click("#passwordNext")
                page.wait_for_timeout(6000)

                logger.info("🌐 جاري الدخول إلى Cloud Run...")
                page.goto(f"https://console.cloud.google.com/run?project={project_id}&hl=en")
                page.wait_for_selector("body", timeout=45000)
                page.wait_for_timeout(8000)

                token = page.evaluate("""() => {
                    const keys = ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token'];
                    for (let k of keys) {
                        let v = localStorage.getItem(k);
                        if (v && v.length > 40) return v;
                    }
                    for (let k of sessionStorage.keys()) {
                        if (k.includes('token') || k.includes('oauth')) {
                            let v = sessionStorage.getItem(k);
                            if (v && v.length > 40) return v;
                        }
                    }
                    return null;
                }""")

                browser.close()
                if token and len(token) > 40:
                    logger.info("✅ تم استخراج التوكن")
                    return token
                raise Exception("التوكن غير موجود أو قصير")

        except Exception as e:
            logger.warning(f"محاولة {attempt+1} فشلت: {e}")
            if attempt == retries - 1:
                raise Exception(f"فشل استخراج التوكن بعد {retries} محاولات: {str(e)}")
            time.sleep(5)
    raise Exception("لم نتمكن من استخراج التوكن")

def get_master_token(user_id: int, email: str, password: str, project_id: str) -> str:
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        if test_token_validity(USER_TOKEN_OVERRIDE, project_id):
            logger.info("✅ استخدام التوكن من البيئة")
            save_cached_token(user_id, USER_TOKEN_OVERRIDE)
            return USER_TOKEN_OVERRIDE

    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        logger.info("✅ استخدام التوكن المخبأ")
        return cached

    logger.info("🔄 استخراج توكن جديد...")
    token = extract_token_playwright(email, password, project_id)
    if token and test_token_validity(token, project_id):
        save_cached_token(user_id, token)
        return token

    raise Exception("تعذر الحصول على توكن صالح")

# ===================================================================
# 6. فحص المناطق والنشر
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            locations = data.get("locations", [])
            allowed = [loc["locationId"] for loc in locations if loc.get("state") == "ENABLED" and loc.get("locationId")]
            if allowed:
                return allowed
    except Exception as e:
        logger.warning(f"فشل جلب المناطق: {e}")
    return list(KNOWN_REGIONS.keys())

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
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code not in (200, 201):
        raise Exception(f"فشل النشر ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    service_url = data.get("status", {}).get("url")
    if not service_url:
        service_url = f"https://{service_name}-{region}.run.app"
    vless = build_vless_link(service_url)
    return service_url, vless

# ===================================================================
# 7. معالجات البوت
# ===================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v400 – Railway**\n"
        "1. احفظ بياناتك: /set_creds <البريد> <كلمة_السر>\n"
        "2. أرسل رابط Qwiklabs.\n"
        "3. اختر المنطقة من الأزرار.\n"
        "أمرك سيدي 👁"
    )

async def set_creds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد وكلمة المرور")
    except IndexError:
        await update.message.reply_text("❌ /set_creds <البريد> <كلمة_السر>")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات")
        return
    token_status = "✅" if get_cached_token(user_id) else "❌"
    await update.message.reply_text(
        f"📋 حالتك\n📧 {user.get('email', 'غير مضبوط')}\n"
        f"📊 عدد النشر: {user.get('deploy_count', 0)}\n"
        f"🔑 التوكن: {token_status}"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 8. محادثة النشر
# ===================================================================
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ أرسل رابطاً صالحاً")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ الرابط لا يحتوي على project_id")
        return WAITING_LINK

    user = get_user(user_id)
    if not user or not user.get("email") or not user.get("password"):
        await update.message.reply_text("❌ احفظ بياناتك أولاً: /set_creds")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("🔄 **جاري الدخول إلى الـ Lab والتجهيز...**")

    try:
        token = get_master_token(user_id, user["email"], user["password"], project_id)
        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions

        keyboard = []
        for r in regions:
            display = KNOWN_REGIONS.get(r, r)
            keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"region_{r}")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_selection")])

        await update.message.reply_text(
            f"📡 **تم اكتشاف {len(regions)} منطقة مسموحة.**\n👇 اختر المنطقة:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_REGION

    except Exception as e:
        await update.message.reply_text(f"❌ فشل الفحص: {str(e)[:200]}")
        return ConversationHandler.END

async def region_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_selection":
        await query.edit_message_text("❌ تم الإلغاء")
        return ConversationHandler.END

    region = data.replace("region_", "")
    user_id = query.from_user.id

    lab_url = context.user_data.get("lab_url")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")

    if not token or not project_id:
        await query.edit_message_text("❌ انتهت الجلسة، أعد الإرسال")
        return ConversationHandler.END

    await query.edit_message_text(f"🚀 **جاري النشر على {region}...**")

    try:
        service_url, vless = deploy_service(project_id, token, region)
        user = get_user(user_id)
        deploy_count = user.get("deploy_count", 0) + 1 if user else 1
        update_user(user_id, deploy_count=deploy_count, status="completed")
        add_deploy_history(user_id, lab_url, service_url, vless, region, success=1)

        result = (
            f"✅ **تم النشر!**\n"
            f"🌍 المنطقة: {region}\n"
            f"🌐 الرابط: {service_url}\n\n"
            f"🔗 VLESS:\n{vless}"
        )
        await query.message.reply_text(result)

    except Exception as e:
        error_msg = str(e)[:300]
        await query.message.reply_text(f"❌ فشل النشر: {error_msg}")
        add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
        update_user(user_id, status="error")

    context.user_data.clear()
    return ConversationHandler.END

# ===================================================================
# 9. تشغيل البوت
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_selection_callback, pattern="^(region_|cancel_selection)")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("set_creds", set_creds_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(conv)
    logger.info("✅ SHADOW LEGION v400 يعمل على Railway")
    app.run_polling()

if __name__ == "__main__":
    main()