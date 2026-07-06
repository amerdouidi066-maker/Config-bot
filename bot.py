#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v999 – DIRECT TOKEN FROM LINK
يستخدم التوكن من الرابط مباشرة مع X-Goog-User-Project.
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
    raise ValueError("❌ TOKEN غير موجود في متغيرات البيئة")

DB_PATH = "shadow_direct_link.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (Direct Link) بدأ التشغيل...")

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
    "southamerica-east1": "🇧🇷 ساو باولو",
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
    logger.info("✅ قاعدة البيانات جاهزة")

init_db()

# ===================================================================
# 3. دوال قاعدة البيانات (مختصرة)
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, deploy_count, status, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "deploy_count": row[1], "status": row[2], "last_activity": row[3]}
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

def get_cached_token(user_id: int) -> Optional[Tuple[str, str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, expiry, project_id FROM token_cache WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and datetime.fromisoformat(row[1]) > datetime.now():
        return row[0], row[2]
    return None, None

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

def extract_token_from_link(link: str) -> Optional[str]:
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m:
        return m.group(1)
    # البحث عن display_token
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    if m:
        return m.group(1)
    return None

def build_vless_link(service_url: str) -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5(("direct" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#DirectTunnel"

def test_token_validity(token: str, project_id: str) -> bool:
    if not token or len(token) < 40:
        return False
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": project_id,
            "Content-Type": "application/json"
        }
        r = requests.get(url, headers=headers, timeout=15)
        return r.status_code == 200
    except:
        return False

# ===================================================================
# 5. الحصول على التوكن (من الرابط مباشرة)
# ===================================================================
async def get_token_from_link(link: str, project_id: str) -> Tuple[Optional[str], bool, List[str]]:
    steps = []
    token = extract_token_from_link(link)
    if not token:
        steps.append("❌ لم أجد توكن في الرابط!")
        return None, True, steps

    steps.append(f"🔑 تم استخراج التوكن من الرابط: {token[:20]}...")
    
    # اختبار التوكن مع X-Goog-User-Project
    if test_token_validity(token, project_id):
        steps.append("✅ التوكن صالح مع X-Goog-User-Project!")
        return token, False, steps
    else:
        steps.append("❌ التوكن غير صالح (401 أو 403)")
        return None, True, steps

# ===================================================================
# 6. الحصول على التوكن (مع التخزين المؤقت)
# ===================================================================
async def get_master_token(user_id: int, link: str, project_id: str) -> Tuple[Optional[str], bool, List[str]]:
    cached_token, cached_project = get_cached_token(user_id)
    if cached_token and cached_project == project_id and test_token_validity(cached_token, project_id):
        return cached_token, False, ["♻️ استخدام التوكن المخبأ (صالح)"]

    token, expired, steps = await get_token_from_link(link, project_id)
    if token and not expired and test_token_validity(token, project_id):
        save_cached_token(user_id, token, project_id)
        steps.append("✅ تم حفظ التوكن في المخبأ")
        return token, False, steps
    else:
        return None, True, steps

# ===================================================================
# 7. فحص المناطق والنشر
# ===================================================================
def fetch_allowed_regions(project_id: str, token: str) -> List[str]:
    try:
        url = f"https://run.googleapis.com/v1/projects/{project_id}/locations"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": project_id,
            "Content-Type": "application/json"
        }
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            allowed = [loc["locationId"] for loc in data.get("locations", []) if loc.get("state") == "ENABLED"]
            if allowed:
                return allowed
    except:
        pass
    return ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]

def deploy_to_cloud_run(project_id: str, token: str, region: str) -> Tuple[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }
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
        raise Exception(f"فشل النشر (كود {resp.status_code})")
    service_url = resp.json().get("status", {}).get("url")
    if not service_url:
        service_url = f"https://{service_name}-{region}.run.app"
    return service_url, build_vless_link(service_url)

# ===================================================================
# 8. الأزرار المتطورة
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
        InlineKeyboardButton("⭐ تعيين مفضلة", callback_data="set_pref"),
        InlineKeyboardButton("📊 إحصائيات", callback_data="stats_regions"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)

def confirm_keyboard(region: str, link_preview: str) -> InlineKeyboardMarkup:
    display = KNOWN_REGIONS.get(region, region)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تأكيد النشر على {display}", callback_data=f"confirm_{region}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_regions")]
    ])

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تشغيل خدمة سريعة 😊", callback_data="quick_deploy")],
        [InlineKeyboardButton("📊 حالة الاشتراك", callback_data="subscription_status")],
        [InlineKeyboardButton("📜 سجل عملياتي", callback_data="my_history")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")]
    ])

# ===================================================================
# 9. معالجات البوت
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        f"مرحباً بك في بوت تشغيل الخدمات السحابية! 😊\n\n"
        f"نوع اشتراكك الحالي: **عادي (استخدام شخصي)**\n\n"
        "استخدم الأزرار أدناه للاستفادة من ميزات البوت.\n"
        "البوت يستخدم التوكن من الرابط مباشرة مع X-Goog-User-Project.",
        reply_markup=main_menu_keyboard()
    )

async def button_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "• أرسل الرابط (يستخرج التوكن من الرابط مباشرة).\n"
            "• يستخدم X-Goog-User-Project مع الطلبات.",
            reply_markup=main_menu_keyboard()
        )
        return
    return ConversationHandler.END

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    regions = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"]
    context.user_data["regions"] = regions
    context.user_data["current_page"] = 0
    preferred = get_preferred_region(user_id)
    if preferred and preferred in regions:
        context.user_data["preferred"] = preferred
    await update.message.reply_text(
        "🌍 اختر منطقة النشر (Region) المطلوبة:",
        reply_markup=build_region_keyboard(regions, 0, preferred)
    )
    return WAITING_REGION

