#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 SHADOW LEGION v200 - THE ABYSS FINAL
✅ تحليل الرابط + قائمة مناطق بالأعلام + طابور + 14 محاولة ABYSS
"""

import os
import sys
import time
import re
import json
import hashlib
import logging
import sqlite3
import urllib.parse
import random
import threading
import queue
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

import requests

# ====================== CONFIG ======================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN environment variable not set")

DEFAULT_REGION = "us-central1"

REGIONS = {
    "us-central1": "🇺🇸 أيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
    "asia-southeast1": "🇸🇬 سنغافورة"
}

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = "shadow_legion.db"

# ====================== DATABASE ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            region TEXT DEFAULT 'us-central1',
            deploy_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            last_result TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lab_url TEXT,
            service_url TEXT,
            vless_link TEXT,
            deployed_at TEXT,
            success INTEGER
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if get_user(user_id):
        for key, val in kwargs.items():
            c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (val, user_id))
    else:
        c.execute(
            "INSERT INTO users (user_id, region) VALUES (?, ?)",
            (user_id, kwargs.get('region', DEFAULT_REGION))
        )
    conn.commit()
    conn.close()

init_db()

# ====================== EXTRACTORS ======================
def extract_project_id(link):
    decoded = urllib.parse.unquote(link)
    match = re.search(r'project=([^&]+)', decoded)
    return match.group(1) if match else None

def extract_token(link):
    decoded = urllib.parse.unquote(link)
    match = re.search(r'token=([^&]+)', decoded)
    return match.group(1) if match else None

def analyze_link(link):
    return {
        "project_id": extract_project_id(link),
        "token": extract_token(link),
        "valid": bool(extract_project_id(link) and extract_token(link))
    }

# ====================== ABYSS DEPLOY ======================
def abyss_bodies(base):
    return [
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-a"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-b"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1"}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-c", "annotations": {"run.googleapis.com/launch-stage": "GA"}}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-d"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1"}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-e"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}, "traffic": [{"percent": 100}]}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-f"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}], "serviceAccountName": "default"}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-g", "labels": {"cloud.googleapis.com/location": "us-central1"}}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-h"}, "spec": {"template": {"metadata": {"annotations": {"autoscaling.knative.dev/maxScale": "1"}}}, "spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-i"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}], "env": [{"name": "PORT", "value": "8080"}]}]}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-j"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}], "timeoutSeconds": 300}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-k"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}], "containerConcurrency": 10}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-l"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}], "serviceAccountName": "shadow-bot"}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-m"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}], "nodeSelector": {"cloud.google.com/gke-nodepool": "default-pool"}}}}},
        {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": f"{base}-n"}, "spec": {"template": {"spec": {"containers": [{"image": "ajndjd2/ahmed-vip1", "ports": [{"containerPort": 8080}]}]}, "enableServiceLinks": False}}}
    ]

def abyss_agents():
    return [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Googlebot/2.1",
        "curl/7.81.0",
        "ShadowAbyss/9.9.9",
        "Python-Requests/2.32.0",
        "ApocalypseBot/1.0"
    ]

def the_abyss_deploy(project_id, token, region, send_message):
    """THE ABYSS - 14 محاولة بأشكال مختلفة"""
    
    send_message("⛧ **تفعيل THE ABYSS...**")
    send_message("🌑 **الهاوية تبتلع كل شيء...**")
    
    base = f"shadow-abyss-{int(time.time())}"
    bodies = abyss_bodies(base)
    agents = abyss_agents()
    
    last_error = None
    
    for attempt in range(1, len(bodies) + 1):
        try:
            body = random.choice(bodies)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": random.choice(agents),
                "X-Goog-User-Project": project_id,
                "X-Goog-Request-ID": hashlib.md5(str(time.time() + random.random()).encode()).hexdigest()
            }
            
            send_message(f"⛧ **محاولة ABYSS {attempt}/{len(bodies)}**")
            
            url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
            
            r = requests.post(url, headers=headers, json=body, timeout=300)
            
            if r.status_code in (200, 201):
                service_url = r.json().get('status', {}).get('url') or f"https://{base}-{region}.run.app"
                host = service_url.replace('https://', '')
                uid = hashlib.md5(str(time.time() + random.random()).encode()).hexdigest()[:32]
                vless = f"vless://{uid}@{host}:443?type=ws&security=tls&path=/&sni=youtube.com&fp=chrome#{base}"
                
                send_message(f"""⛧ **نجح النشر في الهاوية!**

