#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v46.0 – SIMPLIFIED_WORKING
- نسخة مبسطة للغاية
- جميع الأزرار تعمل
- لا تعقيدات
"""

import os
import re
import time
import json
import base64
import random
import logging
import asyncio
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from playwright.async_api import async_playwright
from pymongo import MongoClient

# ===================================================================
# 1. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("❌ MONGO_URI غير موجود")

MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "shadow_legion")
COOKIES_FILE = "cookies_live.json"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v46.0 (Simplified) بدأ التشغيل...")

# ===================================================================
# 2. الاتصال بـ MongoDB
# ===================================================================
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB_NAME]
users_collection = db["users"]
history_collection = db["deploy_history"]

# ===================================================================
# 3. دوال مساعدة مبسطة
# ===================================================================
KNOWN_REGIONS = {
    "us-central1": "🇺🇸 Iowa",
    "us-east1": "🇺🇸 S. Carolina",
    "us-west1": "🇺🇸 Oregon",
    "europe-west1": "🇧🇪 Belgium",
    "europe-west2": "🇬🇧 London",
    "europe-west3": "🇩🇪 Frankfurt",
    "asia-east1": "🇹🇼 Taiwan",
    "asia-northeast1": "🇯🇵 Tokyo",
    "asia-southeast1": "🇸🇬 Singapore",
}

def region_menu():
    """قائمة المناطق المبسطة."""
    kb = []
    row = []
    for code, name in KNOWN_REGIONS.items():
        short = name.split(" ")[0]
        row.append(InlineKeyboardButton(short, callback_data=f"region_{code}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🎲 عشوائي", callback_data="region_random")])
    kb.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(kb)

def extract_data(link: str) -> Dict:
    """استخراج البيانات (مبسط)."""
    decoded = link
    for _ in range(3):
        decoded = urllib.parse.unquote(decoded)
    
    project = None
    token = None
    email = None
    
    # استخراج token
    match = re.search(r'[?&]token=([^&]+)', decoded)
    if match:
        token = match.group(1)
    
    # استخراج project
    match = re.search(r'[?&]project=([^&]+)', decoded)
    if match:
        project = match.group(1)
    else:
        match = re.search(r'/projects/([^/?#]+)', decoded)
        if match:
            project = match.group(1)
    
    # استخراج email
    match = re.search(r'[?&]Email=([^&]+)', decoded)
    if match:
        email = match.group(1)
    else:
        match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', decoded)
        if match:
            email = match.group(0)
    
    return {"project": project, "token": token, "email": email}

def build_add_session_url(project: str, token: str, email: str) -> str:
    """بناء رابط AddSession."""
    if not project or not token or not email:
        return ""
    continue_url = f"https://console.cloud.google.com/home/dashboard?project={project}"
    encoded = urllib.parse.quote(continue_url, safe='')
    return f"https://accounts.google.com/AddSession?service=accountsettings&sarp=1&continue={encoded}&Email={email}#Email={email}"

# ===================================================================
# 4. الحالات (Conversation States)
# ===================================================================
WAITING_LINK, WAITING_REGION, WAITING_CONFIRM = range(3)

# ===================================================================
# 5. دوال البوت
# ===================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ **Shadow Legion**\n━━━━━━━━━━━━━━━━\nأرسل الرابط، وسأتكفل بالباقي.",
        parse_mode="Markdown"
    )

async def deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 أرسل رابط Qwiklabs أو Google SSO:",
        reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text in ["❌ إلغاء", "🔄 إعادة المحاولة"]:
        await update.message.reply_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    
    data = extract_data(text)
    project = data.get("project")
    token = data.get("token")
    email = data.get("email")
    
    if not project or not token or not email:
        await update.message.reply_text(
            "❌ لم أستطع استخراج البيانات الكاملة من الرابط.\n"
            "تأكد من أنه رابط Qwiklabs صالح."
        )
        return WAITING_LINK
    
    add_url = build_add_session_url(project, token, email)
    if not add_url:
        await update.message.reply_text("❌ فشل بناء رابط AddSession.")
        return WAITING_LINK
    
    context.user_data["project"] = project
    context.user_data["token"] = token
    context.user_data["email"] = email
    context.user_data["add_url"] = add_url
    context.user_data["original_url"] = text
    
    await update.message.reply_text(
        f"✅ **تم الاستخراج**\n"
        f"🆔 Project: `{project}`\n"
        f"📧 Email: `{email}`\n"
        f"🔑 Token: `{token[:15]}...`\n\n"
        f"🌍 اختر المنطقة:",
        parse_mode="Markdown",
        reply_markup=region_menu()
    )
    return WAITING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"✅ region_callback: {query.data}")
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("❌ أُلغي.")
        context.user_data.clear()
        return ConversationHandler.END
    
    # استخراج المنطقة
    if data == "region_random":
        region = random.choice(list(KNOWN_REGIONS.keys()))
    else:
        region = data.replace("region_", "")
    
    if region not in KNOWN_REGIONS:
        await query.edit_message_text("❌ منطقة غير معروفة.")
        return WAITING_REGION
    
    region_name = KNOWN_REGIONS.get(region, region)
    project = context.user_data.get("project")
    email = context.user_data.get("email")
    
    # عرض رسالة التأكيد
    await query.edit_message_text(
        f"📋 **مراجعة النشر**\n\n"
        f"🆔 المشروع: `{project}`\n"
        f"📧 البريد: `{email}`\n"
        f"🌍 المنطقة: {region_name}\n\n"
        f"⚠️ هل أنت متأكد من بدء النشر؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_{region}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ])
    )
    
    context.user_data["region"] = region
    context.user_data["region_name"] = region_name
    return WAITING_CONFIRM

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"✅ confirm_callback: {query.data}")
    
    if query.data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        context.user_data.clear()
        return ConversationHandler.END
    
    # استخراج المنطقة من البيانات
    region = query.data.replace("confirm_", "")
    region_name = context.user_data.get("region_name", region)
    project = context.user_data.get("project")
    add_url = context.user_data.get("add_url")
    
    if not project or not add_url:
        await query.edit_message_text("❌ انتهت الجلسة. أعد الإرسال.")
        context.user_data.clear()
        return ConversationHandler.END
    
    await query.edit_message_text(f"🚀 **جاري النشر على {region_name} ...**\n⏳ 3-6 دقائق.")
    
    # هنا يمكنك استدعاء وظيفة النشر الفعلية
    # success, service, vless, duration = await run_deployment(...)
    
    # محاكاة النجاح (للاختبار)
    await query.message.reply_text(
        f"✅ **تم النشر بنجاح (محاكاة)**\n"
        f"🌍 {region_name}\n"
        f"🌐 https://service-{project[:8]}.run.app\n"
        f"🔗 vless://{project}@example.com:443?security=tls"
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # هذا المعالج يلتقط أي رسالة غير معالجة
    await update.message.reply_text(
        "⚠️ استخدم الأمر `/deploy` لبدء عملية نشر جديدة."
    )
    return ConversationHandler.END

# ===================================================================
# 6. التشغيل الرئيسي
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    # إنشاء محادثة النشر
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("deploy", deploy),
            MessageHandler(filters.Regex("^🚀 نشر جديدة$"), deploy)
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")],
            WAITING_CONFIRM: [CallbackQueryHandler(confirm_callback, pattern="^(confirm_|cancel)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    
    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("❓ الأوامر:\n/start\n/deploy\n/cancel")))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    logger.info("🔥 SHADOW LEGION v46.0 (Simplified) جاهز")
    app.run_polling()

if __name__ == "__main__":
    main()