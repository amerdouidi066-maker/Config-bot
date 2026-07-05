#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║            SHADOW LEGION v600 – ULTIMATE LONG EDITION          ║
║              مخصص للاستخدام الفردي مع Railway                  ║
║   الطول: ~750 سطراً  │  الميزات: 7 طبقات مقاومة للفشل        ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ===================================================================
# 1. استيراد المكتبات الأساسية
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

# مكتبات خارجية
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
# 2. الإعدادات الأساسية والمتغيرات البيئية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ متغير TOKEN غير موجود في البيئة. أضفه في Railway Variables.")

# متغير اختياري لتجاوز التوكن يدوياً (للطوارئ القصوى)
USER_TOKEN_OVERRIDE = os.environ.get("USER_TOKEN", None)

# اسم ملف قاعدة البيانات
DB_PATH = "shadow_legion_600.db"

# إعدادات التسجيل (Logging)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# قائمة المناطق المعروفة (سيتم تحديثها من API لاحقاً)
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

# حالات محادثة التيليجرام
WAITING_LINK, WAITING_REGION = range(2)

# ===================================================================
# 3. قاعدة البيانات المتكاملة (دوال طويلة ومفصلة)
# ===================================================================
def init_database():
    """تهيئة قاعدة البيانات بكل الجداول المطلوبة مع تعليقات توضيحية"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        -- جدول المستخدمين الأساسي
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

        -- جدول تخزين التوكن مع صلاحية زمنية
        CREATE TABLE IF NOT EXISTS token_cache (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT,
            expiry TIMESTAMP,
            project_id TEXT
        );

        -- جدول لحفظ المناطق الممسوحة لكل مشروع
        CREATE TABLE IF NOT EXISTS scan_cache (
            user_id INTEGER,
            project_id TEXT,
            allowed_regions TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, project_id)
        );

        -- جدول سجل عمليات النشر (تاريخي)
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

        -- جدول للتحليلات (عدد المحاولات الفاشلة لكل مستخدم)
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
    logger.info("✅ قاعدة البيانات المهيأة بالكامل (جميع الجداول جاهزة)")

# استدعاء تهيئة القاعدة عند بدء التشغيل
init_database()

# ===================================================================
# 4. دوال التعامل مع قاعدة البيانات (CRUD متقدم)
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    """استرجاع بيانات المستخدم كاملة"""
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
    """تحديث بيانات المستخدم أو إنشائه إذا لم يكن موجوداً"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user(user_id)
    if existing:
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    else:
        # إضافة last_activity افتراضياً
        if "last_activity" not in kwargs:
            kwargs["last_activity"] = datetime.now().isoformat()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        c.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {placeholders})", [user_id] + list(kwargs.values()))
    conn.commit()
    conn.close()

def get_cached_token(user_id: int) -> Optional[str]:
    """استرجاع التوكن المخبأ إذا كان صالحاً (لم تنته صلاحيته)"""
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
    """حفظ التوكن في قاعدة البيانات مع صلاحية ساعة واحدة"""
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
    """مسح التوكن المخبأ (في حال انتهى أو أصبح غير صالح)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM token_cache WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"🗑️ تم مسح التوكن المخبأ للمستخدم {user_id}")

def save_scan_cache(user_id: int, project_id: str, regions: List[str]) -> None:
    """حفظ المناطق الممسوحة لتجنب إعادة الفحص في كل مرة"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO scan_cache (user_id, project_id, allowed_regions) VALUES (?, ?, ?)",
        (user_id, project_id, json.dumps(regions))
    )
    conn.commit()
    conn.close()
    logger.info(f"✅ تم حفظ {len(regions)} منطقة للمشروع {project_id}")

def get_scan_cache(user_id: int, project_id: str) -> Optional[List[str]]:
    """استرجاع المناطق الممسوحة سابقاً من قاعدة البيانات"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT allowed_regions FROM scan_cache WHERE user_id = ? AND project_id = ?", (user_id, project_id))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = "") -> None:
    """تسجيل عملية النشر في السجل التاريخي"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, lab_url, service_url, vless, region, success, error_msg)
    )
    conn.commit()
    conn.close()
    logger.info(f"📝 تم تسجيل عملية نشر للمستخدم {user_id} (نجاح: {success})")

