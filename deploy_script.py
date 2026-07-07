import subprocess, time, hashlib, re, json, sys, os, tempfile

# استلام البيانات من البوت
PROJECT_ID = os.environ.get("PROJECT_ID")
TOKEN = os.environ.get("TOKEN")
CREDS_JSON = os.environ.get("CREDS_JSON")  # المفتاح المستخرج من الجلسة

if not PROJECT_ID or not TOKEN or not CREDS_JSON:
    print("❌ PROJECT_ID أو TOKEN أو CREDS_JSON غير موجود")
    sys.exit(1)

# إنشاء ملف مؤقت للمفتاح
cred_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
cred_file.write(CREDS_JSON)
cred_file.close()

REGION = "us-central1"
SERVICE_NAME = f"ahmed-vip1-{int(time.time())}"
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"

def run_cmd(cmd):
    print(f"🔹 تنفيذ: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️ تحذير: {result.stderr}")
    return result.stdout.strip(), result.stderr

def log(msg): print(f"🔹 {msg}")

# 0. تفعيل الحساب الخدمي
log("0. تفعيل Service Account...")
run_cmd(["gcloud", "auth", "activate-service-account", f"--key-file={cred_file.name}", "--quiet"])
run_cmd(["gcloud", "config", "set", "project", PROJECT_ID, "--quiet"])

# 1. تفعيل API
log("1. تفعيل Cloud Run API...")
run_cmd(["gcloud", "services", "enable", "run.googleapis.com", f"--project={PROJECT_ID}"])
time.sleep(5)

# 2. نشر الخدمة
log(f"2. نشر الخدمة '{SERVICE_NAME}'...")
stdout, stderr = run_cmd([
    "gcloud", "run", "deploy", SERVICE_NAME,
    "--image", DOCKER_IMAGE,
    "--region", REGION,
    "--project", PROJECT_ID,
    "--allow-unauthenticated",
    "--quiet"
])
if "ERROR" in stderr or "error" in stderr.lower():
    log(f"❌ فشل النشر: {stderr}")
    sys.exit(1)
log("✅ تم إرسال طلب النشر بنجاح.")

# 3. انتظار استقرار الخدمة
log("3. انتظار 30 ثانية لاستقرار الخدمة...")
time.sleep(30)

# 4. جلب الرابط
log("4. جلب رابط الخدمة...")
service_url = ""
for i in range(6):
    cmd_describe = [
        "gcloud", "run", "services", "describe", SERVICE_NAME,
        "--region", REGION,
        "--project", PROJECT_ID,
        "--format", "value(status.url)"
    ]
    url, _ = run_cmd(cmd_describe)
    if url and url.startswith("http"):
        service_url = url
        break
    log(f"   المحاولة {i+1}/6: الرابط لم يظهر بعد، ننتظر 5 ثوانٍ...")
    time.sleep(5)

# 5. توليد VLESS
if service_url:
    log(f"✅ الرابط المستخرج: {service_url}")
    email = os.environ.get("EMAIL", "student-02-93b0e6f4b24d@qwiklabs.net")
    raw = hashlib.md5(email.encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    vless = f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

    # كتابة النتيجة في ملف (ليقرأها البوت)
    with open("result.txt", "w") as f:
        f.write(f"SERVICE_URL: {service_url}\n")
        f.write(f"VLESS: {vless}\n")

    print("\n" + "="*70)
    print(f"SERVICE_URL: {service_url}")
    print(f"VLESS: {vless}")
    print("="*70)
else:
    print("\n❌ فشل جلب الرابط.")