🌍 **المنطقة:** {region}
🌐 **رابط الخدمة:** `{service_url}`
🔗 **VLESS:** `{vless}`

🔥 **SHADOW LEGION v200 - THE ABYSS VICTORY**""")
                return service_url, vless, True
                
            elif r.status_code == 401:
                send_message(f"⛧ **401 - التوكن منتهي. {len(bodies)-attempt} محاولة متبقية**")
                last_error = "UNAUTHORIZED_TOKEN"
                continue
            elif r.status_code == 403:
                send_message(f"⛧ **403 - صلاحية مرفوضة. جاري تجربة هيكل آخر**")
                last_error = "FORBIDDEN"
                continue
            elif r.status_code == 404:
                send_message(f"⛧ **404 - مشروع غير موجود. تحقق من project_id**")
                raise Exception("PROJECT_NOT_FOUND")
            else:
                send_message(f"⛧ **{r.status_code} - فشل، جاري التبديل...**")
                last_error = f"HTTP_{r.status_code}"
                
            time.sleep(random.uniform(2, 5))
            
        except Exception as e:
            last_error = str(e)
            send_message(f"⛧ **خطأ: {last_error[:100]}**")
            time.sleep(random.uniform(2, 5))
    
    # الفشل النهائي
    if "UNAUTHORIZED_TOKEN" in str(last_error):
        raise Exception("❗ **التوكن منتهي الصلاحية**\nيرجى الحصول على رابط جديد من Qwiklabs")
    elif "FORBIDDEN" in str(last_error):
        raise Exception("❗ **صلاحية مرفوضة**\nقد تحتاج إلى تفعيل الفوترة في المشروع")
    else:
        raise Exception(f"❗ **فشلت جميع المحاولات ({len(bodies)})**\nآخر خطأ: {last_error[:150]}")

# ====================== QUEUE ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                item = task_queue.get()
                user_id = item['user_id']
                link = item['link']
                region = item['region']
                context = item['context']
                loop = item['loop']
                bot = context.bot

                async def send_message(text):
                    try:
                        await bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"فشل الإرسال: {e}")

                # ========== تنفيذ النشر ==========
                async def execute():
                    try:
                        await send_message("🌑 **تم قبول طلبك...**")
                        await asyncio.sleep(1)
                        
                        analysis = analyze_link(link)
                        if not analysis["valid"]:
                            await send_message("❌ **الرابط غير صالح**")
                            return
                        
                        await send_message(f"🔍 **تحليل الرابط:**\nProject ID: `{analysis['project_id']}`\nToken: {'✅ موجود' if analysis['token'] else '❌ مفقود'}")
                        await asyncio.sleep(1)
                        
                        await send_message(f"🚀 **جاري نشر على {REGIONS.get(region, region)}**")
                        await asyncio.sleep(1)
                        
                        # THE ABYSS
                        service_url, vless, success = await asyncio.to_thread(
                            the_abyss_deploy,
                            analysis['project_id'],
                            analysis['token'],
                            region,
                            lambda msg: asyncio.run_coroutine_threadsafe(send_message(msg), loop)
                        )
                        
                        await send_message("✅ **تم النشر بنجاح!**")
                        await send_message(f"🌐 **رابط الخدمة:** `{service_url}`\n🔗 **VLESS:** `{vless}`")
                        
                        # حفظ السجل
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute("UPDATE users SET deploy_count = deploy_count + 1, status = 'completed', last_result = ? WHERE user_id = ?", (service_url, user_id))
                        c.execute("INSERT INTO history (user_id, lab_url, service_url, vless_link, deployed_at, success) VALUES (?, ?, ?, ?, ?, 1)",
                                 (user_id, link, service_url, vless, datetime.now().isoformat()))
                        conn.commit()
                        conn.close()
                        
                    except Exception as e:
                        error_msg = str(e)
                        await send_message(f"❌ **فشل النشر:**\n{error_msg}")
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute("UPDATE users SET status = 'error', last_result = ? WHERE user_id = ?", (error_msg, user_id))
                        c.execute("INSERT INTO history (user_id, lab_url, success, deployed_at) VALUES (?, ?, 0, ?)",
                                 (user_id, link, datetime.now().isoformat()))
                        conn.commit()
                        conn.close()
                    finally:
                        global processing
                        processing = False

                # تشغيل الدالة غير المتزامنة
                asyncio.run_coroutine_threadsafe(execute(), loop)
                
            except Exception as e:
                logger.error(f"خطأ في الطابور: {e}")
                processing = False
        time.sleep(2)

threading.Thread(target=process_queue, daemon=True).start()

# ====================== BOT ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')]
    ]
    await update.message.reply_text(
        "🔥 **SHADOW LEGION v200 - THE ABYSS**\n"
        "📡 أقوى بوت نشر Cloud Run مع 14 محاولة خبيثة\n"
        "أمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def deploy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔗 **أرسل رابط SSO الآن**")
    return 1

async def receive_lab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text.strip()

    analysis = analyze_link(link)
    if not analysis["valid"]:
        await update.message.reply_text("❌ **الرابط غير صالح**\nيجب أن يحتوي على project_id و token")
        return 1

    region = context.user_data.get('region', DEFAULT_REGION)
    
    # عرض قائمة المناطق
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"region_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="cancel")])

    await update.message.reply_text(
        f"""✅ **تم تحليل الرابط بنجاح**

