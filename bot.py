#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v400 – Railway Final
يعمل مع Playwright على الصورة الرسمية
"""

import os
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
# الإعدادات
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

DB_PATH = "shadow.db"
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_LINK, WAITING_REGION = range(2)

KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west1": "🇧🇪 بلجيكا",
    "asia-southeast1": "🇸🇬 سنغافورة",
}

# ===================================================================
# قاعدة البيانات
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
            expiry TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER,
            project_id TEXT,
            regions TEXT,
            PRIMARY KEY (user_id, project_id)
        );
    """)
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, password, deploy_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"email": row[0], "password": row[1], "deploy_count": row[2]} if row else None

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

def get_cached_token(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0]
    return None

def save_cached_token(user_id, token, expiry_seconds=3600):
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry) VALUES (?,?,?)",
              (user_id, token, expiry.isoformat()))
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

# ===================================================================
# دوال مساعدة
# ===================================================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(("v400" + str(time.time())).encode()).hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#ShadowRelay"

def test_token(token, project_id):
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# استخراج التوكن بـ Playwright
# ===================================================================
def extract_token_playwright(email, password, project_id):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"
        )
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page.goto("https://accounts.google.com/")
        page.fill("#identifierId", email)
        page.click("#identifierNext")
        page.wait_for_selector("input[name='Passwd']", timeout=20000)
        page.fill("input[name='Passwd']", password)
        page.click("#passwordNext")
        page.wait_for_timeout(5000)

        page.goto(f"https://console.cloud.google.com/run?project={project_id}&hl=en")
        page.wait_for_timeout(8000)

        token = page.evaluate("""() => {
            for (let k of ['access_token','id_token','gapi_token','oauth_token']) {
                let v = localStorage.getItem(k);
                if (v && v.length > 40) return v;
            }
            return null;
        }""")
        browser.close()
        if not token or len(token) < 40:
            raise Exception("لم أجد التوكن")
        return token

# ===================================================================
# فحص المناطق والنشر
# ===================================================================
def fetch_regions(project_id, token):
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            allowed = [loc["locationId"] for loc in data.get("locations", []) if loc.get("state") == "ENABLED"]
            if allowed:
                return allowed
    except:
        pass
    return ["us-central1", "us-east1", "europe-west1"]

def deploy_service(project_id, token, region):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"app-{int(time.time())}"
    payload = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}
                    ]
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
# معالجات البوت
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 **Shadow Legion v400**\n"
        "1. /set_creds <البريد> <كلمة_السر>\n"
        "2. أرسل رابط Qwiklabs\n"
        "3. اختر المنطقة"
    )

async def set_creds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم الحفظ")
    except:
        await update.message.reply_text("❌ /set_creds <بريد> <كلمة>")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("لا بيانات")
        return
    await update.message.reply_text(f"📧 {user['email']}\n📊 نشر: {user['deploy_count']}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

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
    if not user or not user["email"] or not user["password"]:
        await update.message.reply_text("❌ احفظ بياناتك أولاً")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("🔄 جاري التجهيز...")

    try:
        token = get_cached_token(user_id)
        if not token or not test_token(token, project_id):
            token = extract_token_playwright(user["email"], user["password"], project_id)
            save_cached_token(user_id, token)

        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        keyboard = []
        for r in regions:
            display = KNOWN_REGIONS.get(r, r)
            keyboard.append([InlineKeyboardButton(f"🌍 {display}", callback_data=f"region_{r}")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_selection")])

        await update.message.reply_text(
            f"📡 تم اكتشاف {len(regions)} منطقة:\nاختر:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_REGION

    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")
        return ConversationHandler.END

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_selection":
        await query.edit_message_text("❌ تم الإلغاء")
        return ConversationHandler.END

    region = data.replace("region_", "")
    user_id = query.from_user.id
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    lab_url = context.user_data.get("lab_url")

    if not token or not project_id:
        await query.edit_message_text("❌ انتهت الجلسة")
        return ConversationHandler.END

    await query.edit_message_text(f"🚀 جاري النشر على {region}...")

    try:
        service_url, vless = deploy_service(project_id, token, region)
        user = get_user(user_id)
        update_user(user_id, deploy_count=(user["deploy_count"] + 1) if user else 1)

        result = f"✅ تم النشر!\n🌐 {service_url}\n\n🔗 {vless}"
        await query.message.reply_text(result)

    except Exception as e:
        await query.message.reply_text(f"❌ فشل النشر: {str(e)[:300]}")

    context.user_data.clear()
    return ConversationHandler.END

# ===================================================================
# التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel_selection)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_creds", set_creds))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(conv)
    logger.info("✅ Shadow Legion v400 يعمل على Railway")
    app.run_polling()

if __name__ == "__main__":
    main()