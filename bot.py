#!/usr/bin/env python3
import os, re, time, json, subprocess, hashlib, urllib.parse, tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود")

REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west4": "🇳🇱 هولندا",
    "asia-southeast1": "🇸🇬 سنغافورة",
}
WAITING_LINK, WAITING_REGION = range(2)

def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]project=([^&]+)', decoded)
    return m.group(1) if m else None

def extract_token(link):
    decoded = urllib.parse.unquote(link)
    m = re.search(r'[?&]token=([^&]+)', decoded)
    return m.group(1) if m else None

def build_vless(service_url):
    host = service_url.replace('https://','').replace('http://','').split('/')[0]
    raw = hashlib.md5(("gcloud_bot_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

def deploy_with_gcloud(project_id, token, region):
    """
    ينفذ أوامر gcloud مباشرة باستخدام التوكن المستخرج.
    يعيد (service_url, vless, error) أو يرفع استثناء.
    """
    # إنشاء ملف اعتماد مؤقت
    cred_data = {"access_token": token, "token_type": "Bearer", "expires_in": 3600}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(cred_data, f)
        cred_file = f.name

    service_name = f"ahmed-vip1-{int(time.time())}"
    docker_image = "docker.io/ajndjd2/ahmed-vip1"

    try:
        # 1. تسجيل الدخول عبر gcloud
        login_cmd = ["gcloud", "auth", "login", "--cred-file", cred_file, "--quiet"]
        subprocess.run(login_cmd, check=True, capture_output=True)

        # 2. تفعيل API
        enable_cmd = ["gcloud", "services", "enable", "run.googleapis.com", f"--project={project_id}", "--quiet"]
        subprocess.run(enable_cmd, check=True, capture_output=True)
        time.sleep(5)

        # 3. نشر الخدمة
        deploy_cmd = [
            "gcloud", "run", "deploy", service_name,
            "--image", docker_image,
            "--region", region,
            "--platform", "managed",
            "--port", "8080",
            "--allow-unauthenticated",
            "--project", project_id,
            "--quiet"
        ]
        result = subprocess.run(deploy_cmd, capture_output=True, text=True, check=True)
        output = result.stdout + result.stderr

        # 4. استخراج الرابط من المخرجات
        match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', output)
        if match:
            service_url = match.group(0)
            return service_url, build_vless(service_url), None

        # 5. إذا لم يظهر، استخدم describe
        describe_cmd = [
            "gcloud", "run", "services", "describe", service_name,
            "--region", region,
            "--project", project_id,
            "--format", "value(status.url)"
        ]
        for _ in range(6):
            time.sleep(5)
            desc_result = subprocess.run(describe_cmd, capture_output=True, text=True)
            url = desc_result.stdout.strip()
            if url and url.startswith("http"):
                return url, build_vless(url), None

        raise Exception("لم أجد رابط الخدمة بعد المحاولات المتكررة.")
    except subprocess.CalledProcessError as e:
        return None, None, f"فشل gcloud: {e.stderr}"
    finally:
        if os.path.exists(cred_file):
            os.remove(cred_file)

async def start(update, context):
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v21.0 – Ultimate Automation**\n\n"
        "📌 أرسل رابط Qwiklabs (يحتوي على `token=` و `project=`).\n"
        "✅ سأستخدم `gcloud` مباشرة للنشر (بدون متصفح).\n"
        "⚡ أتمتة كاملة 100% – لا حاجة لأي تدخل يدوي."
    )

async def receive_link(update, context):
    text = update.message.text.strip()
    if not text.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return WAITING_LINK

    project_id = extract_project_id(text)
    token = extract_token(text)
    if not project_id or not token:
        await update.message.reply_text("❌ لم أجد project_id أو token في الرابط.")
        return WAITING_LINK

    context.user_data["project_id"] = project_id
    context.user_data["token"] = token
    context.user_data["lab_url"] = text

    keyboard = [[InlineKeyboardButton(f"🌍 {name}", callback_data=f"region_{code}")] for code, name in REGIONS.items()]
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    await update.message.reply_text(
        f"✅ **تم استخراج البيانات**\n🆔 Project: `{project_id}`\n\n🌍 اختر المنطقة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_REGION

async def region_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        context.user_data.clear()
        return

    region = query.data.replace("region_", "")
    project_id = context.user_data.get("project_id")
    token = context.user_data.get("token")
    if not project_id or not token:
        await query.edit_message_text("❌ انتهت الجلسة.")
        return

    await query.edit_message_text(f"🚀 جاري النشر على {REGIONS.get(region, region)}... (1-2 دقيقة)")

    try:
        service_url, vless, error = deploy_with_gcloud(project_id, token, region)
        if error:
            await query.message.reply_text(f"❌ فشل النشر:\n```\n{error}\n```")
        else:
            await query.message.reply_text(
                f"✅ **تم النشر بنجاح!**\n\n"
                f"🌍 المنطقة: {REGIONS.get(region, region)}\n"
                f"🌐 الرابط: `{service_url}`\n\n"
                f"🔗 **VLESS:**\n`{vless}`"
            )
    except Exception as e:
        await query.message.reply_text(f"❌ خطأ: {str(e)}")
    context.user_data.clear()

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_REGION: [CallbackQueryHandler(region_callback, pattern="^(region_|cancel)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()