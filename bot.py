#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║     SHADOW LEGION v950 – ADVANCED BUTTONS EDITION             ║
║   أزرار متطورة: تصفح، تأكيد، إعادة فحص، حالة                ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ===================================================================
# 1. الاستيرادات
# ===================================================================
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
# 2. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)
DB_PATH = "shadow_advanced.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v950 (أزرار متطورة) بدأ التشغيل...")

# حالات المحادثة
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
# 3. قاعدة البيانات (نفسها لكن مختصرة للمساحة)
# ===================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT, password TEXT,
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle'
        );
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT, expiry TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER, project_id TEXT, regions TEXT,
            PRIMARY KEY (user_id, project_id)
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, lab_url TEXT, service_url TEXT,
            vless_link TEXT, region_used TEXT,
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
    c.execute("SELECT email, password, deploy_count, status FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"email": row[0], "password": row[1], "deploy_count": row[2], "status": row[3]} if row else None

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

def add_history(user_id, lab_url, service_url, vless, region, success=1, error_msg=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
    conn.commit()
    conn.close()

# ===================================================================
# 4. دوال مساعدة
# ===================================================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5(("v950" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#ShadowAdvanced"

def test_token(token, project_id):
    try:
        r = requests.get(f"https://run.googleapis.com/v1/projects/{project_id}/locations",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# 5. استخراج التوكن (مبسط لكن يعمل)
# ===================================================================
def extract_token_playwright(email, password, project_id, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
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
                if token and len(token) > 40:
                    return token
                raise Exception("لم أجد التوكن")
        except Exception as e:
            logger.warning(f"محاولة {attempt} فشلت: {e}")
            time.sleep(3)
    raise Exception("فشل استخراج التوكن")

def get_master_token(user_id, email, password, project_id):
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        if test_token(USER_TOKEN_OVERRIDE, project_id):
            save_cached_token(user_id, USER_TOKEN_OVERRIDE)
            return USER_TOKEN_OVERRIDE
    cached = get_cached_token(user_id)
    if cached and test_token(cached, project_id):
        return cached
    token = extract_token_playwright(email, password, project_id)
    if token and test_token(token, project_id):
        save_cached_token(user_id, token)
        return token
    raise Exception("تعذر الحصول على توكن صالح")

# ===================================================================
# 6. فحص المناطق والنشر
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
    return ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]

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
# 7. دوال الأزرار المتطورة (Pagination + Confirm)
# ===================================================================
PER_PAGE = 4  # عدد المناطق في كل صفحة

def build_region_keyboard(regions: List[str], page: int = 0) -> InlineKeyboardMarkup:
    """بناء لوحة أزرار متطورة مع ترقيم وحالة"""
    total = len(regions)
    if total == 0:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ لا توجد مناطق", callback_data="noop")]
        ])

    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    start = page * PER_PAGE
    end = min(start + PER_PAGE, total)

    keyboard = []
    # عرض حالة الصفحة
    keyboard.append([InlineKeyboardButton(
        f"📋 الصفحة {page+1} من {total_pages} | إجمالي {total} منطقة",
        callback_data="noop"
    )])

    # أزرار المناطق
    for i in range(start, end):
        region_code = regions[i]
        display_name = KNOWN_REGIONS.get(region_code, region_code)
        keyboard.append([
            InlineKeyboardButton(
                f"🌍 {display_name}  ➡️",
                callback_data=f"region_select_{region_code}"
            )
        ])

    # أزرار التصفح (التالي / السابق)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"region_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"region_page_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # أزرار التحكم السفلية
    control_row = []
    control_row.append(InlineKeyboardButton("🔄 إعادة فحص", callback_data="rescan_regions"))
    control_row.append(InlineKeyboardButton("❌ إلغاء", callback_data="cancel_selection"))
    keyboard.append(control_row)

    return InlineKeyboardMarkup(keyboard)

def build_confirm_keyboard(region: str) -> InlineKeyboardMarkup:
    """لوحة تأكيد قبل النشر"""
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_deploy_{region}")],
        [InlineKeyboardButton("🔙 العودة للقائمة", callback_data="back_to_regions")]
    ])

# ===================================================================
# 8. معالجات البوت (الأوامر والمحادثات)
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v950 – أزرار متطورة**\n"
        "1. /set_creds <البريد> <كلمة_السر>\n"
        "2. أرسل رابط Qwiklabs.\n"
        "3. اختر المنطقة من الأزرار المتطورة.\n"
        "📌 أوامر: /status, /cancel"
    )

async def set_creds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد وكلمة المرور")
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

