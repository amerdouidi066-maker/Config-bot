#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, time, base64, hashlib, logging, asyncio, urllib.parse
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("🚀 SHADOW LEGION v7.0 (CloudShell Automation) بدأ التشغيل...")

WAITING_LINK = 0

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

def extract_email(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]Email=([^&]+)', decoded)
    if m: return m.group(1)
    m = re.search(r'#Email=([^&]+)', decoded)
    return m.group(1) if m else "student-02-93b0e6f4b24d@qwiklabs.net"

async def run_in_cloudshell(link: str, project_id: str, token: str, email: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        # --- تسجيل الدخول عبر الرابط ---
        logger.info("🌐 فتح رابط تسجيل الدخول...")
        await page.goto(link, timeout=60000, wait_until="networkidle")
        await asyncio.sleep(5)

        # التحقق من عدم ظهور شاشة تسجيل الدخول
        try:
            email_input = await page.wait_for_selector("input[type='email']", timeout=3000)
            if email_input:
                await browser.close()
                return "❌ **انتهت صلاحية الرابط!** يرجى الحصول على رابط جديد."
        except:
            pass

        logger.info("✅ تم تسجيل الدخول بنجاح.")

        # --- الدخول إلى Cloud Shell ---
        logger.info("📂 التوجه إلى Cloud Shell...")
        await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")

        # --- انتظار تحميل الطرفية (بطريقة صبورة) ---
        logger.info("⏳ انتظار تحميل الطرفية...")
        terminal_ready = False
        for attempt in range(10):  # 10 محاولات كل 5 ثواني = 50 ثانية
            try:
                await page.wait_for_selector(".xterm, .terminal, [role='textbox'], textarea", timeout=5000)
                logger.info("✅ تم العثور على عنصر الطرفية.")
                terminal_ready = True
                break
            except:
                logger.info(f"⏳ المحاولة {attempt+1}/10: لا يزال التحميل جارياً...")
        if not terminal_ready:
            logger.warning("⚠️ لم نتمكن من تأكيد تحميل الطرفية، ننتظر 15 ثانية ونكمل...")
            await asyncio.sleep(15)

        await asyncio.sleep(3)

        # --- إعداد السكربت وحقنه ---
        with open("deploy_script.py", "r") as f:
            script_content = f.read()
        script_content = script_content.replace('os.environ.get("PROJECT_ID")', f'"{project_id}"')
        script_content = script_content.replace('os.environ.get("TOKEN")', f'"{token}"')
        script_content = script_content.replace('os.environ.get("EMAIL")', f'"{email}"')
        b64_script = base64.b64encode(script_content.encode()).decode()

        commands = [
            f"echo '{b64_script}' | base64 -d > deploy.py",
            "python3 deploy.py",
            "cat result.txt"  # قراءة النتيجة بعد التنفيذ
        ]

        for cmd in commands:
            logger.info(f"⌨️ كتابة الأمر: {cmd[:50]}...")
            await page.keyboard.type(cmd)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)

        # --- انتظار ظهور النتيجة ---
        logger.info("⏳ انتظار اكتمال النشر وظهور النتيجة...")
        try:
            await page.wait_for_selector("text=/SERVICE_URL:|VLESS:/", timeout=180000)
            logger.info("✅ تم العثور على النتيجة.")
        except:
            logger.warning("⚠️ لم يتم العثور على النتيجة خلال المهلة.")

        await asyncio.sleep(3)
        terminal_text = await page.evaluate("() => document.body.innerText")
        await browser.close()

        # استخراج SERVICE_URL و VLESS من النص
        service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', terminal_text)
        vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', terminal_text)

        if service_match and vless_match:
            return f"✅ SERVICE_URL: {service_match.group(1)}\n\n🔗 VLESS:\n{vless_match.group(1)}"
        else:
            return f"⚠️ لم أتمكن من استخراج النتيجة. آخر ما ظهر في الطرفية:\n```\n{terminal_text[-800:]}\n```"

async def start(update: Update, context):
    await update.message.reply_text(
        "🔥 **المهندس المعماري – النسخة النهائية v7.0**\n\n"
        "أرسل رابط Qwiklabs.\n"
        "سأفتح متصفحاً خفياً، أسجل الدخول، وأدخل إلى Cloud Shell، وأنفذ السكربت الناجح نيابة عنك.\n"
        "⏳ تستغرق العملية 2-3 دقائق."
    )

async def receive_link(update: Update, context):
    link = update.message.text.strip()
    if not link.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(link)
    token = extract_token(link)
    email = extract_email(link)

    if not project_id or not token:
        await update.message.reply_text("❌ لم أجد project_id أو token في الرابط.")
        return WAITING_LINK

    await update.message.reply_text(
        f"✅ **تم استخراج البيانات:**\n"
        f"🆔 Project: `{project_id}`\n"
        f"📧 Email: `{email}`\n"
        f"🔑 Token: `{token[:15]}...`\n\n"
        f"🚀 جاري التنفيذ... (2-3 دقائق)"
    )

    try:
        result = await run_in_cloudshell(link, project_id, token, email)
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **فشل التنفيذ:**\n```\n{str(e)[:500]}\n```")

    return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("❌ تم الإلغاء")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()