#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v999 – UI AUTOMATION PRO
أتمتة كاملة لـ Cloud Console مع واجهة احترافية وأزرار متطورة.
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
from datetime import datetime
from typing import Optional, Dict, List, Tuple

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
    raise ValueError("❌ TOKEN غير موجود في متغيرات البيئة")

DB_PATH = "shadow_pro_ui.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v999 (UI Automation Pro) بدأ التشغيل...")

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
# 3. دوال قاعدة البيانات
# ===================================================================
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, deploy_count, status, last_activity FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "deploy_count": row[1],
            "status": row[2],
            "last_activity": row[3]
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

def add_deploy_history(user_id: int, lab_url: str, service_url: str, vless: str, region: str, success: int = 1, error_msg: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO deploy_history (user_id, lab_url, service_url, vless_link, region_used, success, error_msg) VALUES (?,?,?,?,?,?,?)",
              (user_id, lab_url, service_url, vless, region, success, error_msg))
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

def build_vless_link(service_url: str) -> str:
    host = service_url.replace('https://', '').replace('http://', '')
    raw = hashlib.md5(("ui_pro" + str(time.time())).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?encryption=none&security=tls&sni=youtube.com&fp=chrome&type=ws&host={host}&path=%2F%40nkka404#ProUITunnel"

# ===================================================================
# 5. النشر عبر أتمتة الواجهة
# ===================================================================
async def deploy_via_ui(link: str, project_id: str, region: str, send_status) -> Tuple[str, str]:
    """
    ينشر الخدمة عبر أتمتة واجهة المستخدم.
    يعيد (service_url, vless_link)
    """
    service_name = f"app-{int(time.time())}"
    steps = []

    try:
        await send_status("🌐 **جاري فتح الرابط في المتصفح...**")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--incognito"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            
            await send_status("📂 **جاري التوجه إلى Cloud Run Console...**")
            await page.goto(link, timeout=60000)
            await page.wait_for_timeout(5000)
            
            await page.goto(f"https://console.cloud.google.com/run?project={project_id}", timeout=60000)
            await page.wait_for_timeout(5000)
            
            await send_status("🔍 **جاري البحث عن زر 'Create Service'...**")
            create_clicked = False
            for text in ["Create Service", "إنشاء خدمة", "CREATE SERVICE"]:
                try:
                    await page.click(f"text={text}", timeout=5000)
                    await send_status(f"✅ **تم النقر على '{text}'**")
                    create_clicked = True
                    break
                except:
                    continue
            if not create_clicked:
                try:
                    await page.click("button:has-text('Create')", timeout=5000)
                    await send_status("✅ **تم النقر على زر Create**")
                    create_clicked = True
                except:
                    raise Exception("❌ لم أجد زر Create Service")
            
            await send_status("⏳ **انتظار ظهور النموذج...**")
            await page.wait_for_timeout(10000)
            
            await send_status("✏️ **جاري ملء البيانات تلقائياً...**")
            # إدخال البيانات عبر JavaScript
            await page.evaluate("""
                (data) => {
                    const { serviceName, image, port } = data;
                    const inputs = document.querySelectorAll('input');
                    for (let inp of inputs) {
                        const label = (inp.placeholder || inp.name || inp.id || '').toLowerCase();
                        if (label.includes('service') || label.includes('name') || label.includes('اسم')) {
                            inp.value = serviceName;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        if (label.includes('image') || label.includes('container') || label.includes('صورة')) {
                            inp.value = image;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        if (label.includes('port') || label.includes('منفذ')) {
                            inp.value = port;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }
                }
            """, {"serviceName": service_name, "image": "ajndjd2/ahmed-vip1", "port": "8080"})
            
            await send_status("🔓 **تفعيل الطلبات غير المصادق عليها...**")
            try:
                await page.click("input[type='checkbox']")
            except:
                try:
                    await page.click("label:has-text('Allow unauthenticated')")
                except:
                    pass
            
            await send_status("🚀 **الضغط على زر Create...**")
            try:
                await page.click("button:has-text('Create')", timeout=10000)
            except:
                try:
                    await page.click("button:has-text('إنشاء')", timeout=10000)
                except:
                    await page.click("button[type='submit']", timeout=10000)
            
            await send_status("⏳ **انتظار اكتمال النشر (قد يستغرق 30-60 ثانية)...**")
            await page.wait_for_timeout(30000)
            
            await send_status("🔗 **جاري استخراج رابط الخدمة...**")
            service_url = None
            
            # محاولة استخراج الرابط بطرق متعددة
            content = await page.content()
            match = re.search(r'https://[^\s]+\.run\.app', content)
            if match:
                service_url = match.group(0)
            
            if not service_url:
                try:
                    link_elem = await page.query_selector("a[href*='run.app']")
                    if link_elem:
                        service_url = await link_elem.get_attribute('href')
                except:
                    pass
            
            if not service_url:
                current_url = page.url
                if "run.app" in current_url:
                    service_url = current_url
            
            if not service_url:
                try:
                    await page.wait_for_selector("a[href*='run.app']", timeout=15000)
                    link_elem = await page.query_selector("a[href*='run.app']")
                    if link_elem:
                        service_url = await link_elem.get_attribute('href')
                except:
                    pass
            
            await browser.close()
            
            if not service_url:
                raise Exception("لم أجد رابط الخدمة بعد النشر")
            
            vless = build_vless_link(service_url)
            return service_url, vless
            
    except PlaywrightTimeoutError:
        raise Exception("⏰ انتهت مهلة تحميل الصفحة")
    except Exception as e:
        raise Exception(f"❌ فشل النشر: {str(e)}")

# ===================================================================
# 6. واجهة البوت (أزرار وتنسيق احترافي)
# ===================================================================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 نشر خدمة جديدة", callback_data="deploy")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [InlineKeyboardButton("⭐ المنطقة المفضلة", callback_data="pref")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help")]
    ])