**Project ID:** `{analysis['project_id']}`
**Token:** {'✅ موجود' if analysis['token'] else '❌ مفقود'}

🌍 **اختر المنطقة للنشر:**""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    context.user_data['link'] = link
    return 2

async def region_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        return ConversationHandler.END

    region = data.replace("region_", "")
    link = context.user_data.get('link')
    
    if not link:
        await query.edit_message_text("❌ الرابط مفقود، حاول مرة أخرى")
        return ConversationHandler.END

    # إضافة المهمة إلى الطابور
    loop = asyncio.get_running_loop()
    task_queue.put({
        'user_id': update.effective_user.id,
        'link': link,
        'region': region,
        'context': context,
        'loop': loop
    })

    await query.edit_message_text(
        f"✅ **تم إضافة طلبك إلى طابور التنفيذ**\n"
        f"🌍 المنطقة: {REGIONS.get(region, region)}\n"
        f"⏳ سيتم النشر خلال لحظات..."
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ لا توجد بيانات")
        return
    
    await update.message.reply_text(
        f"📋 **حالتك**\n\n"
        f"📊 عدد النشر: {user[4] or 0}\n"
        f"🔄 الحالة: {user[5] or 'idle'}\n"
        f"📝 آخر نتيجة: {user[6] or 'لا يوجد'}"
    )

async def change_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"setregion_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="back")])
    
    msg = "🌍 **اختر منطقتك الافتراضية:**"
    if query:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    region = query.data.replace("setregion_", "")
    if region == "back":
        await start(update, context)
        return
    
    user_id = query.from_user.id
    update_user(user_id, region=region)
    await query.edit_message_text(f"✅ تم تغيير المنطقة إلى {REGIONS.get(region, region)}")
    await start(update, context)

# ====================== MAIN ======================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    deploy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='^deploy$')],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lab)],
            2: [CallbackQueryHandler(region_selected, pattern='^(region_|cancel)')]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(deploy_conv)
    app.add_handler(CallbackQueryHandler(change_region, pattern='^change_region$'))
    app.add_handler(CallbackQueryHandler(set_region, pattern='^setregion_'))

    logger.info("🚀 SHADOW LEGION v200 - THE ABYSS STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()