# ===================================================================
# 9. استقبال الرابط وعرض الأزرار المتطورة
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
    if not user or not user["email"] or not user["password"]:
        await update.message.reply_text("❌ احفظ بياناتك أولاً: /set_creds")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text("🔄 جاري التجهيز... قد يستغرق 30-60 ثانية")

    try:
        token = get_master_token(user_id, user["email"], user["password"], project_id)
        context.user_data["token"] = token

        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions
        context.user_data["current_page"] = 0

        keyboard = build_region_keyboard(regions, 0)
        await update.message.reply_text(
            f"📡 **تم اكتشاف {len(regions)} منطقة.**\n👇 اختر المنطقة المطلوبة:",
            reply_markup=keyboard
        )
        return WAITING_REGION

    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")
        return ConversationHandler.END

# ===================================================================
# 10. معالج الأزرار (التصفح، الاختيار، التأكيد، إعادة الفحص)
# ===================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # حالة عدم فعل شيء (عناصر وهمية)
    if data == "noop":
        return

    # ----- 1. إلغاء -----
    if data == "cancel_selection":
        await query.edit_message_text("❌ تم الإلغاء")
        context.user_data.clear()
        return ConversationHandler.END

    # ----- 2. إعادة فحص -----
    if data == "rescan_regions":
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة، أعد الإرسال")
            return ConversationHandler.END
        await query.edit_message_text("🔄 جاري إعادة فحص المناطق...")
        try:
            regions = fetch_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)
            context.user_data["regions"] = regions
            context.user_data["current_page"] = 0
            keyboard = build_region_keyboard(regions, 0)
            await query.edit_message_text(
                f"📡 **تم إعادة الفحص واكتشاف {len(regions)} منطقة.**",
                reply_markup=keyboard
            )
            return WAITING_REGION
        except Exception as e:
            await query.edit_message_text(f"❌ فشل إعادة الفحص: {str(e)[:150]}")
            return WAITING_REGION

    # ----- 3. تغيير الصفحة -----
    if data.startswith("region_page_"):
        page = int(data.replace("region_page_", ""))
        regions = context.user_data.get("regions", [])
        if not regions:
            await query.edit_message_text("❌ لا توجد مناطق")
            return ConversationHandler.END
        context.user_data["current_page"] = page
        keyboard = build_region_keyboard(regions, page)
        await query.edit_message_text(
            f"📡 **اختر المنطقة:** (صفحة {page+1})",
            reply_markup=keyboard
        )
        return WAITING_REGION

    # ----- 4. اختيار منطقة (يذهب للتأكيد) -----
    if data.startswith("region_select_"):
        region = data.replace("region_select_", "")
        context.user_data["pending_region"] = region
        keyboard = build_confirm_keyboard(region)
        await query.edit_message_text(
            f"⚠️ **تأكيد النشر**\n"
            f"المنطقة المختارة: {KNOWN_REGIONS.get(region, region)}\n"
            f"هل أنت متأكد من النشر عليها؟",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY

    # ----- 5. العودة للقائمة (من التأكيد) -----
    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        keyboard = build_region_keyboard(regions, page)
        await query.edit_message_text(
            f"📡 **اختر المنطقة:**",
            reply_markup=keyboard
        )
        return WAITING_REGION

    # ----- 6. تأكيد النشر -----
    if data.startswith("confirm_deploy_"):
        region = data.replace("confirm_deploy_", "")
        project_id = context.user_data.get("project_id")
        token = context.user_data.get("token")
        lab_url = context.user_data.get("lab_url")

        if not token or not project_id:
            await query.edit_message_text("❌ انتهت الجلسة، أعد الإرسال")
            return ConversationHandler.END

        await query.edit_message_text(f"🚀 **جاري النشر على {KNOWN_REGIONS.get(region, region)}...**")

        try:
            service_url, vless = deploy_service(project_id, token, region)
            user = get_user(user_id)
            update_user(user_id, deploy_count=(user["deploy_count"] + 1) if user else 1)
            add_history(user_id, lab_url, service_url, vless, region, success=1)

            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"🌍 المنطقة: {KNOWN_REGIONS.get(region, region)}\n"
                f"🌐 الرابط: {service_url}\n\n"
                f"🔗 VLESS:\n{vless}"
            )
            await query.message.reply_text(result)

        except Exception as e:
            error_msg = str(e)[:300]
            add_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(f"❌ فشل النشر: {error_msg}")

        context.user_data.clear()
        return ConversationHandler.END

    return WAITING_REGION

# ===================================================================
# 11. التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(button_handler, pattern="^(region_select_|region_page_|rescan_regions|cancel_selection|noop)")],
            CONFIRM_DEPLOY: [CallbackQueryHandler(button_handler, pattern="^(confirm_deploy_|back_to_regions)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_creds", set_creds))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v950 (أزرار متطورة) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()