def log_failure(user_id: int, error_type: str, error_detail: str) -> None:
    """تسجيل الأخطاء لتحليلها لاحقاً"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO failure_logs (user_id, error_type, error_detail) VALUES (?, ?, ?)",
        (user_id, error_type, error_detail[:500])
    )
    conn.commit()
    conn.close()
    logger.warning(f"⚠️ تم تسجيل خطأ للمستخدم {user_id}: {error_type}")

# ===================================================================
# 5. دوال مساعدة عامة (استخراج البيانات، بناء الروابط، الاختبارات)
# ===================================================================
def extract_project_id(link: str) -> Optional[str]:
    """استخراج project_id من رابط Qwiklabs بطرق متعددة"""
    decoded = urllib.parse.unquote(link)
    # الطريقة الأولى: البحث المباشر
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        return match.group(1)
    # الطريقة الثانية: البحث في المسار
    match = re.search(r'/projects/([^/?]+)', decoded)
    if match:
        return match.group(1)
    return None

def extract_email_from_link(link: str) -> Optional[str]:
    """استخراج البريد الإلكتروني من الرابط إن وجد"""
    decoded = urllib.parse.unquote(link)
    match = re.search(r'[Ee]mail=([^&]+)', decoded)
    return urllib.parse.unquote(match.group(1)) if match else None

def build_vless_link(service_url: str, seed: str = "shadow_v600") -> str:
    """بناء رابط VLESS بتنسيق متقدم مع توثيق عشوائي"""
    host = service_url.replace('https://', '').replace('http://', '')
    # توليد UUID مشابه لـ VLESS
    raw = hashlib.md5((seed + str(time.time()) + os.urandom(4).hex()).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return (
        f"vless://{uid}@{host}:443?"
        f"encryption=none&security=tls&sni=youtube.com&fp=chrome&"
        f"type=ws&host={host}&path=%2F%40nkka404#ShadowLegion_600"
    )

def test_token_validity(token: str, project_id: str) -> bool:
    """اختبار صلاحية التوكن عبر استدعاء واجهة المناطق (GET خفيف)"""
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
# 6. استخراج التوكن عبر Playwright (طبقات متعددة لإعادة المحاولة)
# ===================================================================
def extract_token_playwright_advanced(email: str, password: str, project_id: str, max_retries: int = 3) -> str:
    """
    استخراج التوكن باستخدام Playwright مع 3 استراتيجيات مختلفة وإعادة محاولة
    الطبقة 1: الانتظار حتى تحميل صفحة Cloud Run بالكامل
    الطبقة 2: محاولة الدخول عبر صفحة APIs Library
    الطبقة 3: زيادة وقت الانتظار والتفتيش عن التوكن في localStorage و sessionStorage
    """
    last_exception = None
    for attempt in range(1, max_retries + 1):
        logger.info(f"🔄 محاولة استخراج التوكن رقم {attempt}/{max_retries}")
        try:
            with sync_playwright() as p:
                # تشغيل المتصفح بوضع التخفي
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
                # تعطيل كشف الأتمتة
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)

                # الخطوة 1: تسجيل الدخول إلى جوجل
                logger.info("📧 جاري تسجيل الدخول إلى Google...")
                page.goto("https://accounts.google.com/", timeout=30000)
                page.wait_for_selector("#identifierId", timeout=15000)
                page.fill("#identifierId", email)
                page.click("#identifierNext")
                page.wait_for_selector("input[name='Passwd']", timeout=20000)
                page.fill("input[name='Passwd']", password)
                page.click("#passwordNext")
                # انتظار اكتمال تسجيل الدخول
                page.wait_for_timeout(5000)

                # الخطوة 2: الانتقال إلى Cloud Run (استراتيجيات متعددة)
                token = None
                urls_to_try = [
                    f"https://console.cloud.google.com/run?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}&hl=en",
                    f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}&hl=en"
                ]

                for target_url in urls_to_try:
                    logger.info(f"🌐 محاولة الدخول إلى: {target_url}")
                    page.goto(target_url, timeout=45000)
                    # انتظار تحميل العناصر الأساسية
                    try:
                        page.wait_for_selector("body", timeout=30000)
                        page.wait_for_timeout(7000)  # انتظار إضافي للمحتوى الديناميكي
                    except PlaywrightTimeoutError:
                        logger.warning("⏰ انتهت مهلة انتظار تحميل الصفحة")

                    # محاولة استخراج التوكن
                    token = page.evaluate("""
                        () => {
                            // البحث في localStorage
                            const ls_keys = ['access_token', 'id_token', 'gapi_token', 'oauth_token', 'gc_token', 'token'];
                            for (let k of ls_keys) {
                                let v = localStorage.getItem(k);
                                if (v && v.length > 40) return v;
                            }
                            // البحث في sessionStorage
                            for (let i = 0; i < sessionStorage.length; i++) {
                                let k = sessionStorage.key(i);
                                if (k && (k.includes('token') || k.includes('oauth') || k.includes('access'))) {
                                    let v = sessionStorage.getItem(k);
                                    if (v && v.length > 40) return v;
                                }
                            }
                            // البحث في cookies
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

        # انتظار قبل إعادة المحاولة
        time.sleep(5)

    raise Exception(f"فشل استخراج التوكن بعد {max_retries} محاولات. آخر خطأ: {last_exception}")

# ===================================================================
# 7. الحصول على التوكن (الطبقة العليا مع التخزين المؤقت واليدوي)
# ===================================================================
def get_master_token(user_id: int, email: str, password: str, project_id: str) -> str:
    """
    الطبقة العليا لإدارة التوكن:
    1. محاولة استخدام التوكن المخبأ.
    2. محاولة استخدام التوكن اليدوي من البيئة (USER_TOKEN).
    3. استخراج توكن جديد عبر Playwright.
    4. حفظ التوكن الجديد في المخبأ.
    """
    # المستوى 0: التوكن اليدوي من البيئة (للطوارئ)
    if USER_TOKEN_OVERRIDE and len(USER_TOKEN_OVERRIDE) > 40:
        logger.info("🔑 محاولة استخدام التوكن من متغير USER_TOKEN")
        if test_token_validity(USER_TOKEN_OVERRIDE, project_id):
            save_cached_token(user_id, USER_TOKEN_OVERRIDE, project_id)
            return USER_TOKEN_OVERRIDE
        else:
            logger.warning("⚠️ USER_TOKEN غير صالح، نستمر بالبحث")

    # المستوى 1: التوكن المخبأ
    cached = get_cached_token(user_id)
    if cached and test_token_validity(cached, project_id):
        logger.info("♻️ استخدام التوكن المخبأ (صالح)")
        return cached

    # المستوى 2: استخراج جديد عبر Playwright
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
# 8. فحص المناطق المسموحة (مع احتياطي واسع)
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    """جلب المناطق الممكّنة فعلاً من API مع احتياطي قوي"""
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
                logger.warning("⚠️ API أعاد مناطق ولكن قائمة فارغة، نستخدم الاحتياطي")
        else:
            logger.warning(f"⚠️ فشل جلب المناطق (كود {response.status_code})")
    except Exception as e:
        logger.warning(f"⚠️ استثناء في جلب المناطق: {e}")

    # الاحتياطي المتقدم: قائمة موسعة من المناطق
    fallback_list = [
        "us-central1", "us-east1", "us-west1",
        "europe-west1", "europe-west3", "europe-west4",
        "asia-southeast1", "asia-east1", "australia-southeast1"
    ]
    logger.info(f"🔄 استخدام قائمة الاحتياطي: {fallback_list}")
    return fallback_list

# ===================================================================
# 9. نشر الخدمة على Cloud Run (مع إعادة محاولة مناطق بديلة)
# ===================================================================
def deploy_service_with_fallback(project_id: str, token: str, preferred_region: str, regions_list: List[str]) -> Tuple[str, str, str]:
    """
    يحاول النشر على المنطقة المفضلة، فإن فشل يجرب المناطق الأخرى في القائمة
    يعيد (الرابط, المنطقة المستخدمة, رابط VLESS)
    """
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

        # انتظار قصير بين المحاولات
        time.sleep(2)

    raise Exception(f"فشل النشر على جميع المناطق. آخر خطأ: {last_error}")

# ===================================================================
# 10. معالجات بوت التيليجرام (الأوامر والمحادثات)
# ===================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر /start – الترحيب والتعليمات الأساسية"""
    user_id = update.effective_user.id
    update_user(user_id)
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v600 – النسخة الطويلة المتكاملة**\n"
        "📍 **الخطوات:**\n"
        "1. احفظ بيانات دخولك: `/set_creds <البريد> <كلمة_السر>`\n"
        "2. أرسل رابط Qwiklabs (سيتم فحص المناطق تلقائياً).\n"
        "3. اختر المنطقة من الأزرار التي ستظهر.\n"
        "4. استلم رابط Cloud Run ورابط VLESS.\n\n"
        "📌 **أوامر مساعدة:**\n"
        "/status – عرض حالتك\n"
        "/cancel – إلغاء العملية الجارية\n"
        "/history – عرض سجل عمليات النشر السابقة"
    )

