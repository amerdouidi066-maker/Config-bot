#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHADOW LEGION v6.0 – THE ULTIMATE ARCHITECT (CloudShell Automation)
لا مجال للرفض. ينفذ كل شيء عبر متصفح خفي.
"""

import os
import re
import time
import json
import base64
import hashlib
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ===================================================================
# 1. الإعدادات الأساسية
# ===================================================================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v6.0 (CloudShell Automation) بدأ التشغيل...")

WAITING_LINK = 0
KNOWN_REGIONS = {"us-central1": "🇺🇸 أيوا", "us-east1": "🇺🇸 ساوث كارولina", "europe-west4": "🇳🇱 هولندا"}

# ===================================================================
# 2. دوال مساعدة
# ===================================================================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    return m.group(1) if m else None

def extract_token(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    if m: return m.group(1)
    m = re.search(r'display_token[=:]([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("bot_v6_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

# ===================================================================
# 3. قلب الأتمتة – Playwright + Cloud Shell
# ===================================================================
async def run_in_cloudshell(link: str, project_id: str, token: str) -> str:
    """يفتح المتصفح، يسجل الدخول، يدخل Cloud Shell، ينفذ السكربت، ويعيد النتيجة"""
    async with async_playwright() as p:
        # تشغيل المتصفح (رأسياً، مع خيارات التوافق)
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        page = await context.new_page()

        # --- الخطوة 1: فتح الرابط (لتسجيل الدخول) ---
        logger.info("🌐 فتح رابط تسجيل الدخول...")
        await page.goto(link, timeout=60000, wait_until="networkidle")
        await asyncio.sleep(5)  # انتظار عمليات إعادة التوجيه

        # --- الخطوة 2: الذهاب إلى Cloud Shell ---
        logger.info("📂 التوجه إلى Cloud Shell...")
        await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")
        
        # --- الخطوة 3: انتظار تحميل الطرفية ---
        logger.info("⏳ انتظار تحميل الطرفية... (قد يستغرق 10-15 ثانية)")
        try:
            # انتظار ظهور المطاف (prompt) مثل "student-@cloudshell:~$"
            await page.wait_for_selector("text=/student-.*@cloudshell:~\\$/", timeout=60000)
            logger.info("✅ تم تحميل الطرفية.")
        except PlaywrightTimeout:
            # محاولة بديلة: انتظار أي عنصر يحتوي على "cloudshell"
            await page.wait_for_selector("text=cloudshell", timeout=60000)
            logger.info("✅ تم تحميل الطرفية (طريقة بديلة).")
        
        await asyncio.sleep(3)  # استقرار إضافي

        # --- الخطوة 4: حقن السكربت وتنفيذه ---
        # قراءة نص السكربت من ملف deploy_script.py
        script_content = open("deploy_script.py", "r").read()
        
        # تعديل السكربت ديناميكياً (حقن PROJECT_ID و TOKEN)
        script_content = script_content.replace('os.environ.get("PROJECT_ID")', f'"{project_id}"')
        script_content = script_content.replace('os.environ.get("TOKEN")', f'"{token}"')
        
        # ترميز السكربت بـ Base64 لتجنب مشاكل الأحرف الخاصة
        b64_script = base64.b64encode(script_content.encode()).decode()
        
        # الأوامر التي سنكتبها في الطرفية
        commands = [
            f"echo '{b64_script}' | base64 -d > deploy.py",  # إنشاء الملف
            "python3 deploy.py"  # تشغيله
        ]

        # كتابة الأوامر واحداً تلو الآخر
        for cmd in commands:
            logger.info(f"⌨️ كتابة الأمر: {cmd[:50]}...")
            await page.keyboard.type(cmd)
            await page.keyboard.press("Enter")
            await asyncio.sleep(2)  # انتظار تنفيذ الأمر

        # --- الخطوة 5: انتظار اكتمال التنفيذ وقراءة النتيجة ---
        logger.info("⏳ انتظار اكتمال النشر (قد يستغرق 1-2 دقيقة)...")
        try:
            # انتظار ظهور النتيجة (مثل "VLESS:" أو "SERVICE_URL:")
            await page.wait_for_selector("text=/VLESS:|SERVICE_URL:/", timeout=180000)
            logger.info("✅ تم العثور على النتيجة في الطرفية.")
        except PlaywrightTimeout:
            logger.warning("⚠️ لم يتم العثور على النتيجة، نحاول قراءة آخر ما ظهر...")

        await asyncio.sleep(3)

        # --- الخطوة 6: استخراج النص من الطرفية ---
        # الطرفية (xterm.js) تظهر النص في عناصر span، لذا نأخذ innerText للعنصر الأب
        try:
            # محاولة 1: البحث عن الحاوية الرئيسية للطرفية
            terminal_text = await page.evaluate("""
                () => {
                    const terminal = document.querySelector('.terminal, .xterm, [role="textbox"], .xterm-helper-textarea');
                    if (terminal) return terminal.innerText || terminal.textContent;
                    // إذا لم نجد، نأخذ النص من الجسم كله
                    return document.body.innerText;
                }
            """)
        except:
            # محاولة بديلة: أخذ النص من الصفحة مباشرة
            terminal_text = await page.inner_text("body")
        
        # --- الخطوة 7: استخراج الرابط و VLESS من النص ---
        service_url = None
        vless = None
        
        # البحث عن SERVICE_URL
        match_url = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', terminal_text)
        if match_url:
            service_url = match_url.group(1)
        
        # البحث عن VLESS
        match_vless = re.search(r'VLESS:\s*(vless://[^\s]+)', terminal_text)
        if match_vless:
            vless = match_vless.group(1)
        
        # إذا لم نجد، نبحث عن أي رابط run.app
        if not service_url:
            match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', terminal_text)
            if match:
                service_url = match.group(0)
                # نحاول بناء VLESS إذا لم نجده
                if not vless:
                    vless = build_vless(service_url)

        await browser.close()

        if service_url and vless:
            return f"✅ SERVICE_URL: {service_url}\n\n🔗 VLESS:\n{vless}"
        else:
            # إذا فشل الاستخراج، نعيد آخر 500 حرف من الطرفية للتصحيح
            return f"⚠️ لم أتمكن من استخراج النتيجة بدقة. آخر ما ظهر في الطرفية:\n```\n{terminal_text[-1000:]}\n```"

# ===================================================================
# 4. أوامر البوت
# ===================================================================
async def start(update: Update, context):
    await update.message.reply_text(
        "🔥 **المهندس المعماري – النسخة النهائية**\n\n"
        "أرسل رابط Qwiklabs.\n"
        "سأفتح متصفحاً خفياً، أسجل الدخول، أدخل إلى Cloud Shell، وأنفذ السكربت نيابة عنك.\n"
        "⚠️ تستغرق العملية 2-3 دقائق."
    )

async def receive_link(update: Update, context):
    user_id = update.effective_user.id
    link = update.message.text.strip()
    
    if not link.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK
    
    project_id = extract_project_id(link)
    token = extract_token(link)
    
    if not project_id:
        await update.message.reply_text("❌ لم أجد project_id في الرابط.")
        return WAITING_LINK
    if not token:
        await update.message.reply_text("❌ لم أجد token في الرابط.")
        return WAITING_LINK
    
    # إرسال رسالة انتظار
    await update.message.reply_text(
        f"✅ تم استخراج البيانات:\n🆔 Project: `{project_id}`\n🔑 Token: `{token[:15]}...`\n\n"
        f"🚀 جاري فتح المتصفح الخفي والدخول إلى Cloud Shell... (قد يستغرق 2-3 دقائق)"
    )
    
    try:
        result = await run_in_cloudshell(link, project_id, token)
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل التنفيذ:\n```\n{str(e)[:500]}\n```")

    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

# ===================================================================
# 5. التشغيل
# ===================================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    
    logger.info("🤖 البوت جاهز (مهندس معماري – نسخة CloudShell)")
    app.run_polling()

if __name__ == "__main__":
    import urllib.parse
    main()