# ===================================================================
# 10. معالج الأزرار الثانوية
# ===================================================================
async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        preferred = get_preferred_region(user_id)
        keyboard = build_region_keyboard(regions, page, preferred)
        await query.edit_message_text("🌍 اختر منطقة النشر:", reply_markup=keyboard)
        return WAITING_REGION
    if data == "rescan":
        project_id = context.user_data.get("project_id")
        await query.edit_message_text("🔄 جاري إعادة فحص المناطق...")
        try:
            token, expired, _ = await get_master_token(user_id, context.user_data.get("lab_url"), project_id)
            if expired or not token:
                await query.edit_message_text("⚠️ الرابط لا يحتوي على توكن صالح!")
                return ConversationHandler.END
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
    if data == "stats_regions":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT region_code, success_count, fail_count FROM region_stats ORDER BY success_count DESC")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("📊 لا توجد إحصائيات للمناطق بعد.")
            return WAITING_REGION
        msg = "📊 إحصائيات المناطق:\n"
        for r in rows:
            msg += f"• {KNOWN_REGIONS.get(r[0], r[0])}: ✅ {r[1]} | ❌ {r[2]}\n"
        await query.edit_message_text(msg)
        return WAITING_REGION
    if data == "set_pref":
        pending = context.user_data.get("pending_region")
        if pending:
            set_preferred_region(user_id, pending)
            await query.edit_message_text(f"⭐ تم تعيين {KNOWN_REGIONS.get(pending, pending)} كمنطقة مفضلة!")
            regions = context.user_data.get("regions", [])
            page = context.user_data.get("current_page", 0)
            preferred = get_preferred_region(user_id)
            keyboard = build_region_keyboard(regions, page, preferred)
            await query.message.reply_text("📡 اختر المنطقة:", reply_markup=keyboard)
            return WAITING_REGION
        else:
            await query.edit_message_text("⚠️ اختر منطقة أولاً ثم اضغط 'تعيين مفضلة'.")
            return WAITING_REGION
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
    if data.startswith("select_"):
        region = data.replace("select_", "")
        context.user_data["pending_region"] = region
        link = context.user_data.get("lab_url", "")
        link_preview = link[:80] + "..." if len(link) > 80 else link
        keyboard = confirm_keyboard(region, link_preview)
        await query.edit_message_text(
            f"⚠️ تأكيد عملية النشر المباشر (Cloud Run)\n\n"
            f"🔗 الرابط:\n{link_preview}\n\n"
            f"🆔 Project ID: `{context.user_data.get('project_id')}`\n"
            f"🌍 المنطقة: `{region}`\n\n"
            f"سيتم استخدام التوكن من الرابط مع X-Goog-User-Project.",
            reply_markup=keyboard
        )
        return CONFIRM_DEPLOY
    await query.edit_message_text(f"📩 ضغطة غير متوقعة: `{data}`")
    return WAITING_REGION

# ===================================================================
# 11. تأكيد النشر (استخدام التوكن من الرابط)
# ===================================================================
async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"✅ استلام confirm: {data}")

    if data == "back_to_regions":
        regions = context.user_data.get("regions", [])
        page = context.user_data.get("current_page", 0)
        preferred = get_preferred_region(user_id)
        keyboard = build_region_keyboard(regions, page, preferred)
        await query.edit_message_text("🌍 اختر منطقة النشر:", reply_markup=keyboard)
        return WAITING_REGION

    if data.startswith("confirm_"):
        region = data.replace("confirm_", "")
        lab_url = context.user_data.get("lab_url")
        project_id = context.user_data.get("project_id")

        await query.edit_message_text("🔑 جاري استخراج التوكن من الرابط...")

        token, expired, steps = await get_master_token(user_id, lab_url, project_id)

        for step in steps:
            await query.message.reply_text(f"📌 {step}")
            await asyncio.sleep(0.3)

        if expired or not token:
            await query.message.reply_text(
                "❌ فشل استخراج التوكن من الرابط!\n"
                "تأكد من أن الرابط يحتوي على `token=` أو `display_token=` صالح."
            )
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg="فشل استخراج التوكن")
            context.user_data.clear()
            return ConversationHandler.END

        await query.message.reply_text(f"✅ تم استخراج التوكن! جاري النشر...")

        try:
            service_url, vless = deploy_to_cloud_run(project_id, token, region)
            increment_deploy_count(user_id)
            save_cached_token(user_id, token, project_id)
            add_deploy_history(user_id, lab_url, service_url, vless, region, success=1)

            result = (
                f"🎉 تم النشر بنجاح!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 المنطقة: `{region}`\n"
                f"🌐 رابط Cloud Run:\n`{service_url}`\n\n"
                f"🔗 رابط VLESS:\n`{vless}`\n\n"
                f"📌 الرابط صالح لمدة ساعة."
            )
            await query.message.reply_text(result)

        except Exception as e:
            error_msg = str(e)[:300]
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(f"❌ فشل النشر:\n`{error_msg}`")

        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text(f"📩 ضغطة غير متوقعة في التأكيد: `{data}`")
    return CONFIRM_DEPLOY

# ===================================================================
# 12. إلغاء
# ===================================================================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ===================================================================
# 13. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_main_handler, pattern="^(quick_deploy|subscription_status|my_history|help_menu)$")
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [
                CallbackQueryHandler(region_callback, pattern="^(select_|page_|rescan|set_pref|stats_regions|cancel|noop|back_to_regions|.*)$")
            ],
            CONFIRM_DEPLOY: [
                CallbackQueryHandler(confirm_callback, pattern="^(confirm_|back_to_regions|.*)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (Direct Link) جاهز، بدء Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()