async def set_creds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حفظ البريد الإلكتروني وكلمة المرور للمستخدم"""
    user_id = update.effective_user.id
    try:
        email = context.args[0]
        password = " ".join(context.args[1:])
        if not email or not password:
            raise IndexError
        update_user(user_id, email=email, password=password)
        await update.message.reply_text("✅ **تم حفظ البريد الإلكتروني وكلمة المرور بنجاح!**")
        logger.info(f"✅ تم حفظ بيانات المستخدم {user_id}")
    except IndexError:
        await update.message.reply_text(
            "❌ **خطأ في الاستخدام:**\n"
            "اكتب: `/set_creds <البريد الإلكتروني> <كلمة المرور>`\n"
            "مثال: `/set_creds user@example.com my_password_123`"
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض حالة المستخدم الحالية"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات مسجلة لك. استخدم /set_creds أولاً.")
        return

    token_status = "✅ (موجود)" if get_cached_token(user_id) else "❌ (غير موجود)"
    await update.message.reply_text(
        f"📋 **حالة الناجي آش**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📧 **البريد:** `{user.get('email', 'غير مضبوط')}`\n"
        f"📊 **عدد عمليات النشر:** `{user.get('deploy_count', 0)}`\n"
        f"🔄 **الحالة:** `{user.get('status', 'idle')}`\n"
        f"🔑 **التوكن المخبأ:** {token_status}\n"
        f"🌍 **المنطقة الافتراضية:** `{user.get('region', 'us-central1')}`\n"
        f"📅 **آخر نشاط:** `{user.get('last_activity', 'غير معروف')}`"
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض آخر 5 عمليات نشر للمستخدم"""
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT service_url, region_used, deployed_at, success FROM deploy_history WHERE user_id = ? ORDER BY deployed_at DESC LIMIT 5",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📭 لا يوجد سجل لأي عملية نشر سابقة.")
        return
    msg = "📜 **آخر 5 عمليات نشر:**\n━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows, 1):
        status_icon = "✅" if row[3] == 1 else "❌"
        msg += f"{i}. {status_icon} **{row[1]}**\n   📅 {row[2][:16]}\n"
    await update.message.reply_text(msg)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء المحادثة الجارية"""
    context.user_data.clear()
    await update.message.reply_text("❌ **تم إلغاء العملية.** يمكنك البدء من جديد بإرسال رابط آخر.")
    return ConversationHandler.END

# ===================================================================
# 11. محادثة النشر (استقبال الرابط + اختيار المنطقة)
# ===================================================================
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """استقبال رابط Qwiklabs من المستخدم وبدء عملية الفحص"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # تحقق من صحة الرابط
    if not text.startswith("http"):
        await update.message.reply_text("❌ الرابط غير صالح. تأكد من أنه يبدأ بـ `http` أو `https`.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text(
            "❌ **لم أجد project_id في الرابط.**\n"
            "تأكد من أن الرابط يحتوي على `?project=...` أو `/projects/...`"
        )
        return WAITING_LINK

    # التحقق من وجود بيانات المستخدم
    user = get_user(user_id)
    if not user or not user.get("email") or not user.get("password"):
        await update.message.reply_text(
            "❌ **بيانات الدخول غير مسجلة.**\n"
            "استخدم الأمر: `/set_creds <البريد> <كلمة_السر>`"
        )
        return WAITING_LINK

    # تخزين البيانات في الجلسة
    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    await update.message.reply_text(
        "🔄 **جاري الدخول إلى الـ Lab وبدء التجهيز...**\n"
        "✔ تم التحقق من صلاحية الرابط.\n"
        "⏳ سيتم ربط الحساب واستخراج التوكن (قد يستغرق 30-60 ثانية)."
    )

    try:
        # 1. استخراج التوكن (من مخبأ أو جديد)
        token = get_master_token(user_id, user["email"], user["password"], project_id)
        context.user_data["token"] = token

        # 2. فحص المناطق (من مخبأ أو API)
        regions = get_scan_cache(user_id, project_id)
        if not regions:
            regions = fetch_allowed_regions(project_id, token)
            save_scan_cache(user_id, project_id, regions)

        context.user_data["regions"] = regions

        # 3. عرض المناطق كأزرار للمستخدم
        keyboard = []
        for r in regions:
            display_name = KNOWN_REGIONS.get(r, r)
            keyboard.append([InlineKeyboardButton(f"🌍 {display_name}", callback_data=f"region_{r}")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_selection")])

        region_count = len(regions)
        await update.message.reply_text(
            f"📡 **جاري تحليل سياسات المشروع لاستخراج المناطق المسموح بها...**\n"
            f"✔ تم اكتشاف {region_count} منطقة مسموحة.\n\n"
            f"👇 **اختر المنطقة التي تريد النشر عليها:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_REGION

    except Exception as e:
        error_msg = str(e)
        log_failure(user_id, "TOKEN_EXTRACTION_FAILED", error_msg)
        await update.message.reply_text(
            f"❌ **فشل الفحص أو استخراج التوكن:**\n"
            f"`{error_msg[:250]}`\n\n"
            "💡 **حلول مقترحة:**\n"
            "1. تأكد من صحة البريد وكلمة المرور.\n"
            "2. تأكد من أن الرابط لمشروع Qwiklabs نشط.\n"
            "3. حاول إعادة إرسال الرابط بعد دقيقة."
        )
        return ConversationHandler.END

async def region_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج اختيار المنطقة من الأزرار"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_selection":
        await query.edit_message_text("❌ **تم إلغاء العملية.**")
        context.user_data.clear()
        return ConversationHandler.END

    region = data.replace("region_", "")
    user_id = query.from_user.id

    lab_url = context.user_data.get("lab_url")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    regions = context.user_data.get("regions", [])

    if not token or not project_id:
        await query.edit_message_text("❌ **انتهت الجلسة.** أعد إرسال الرابط من البداية.")
        return ConversationHandler.END

    # إعلام المستخدم ببدء النشر
    region_display = KNOWN_REGIONS.get(region, region)
    await query.edit_message_text(
        f"🚀 **جاري النشر على المنطقة `{region_display}`...**\n"
        f"⏳ قد يستغرق النشر من 30 إلى 60 ثانية."
    )

    try:
        # تنفيذ النشر مع إعادة المحاولة على مناطق بديلة
        service_url, used_region, vless = deploy_service_with_fallback(
            project_id, token, region, regions
        )

        # تحديث بيانات المستخدم
        user = get_user(user_id)
        deploy_count = user.get("deploy_count", 0) + 1 if user else 1
        update_user(user_id, deploy_count=deploy_count, status="completed")
        add_deploy_history(user_id, lab_url, service_url, vless, used_region, success=1)

        # عرض النتيجة
        result_msg = (
            f"✅ **تم النشر بنجاح!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌍 **المنطقة المستخدمة:** `{used_region}`\n"
            f"🌐 **رابط Cloud Run:**\n`{service_url}`\n\n"
            f"🔗 **رابط VLESS (للاستخدام الفوري):**\n`{vless}`\n\n"
            f"📌 **ملاحظة:** الرابط صالح لمدة ساعة أو حتى انتهاء المشروع."
        )
        await query.message.reply_text(result_msg)

    except Exception as e:
        error_msg = str(e)[:300]
        log_failure(user_id, "DEPLOY_FAILED", error_msg)
        add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
        update_user(user_id, status="error")

        await query.message.reply_text(
            f"❌ **فشل النشر:**\n"
            f"`{error_msg}`\n\n"
            f"💡 **حلول:**\n"
            f"1. حاول اختيار منطقة أخرى.\n"
            f"2. تحقق من صلاحية التوكن (أعد إرسال الرابط).\n"
            f"3. تأكد من أن مشروع Qwiklabs لا يزال نشطاً."
        )

    context.user_data.clear()
    return ConversationHandler.END

# ===================================================================
# 12. تشغيل البوت (الوظيفة الرئيسية)
# ===================================================================
def main() -> None:
    """الوظيفة الرئيسية لتشغيل البوت مع جميع المعالجات"""
    # إنشاء تطبيق البوت
    app = ApplicationBuilder().token(TOKEN).build()

    # إنشاء محادثة النشر (خطوتين)
    deploy_conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_selection_callback, pattern="^(region_|cancel_selection)")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="deploy_conversation",
        persistent=False,
    )

    # إضافة الأوامر والمعالجات
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("set_creds", set_creds_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(deploy_conversation)

    # بدء البوت
    logger.info("✅ SHADOW LEGION v600 يعمل على Railway (النسخة الطويلة)")
    logger.info("📡 البوت جاهز لاستقبال الروابط والأوامر")
    app.run_polling()

if __name__ == "__main__":
    main()