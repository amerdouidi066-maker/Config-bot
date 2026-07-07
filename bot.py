#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION – RAILWAY GCLOUD EDITION
يستخدم gcloud (مثبت عبر apt.txt) بنفس منطق السكربت الناجح.
"""

import os
import re
import time
import json
import hashlib
import logging
import subprocess
import urllib.parse
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

# =============================================
# 🔑 التوكن من متغيرات البيئة
# =============================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود في متغيرات البيئة")

# =============================================
# الإعدادات الثابتة
# =============================================
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"
KNOWN_REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west1": "🇧🇪 بلجيكا",
    "asia-southeast1": "🇸🇬 سنغافورة",
}
WAITING_LINK, WAITING_REGION = range(2)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# دوال مساعدة
# =============================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    return m.group(1) if m else None

def extract_token(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m:
        return m.group(1)
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("railway_gcloud_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return (
        f"vless://{uid}@{host}:443?"
        f"path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&"
        f"security=tls&"
        f"encryption=none&"
        f"host={host}&"
        f"type=ws&"
        f"sni={host}"
        f"#CloudRun"
    )

def run_cmd(cmd):
    """تنفيذ أمر وعرض الناتج (مطابق للسكربت الأصلي)"""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr

# =============================================
# النشر عبر gcloud (نفس deploy_gcloud_only.py)
# =============================================
def deploy_with_gcloud(project_id, region, token):
    # ملف الاعتماد المؤقت
    cred_file = "/tmp/gcloud_cred.json"
    cred_data = {"access_token": token, "token_type": "Bearer", "expires_in": 3600}
    with open(cred_file, "w") as f:
        json.dump(cred_data, f)

    service_name = f"ahmed-vip1-{int(time.time())}"

    try:
        # 1. تسجيل الدخول
        login_cmd = ["gcloud", "auth", "login", "--cred-file", cred_file, "--quiet"]
        run_cmd(login_cmd)

        # 2. تفعيل API
        enable_cmd = ["gcloud", "services", "enable", "run.googleapis.com", f"--project={project_id}", "--quiet"]
        run_cmd(enable_cmd)
        time.sleep(5)

        # 3. نشر الخدمة
        deploy_cmd = [
            "gcloud", "run", "deploy", service_name,
            "--image", DOCKER_IMAGE,
            "--region", region,
            "--platform", "managed",
            "--port", "8080",
            "--allow-unauthenticated",
            "--project", project_id,
            "--quiet"
        ]
        stdout, stderr = run_cmd(deploy_cmd)
        if "ERROR" in stderr or "error" in stderr.lower():
            raise Exception(f"فشل النشر: {stderr}")

        # 4. استخراج الرابط من المخرجات
        output = stdout + stderr
        match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', output)
        if match:
            service_url = match.group(0)
            return service_url, build_vless(service_url)

        # 5. إذا لم يظهر، استخدم gcloud describe
        describe_cmd = [
            "gcloud", "run", "services", "describe", service_name,
            "--region", region,
            "--project", project_id,
            "--format", "value(status.url)"
        ]
        for _ in range(6):  # 6 محاولات كل 5 ثوانٍ
            time.sleep(5)
            url, _ = run_cmd(describe_cmd)
            if url and url.startswith("http"):
                return url, build_vless(url)

        raise Exception("لم أجد رابط الخدمة بعد المحاولات.")

    except Exception as e:
        raise Exception(f"فشل النشر: {str(e)}")
    finally:
        if os.path.exists(cred_file):
            os.remove(cred_file)

# =============================================
# أوامر البوت
# =============================================
async def start(update: Update, context):
    await update.message.reply_text(
        "🔥 **Shadow VPN – gcloud Bot (Railway)**\n"
        "أرسل رابط Qwiklabs (يحتوي على `token=` و `project=`).\n"
        "سأستخدم gcloud للنشر (نفس الطريقة الناجحة)."
    )

async def receive_link(update: Update, context):
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    token = extract_token(text)

    if not project_id:
        await update.message.reply_text("❌ لم أجد project_id في الرابط.")
        return WAITING_LINK

    if not token:
        await update.message.reply_text("❌ لم أجد token في الرابط.")
        return WAITING_LINK

    context.user_data["project_id"] = project_id
    context.user_data["token"] = token
    context.user_data["link"] = text

    keyboard = []
    for r, name in KNOWN_REGIONS.items():
        keyboard.append([InlineKeyboardButton(f"🌍 {name}", callback_data=f"region_{r}")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

    await update.message.reply_text(
        f"✅ **تم استخراج البيانات!**\n"
        f"🆔 Project ID: `{project_id}`\n\n"
        f"🌍 اختر المنطقة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_REGION

async def region_callback(update: Update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        return ConversationHandler.END

    region = query.data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")

    if not project_id or not token:
        await query.edit_message_text("❌ انتهت الجلسة. أرسل الرابط مجدداً.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"🚀 **جاري النشر على {KNOWN_REGIONS.get(region, region)}...**\n"
        f"⏳ قد يستغرق 1-2 دقيقة."
    )

    try:
        service_url, vless = deploy_with_gcloud(project_id, region, token)
        await query.message.reply_text(
            f"✅ **تم النشر بنجاح!**\n\n"
            f"🌍 المنطقة: {KNOWN_REGIONS.get(region, region)}\n"
            f"🌐 الرابط: `{service_url}`\n\n"
            f"🔗 **VLESS:**\n`{vless}`"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ فشل النشر:\n```\n{str(e)}\n```")

    return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# =============================================
# التشغيل
# =============================================
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
    app.add_handler(conv)

    print("🤖 Shadow VPN Bot يعمل على Railway (gcloud)...")
    app.run_polling()

if __name__ == "__main__":
    main()