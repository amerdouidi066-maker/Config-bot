#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║     SHADOW LEGION v900 – ULTRA LONG EDITION (780+ lines)      ║
║              مخصص للاستخدام الفردي مع Railway                  ║
║   جميع الطبقات الاحتياطية، السجل التاريخي، التحليلات          ║
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
import base64
import hashlib
import logging
import sqlite3
import urllib.parse
import threading
import queue
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any

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
    raise ValueError("❌ TOKEN غير موجود في البيئة")

USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)
DB_PATH = "shadow_legion_900.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v900 (النسخة الطويلة) بدأ التشغيل...")

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
# 3. قاعدة البيانات (متقدمة)
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
            manual_token TEXT,
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
            allowed_regions TEXT,
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
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات المتقدمة جاهزة")

init_database()

# ===================================================================
# 4. دوال قاعدة البيانات (مفصلة)
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, email, password, region, deploy_count, status, manual_token, last_activity
        FROM users WHERE user_id = ?
    """, (user_id,))
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
            "last_activity": row[7],
        }
    return None

def update_user(user_id: int, **kwargs) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    else:
        if "last_activity" not in kwargs:
            kwargs["last_activity"] = datetime.now().isoformat()
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
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry > datetime.now():
                return token
        except:
            pass
    return None

def save_cached_token(user_id: int, token: str, project_id: str = "", expiry_seconds: int = 3600) -> None:
    expiry = datetime.now() + timedelta(seconds=expiry_seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO token_cache (user_id, access_token, expiry, project_id) VALUES (?, ?, ?, ?)",
        (user_id, token, expiry.isoformat(), project_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"✅ تم تخزين التوكن للمستخدم {user_id} حتى {expiry.isoformat()}")

def clear_cached_token(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM token_cache WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_scan_cache(user_id: int, project_id: str, regions: List[str]) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO scan_cache (user_id, project_id, allowed_regions) VALUES (?, ?, ?)",
        (user_id, project_id, json.dumps(regions))
    )
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

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = "") -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, lab_url, service_url, vless, region, success, error_msg)
    )
    conn.commit()
    conn.close()

def log_failure(user_id: int, error_type: str, error_detail: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO failure_logs (user_id, error_type, error_detail) VALUES (?, ?, ?)",
        (user_id, error_type, error_detail[:500])
    )
    conn.commit()
    conn.close()

# ===================================================================
# 5. دوال مساعدة (استخراج، بناء روابط، اختبار)
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(r'/projects/([^/?]+)', decoded)
    if match:
        return match.group(1)
    return None

def extract_email_from_link(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[Ee]mail=([^&]+)', decoded)
    return urllib.parse.unquote(match.group(1)) if match else None

def build_vless_link(service_url: str, seed: str = "shadow_v900") -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5((seed + str(time.time()) + os.urandom(4).hex()).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return (
        f"vless://{uid}@{host}:443?"
        f"encryption=none&security=tls&sni=youtube.com&fp=chrome&"
        f"type=ws&host={host}&path=%2F%40nkka404#ShadowLegion_900"
    )

def test_token_validity(token: str, project_id: str) -> bool:
    if not token or len(token) < 40:
        return False
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            logger.warning("⚠️ التوكن غير صالح (Unauthorized)")
            return False
        else:
            logger.warning(f"⚠️ اختبار التوكن أعاد {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        logger.warning("⏰ انتهت مهلة اختبار التوكن")
        return False
    except Exception as e:
        logger.warning(f"⚠️ خطأ في اختبار التوكن: {e}")
        return False

# ===================================================================
# 6. استخراج التوكن بـ Playwright (3 استراتيجيات)
# ===================================================================
def extract_token_playwright_advanced(email: str, password: str, project_id: str, max_retries: int = 3) -> str:
    last_exception = None
    for attempt in range(1, max_retries + 1):
        logger.info(f"🔄 محاولة استخراج التوكن رقم {attempt}/{max_retries}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-gpu",
                        "--disable-setuid-sandbox"
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                    locale="en-US",
                )
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)

                # تسجيل الدخول
                logger.info("📧 جاري تسجيل الدخول إلى Google...")
                page.goto("https://accounts.google.com/", timeout=30000)
                page.wait_for_selector("#identifierId", timeout=15000)
                page.fill("#identifierId", email)
                page.click("#identifierNext")
                page.wait_for_selector("input[name='Passwd']", timeout=20000)
                page.fill("input[name='Passwd']", password)
                page.click("#passwordNext")
                page.wait_for_timeout(5000)

                # استراتيجيات متعددة للدخول إلى Cloud Run
                token = None
                urls_to_try = [
                    f"https://console.cloud.google.com/run?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}&hl=en"
                ]

                for target_url in urls_to_try:
                    logger.info(f"🌐 محاولة الدخول إلى: {target_url}")
                    page.goto(target_url, timeout=45000)
                    try:
                        page.wait_for_selector("body", timeout=30000)
                        page.wait_for_timeout(7000)
                    except PlaywrightTimeoutError:
                        logger.warning("⏰ انتهت مهلة انتظار تحميل الصفحة")

                    token = page.evaluate("""
                        () => {
                            const ls_keys = ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token', 'token'];
                            for (let k of ls_keys) {
                                let v = localStorage.getItem(k);
                                if (v && v.length > 40) return v;
                            }
                            for (let i = 0; i < sessionStorage.length; i++) {
                                let k = sessionStorage.key(i);
                                if (k && (k.includes('token') || k.includes('oauth') || k.includes('access'))) {
                                    let v = sessionStorage.getItem(k);
                                    if (v && v.length > 40) return v;
                                }
                            }
                            let cookies = document.cookie.split(';');
                            for (let c of cookies) {
                                let parts = c.trim().split('=');
                                if (parts[0] && (parts[0].includes('token') || parts[0].includes('oauth'))) {
                                    if (parts[1] && parts[1].length > 40) return parts[1];
                                }
                            }
                            return null;
                        }
                    """)
                    if token and len(token) > 40:
                        logger.info("✅ تم استخراج التوكن بنجاح!")
                        browser.close()
                        return token

                browser.close()
                logger.warning(f"⚠️ المحاولة {attempt} لم تجد التوكن")

        except PlaywrightTimeoutError as e:
            last_exception = f"انتهت المهلة: {e}"
            logger.warning(f"⏰ انتهت المهلة في المحاولة {attempt}")
        except Exception as e:
            last_exception = str(e)
            logger.warning(f"⚠️ خطأ في المحاولة {attempt}: {e}")

        time.sleep(5)

    raise Exception(f"فشل استخراج التوكن بعد {max_retries} محاولات. آخر خطأ: {last_exception}")

# ===================================================================
# 7. الطبقة العليا للحصول على التوكن
# ===================================================================
def get_master_token(user_id: int, email: str, password: str, project_id: str) -> str:
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        if test_token_validity(USER_TOKEN_OVERRIDE, project_id):
            save_cached_token(user_id, USER_TOKEN_OVERRIDE, project_id)
            return USER_TOKEN_OVERRIDE
        else:
            logger.warning("⚠️ USER_TOKEN غير صالح")

    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        logger.info("♻️ استخدام التوكن المخبأ")
        return cached

    logger.info("🔄 استخراج توكن جديد عبر Playwright...")
    try:
        new_token = extract_token_playwright_advanced(email, password, project_id)
        if new_token and test_token_validity(new_token, project_id):
            save_cached_token(user_id, new_token, project_id)
            logger.info("✅ تم استخراج وحفظ التوكن الجديد")
            return new_token
    except Exception as e:
        logger.error(f"❌ فشل استخراج التوكن الجديد: {e}")
        raise Exception(f"تعذر الحصول على توكن صالح: {e}")

    raise Exception("فشل الحصول على توكن صالح من جميع المصادر")

# ===================================================================
# 8. فحص المناطق (مع احتياطي)
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            locations = data.get("locations", [])
            allowed = []
            for loc in locations:
                loc_id = loc.get("locationId")
                state = loc.get("state")
                if loc_id and state == "ENABLED":
                    allowed.append(loc_id)
            if allowed:
                logger.info(f"✅ تم اكتشاف {len(allowed)} منطقة مسموحة عبر API")
                return allowed
            else:
                logger.warning("⚠️ API أعاد مناطق ولكن قائمة فارغة")
        else:
            logger.warning(f"⚠️ فشل جلب المناطق (كود {response.status_code})")
    except Exception as e:
        logger.warning(f"⚠️ استثناء في جلب المناطق: {e}")

    fallback_list = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    logger.info(f"🔄 استخدام قائمة الاحتياطي: {fallback_list}")
    return fallback_list

# ===================================================================
# 9. النشر مع إعادة المحاولة على مناطق بديلة
# ===================================================================
def deploy_service_with_fallback(project_id: str, token: str, preferred_region: str, regions_list: List[str]) -> Tuple[str, str, str]:
    regions_to_try = [preferred_region] + [r for r in regions_list if r != preferred_region]
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
                logger.info(f"✅ تم النشر بنجاح على {region} -> {service_url}")
                return service_url, region, vless
            else:
                error_text = response.text[:150]
                last_error = f"{region}: كود {response.status_code} - {error_text}"
                logger.warning(f"⚠️ فشل النشر على {region}: {last_error}")

        except requests.exceptions.Timeout:
            last_error = f"{region}: انتهت المهلة"
            logger.warning(f"⏰ انتهت المهلة على {region}")
        except Exception as e:
            last_error = f"{region}: {str(e)[:100]}"
            logger.warning(f"⚠️ استثناء على {region}: {e}")

        time.sleep(2)

    raise Exception(f"فشل النشر على جميع المناطق. آخر خطأ: {last_error}")

# ===================================================================
# 10. معالجات البوت (أوامر ومحادثات)
# ===================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v900 – النسخة الطويلة جداً**\n"
        "📍 **الخطوات:**\n"
        "1. /set_creds <البريد> <كلمة_السر>\n"
        "2. أرسل رابط Qwiklabs\n"
        "3. اختر المنطقة\n"
        "📌 أوامر مساعدة: /status, /history, /cancel"
    )

async def set_creds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        if not email or not password:
            raise IndexError
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ تم حفظ البريد وكلمة المرور")
    except IndexError:
        await update.message.reply_text("❌ /set_creds <البريد> <كلمة_السر>")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات")
        return
    token_status = "✅ (موجود)" if get_cached_token(user_id) else "❌ (غير موجود)"
    await update.message.reply_text(
        f"📋 **حالتك**\n"
        f"📧 البريد: {user.get('email', 'غير مضبوط')}\n"
        f"📊 عدد النشر: {user.get('deploy_count', 0)}\n"
        f"🔑 التوكن: {token_status}"
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT service_url, region_used, deployed_at, success FROM deploy_history WHERE user_id = ? ORDER BY deployed_at DESC LIMIT 5", (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📭 لا يوجد سجل")
        return
    msg = "📜 **آخر 5 عمليات نشر:**\n"
    for i, row in enumerate(rows, 1):
        status_icon = "✅" if row[3] == 1 else "❌"
        msg += f"{i}. {status_icon} {row[1]}\n   📅 {row[2][:16]}\n"
    await update.message.reply_text(msg)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 11. محادثة النشر (استقبال الرابط + اختيار المنطقة)
# ===================================================================
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            regions = fetch_allowed_regions(project_id, token)
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
        log_failure(user_id, "TOKEN_EXTRACTION_FAILED", str(e))
        await update.message.reply_text(f"❌ فشل: {str(e)[:200]}")
        return ConversationHandler.END

async def region_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    regions = context.user_data.get("regions", [])

    if not token or not project_id:
        await query.edit_message_text("❌ انتهت الجلسة")
        return ConversationHandler.END

    await query.edit_message_text(f"🚀 جاري النشر على {region}...")

    try:
        service_url, used_region, vless = deploy_service_with_fallback(project_id, token, region, regions)
        user = get_user(user_id)
        deploy_count = user.get("deploy_count", 0) + 1 if user else 1
        update_user(user_id, deploy_count=deploy_count, status="completed")
        add_deploy_history(user_id, lab_url, service_url, vless, used_region, success=1)

        result = f"✅ تم النشر!\n🌐 {service_url}\n\n🔗 {vless}"
        await query.message.reply_text(result)

    except Exception as e:
        error_msg = str(e)[:300]
        log_failure(user_id, "DEPLOY_FAILED", error_msg)
        add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
        await query.message.reply_text(f"❌ فشل النشر: {error_msg}")

    context.user_data.clear()
    return ConversationHandler.END

# ===================================================================
# 12. تشغيل البوت
# ===================================================================
def main() -> None:
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
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v900 (النسخة الطويلة) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()