def region_keyboard(regions: List[str], preferred: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    for r in regions:
        display = KNOWN_REGIONS.get(r, r)
        star = " ⭐" if r == preferred else ""
        keyboard.append([InlineKeyboardButton(f"🌍 {display}{star}", callback_data=f"region_{r}")])
    keyboard.append([
        InlineKeyboardButton("🔄 إعادة تحميل", callback_data="reload_regions"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v999 – UI Automation Pro**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 **البوت يقوم بأتمتة النشر على Cloud Run**\n"
        "• أرسل رابط Qwiklabs (حتى لو كان وسيطاً).\n"
        "• سيتم فتح Console تلقائياً ونشر الخدمة.\n"
        "• لا يحتاج إلى توكن أو صلاحيات إضافية.\n\n"
        "👇 **اختر أحد الخيارات أدناه:**",
        reply_markup=main_menu_keyboard()
    )

async def button_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "deploy":
        await query.edit_message_text(
            "🔗 **أرسل رابط Qwiklabs الآن:**\n"
            "(يمكنك نسخ الرابط من المتصفح بعد بدء الـ Lab)"
        )
        return WAITING_LINK

    elif data == "stats":
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("📭 لا توجد بيانات كافية.", reply_markup=main_menu_keyboard())
            return ConversationHandler.END
        await query.edit_message_text(
            f"📊 **إحصائياتك:**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 عدد عمليات النشر: `{user['deploy_count']}`\n"
            f"🔄 الحالة: `{user['status']}`\n"
            f"📅 آخر نشاط: `{user['last_activity'][:16]}`",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    elif data == "pref":
        preferred = get_preferred_region(user_id)
        if preferred:
            display = KNOWN_REGIONS.get(preferred, preferred)
            await query.edit_message_text(
                f"⭐ **منطقتك المفضلة:** `{display}`\n"
                f"يمكنك تغييرها عند اختيار منطقة جديدة.",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                "⭐ **لم تحدد منطقة مفضلة بعد.**\n"
                "عند نشر خدمة، ستظهر لك أزرار المناطق، ويمكنك اختيار واحدة.",
                reply_markup=main_menu_keyboard()
            )
        return ConversationHandler.END

    elif data == "help":
        await query.edit_message_text(
            "❓ **المساعدة:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ أرسل رابط Qwiklabs.\n"
            "2️⃣ اختر المنطقة من الأزرار.\n"
            "3️⃣ انتظر حتى يكتمل النشر (1-2 دقيقة).\n"
            "4️⃣ استلم رابط Cloud Run ورابط VLESS.\n\n"
            "📌 **ملاحظات:**\n"
            "• البوت يعمل مع الجلسات المؤقتة.\n"
            "• لا يحتاج إلى توكن أو صلاحيات API.\n"
            "• إذا واجهت مشكلة، أعد إرسال الرابط.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    return ConversationHandler.END

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح. أرسل رابطاً يبدأ بـ `http`")
        return WAITING_LINK

    project_id = extract_project_id(text)
    if not project_id:
        await update.message.reply_text("❌ لا يوجد `project_id` في الرابط.")
        return WAITING_LINK

    context.user_data["lab_url"] = text
    context.user_data["project_id"] = project_id

    # عرض المناطق
    regions = list(KNOWN_REGIONS.keys())
    preferred = get_preferred_region(user_id)

    # إذا كانت المنطقة المفضلة موجودة، نضعها أولاً
    if preferred and preferred in regions:
        regions.remove(preferred)
        regions.insert(0, preferred)

    context.user_data["regions"] = regions

    region_list = "\n".join([f"  • {KNOWN_REGIONS.get(r, r)}" for r in regions[:6]])
    await update.message.reply_text(
        f"✅ **تم استخراج project_id:**\n"
        f"`{project_id}`\n\n"
        f"🌍 **المناطق المتاحة:**\n{region_list}\n\n"
        f"👇 **اختر المنطقة التي تريد النشر عليها:**",
        reply_markup=region_keyboard(regions, preferred)
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "cancel":
        await query.edit_message_text("❌ **تم الإلغاء.**", reply_markup=main_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END

    if data == "reload_regions":
        regions = list(KNOWN_REGIONS.keys())
        preferred = get_preferred_region(user_id)
        if preferred and preferred in regions:
            regions.remove(preferred)
            regions.insert(0, preferred)
        context.user_data["regions"] = regions
        await query.edit_message_text(
            "🔄 **تم إعادة تحميل المناطق.**\nاختر المنطقة:",
            reply_markup=region_keyboard(regions, preferred)
        )
        return WAITING_REGION

    if data.startswith("region_"):
        region = data.replace("region_", "")
        lab_url = context.user_data.get("lab_url")
        project_id = context.user_data.get("project_id")

        if not lab_url or not project_id:
            await query.edit_message_text("❌ **انتهت الجلسة.** أعد إرسال الرابط.")
            return ConversationHandler.END

        # حفظ المنطقة المفضلة
        set_preferred_region(user_id, region)

        await query.edit_message_text(
            f"🚀 **جاري النشر على المنطقة:**\n"
            f"`{KNOWN_REGIONS.get(region, region)}`\n\n"
            f"⏳ **الرجاء الانتظار... قد يستغرق 1-2 دقيقة.**"
        )

        # دوال لإرسال رسائل التقدم
        async def send_status(msg):
            await query.message.reply_text(msg)

        try:
            service_url, vless = await deploy_via_ui(lab_url, project_id, region, send_status)
            increment_deploy_count(user_id)
            add_deploy_history(user_id, lab_url, service_url, vless, region, success=1)

            result = (
                f"✅ **تم النشر بنجاح!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 **المنطقة المستخدمة:** `{KNOWN_REGIONS.get(region, region)}`\n"
                f"🌐 **رابط Cloud Run:**\n`{service_url}`\n\n"
                f"🔗 **رابط VLESS:**\n`{vless}`\n\n"
                f"📌 **الرابط صالح لمدة ساعة.**"
            )
            await query.message.reply_text(result, reply_markup=main_menu_keyboard())

        except Exception as e:
            error_msg = str(e)
            add_deploy_history(user_id, lab_url, "", "", region, success=0, error_msg=error_msg)
            await query.message.reply_text(
                f"❌ **فشل النشر:**\n`{error_msg}`\n\n"
                f"💡 **حلول:**\n"
                f"• تأكد من أن الرابط يعمل في المتصفح.\n"
                f"• حاول إعادة إرسال الرابط.\n"
                f"• إذا استمر الفشل، استخدم رابط 'Open Console' المباشر.",
                reply_markup=main_menu_keyboard()
            )

        context.user_data.clear()
        return ConversationHandler.END

    return WAITING_REGION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ **تم الإلغاء.**", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ===================================================================
# 7. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_main_handler, pattern="^(deploy|stats|pref|help)$")
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|reload_regions|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)

    logger.info("🚀 SHADOW LEGION v999 (UI Automation Pro) جاهز للعمل")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()