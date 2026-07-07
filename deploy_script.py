import os, subprocess, time, hashlib, re, sys

PROJECT_ID = os.environ.get("PROJECT_ID")
TOKEN = os.environ.get("TOKEN")
if not PROJECT_ID or not TOKEN:
    print("❌ PROJECT_ID أو TOKEN غير موجود")
    sys.exit(1)

REGION = os.environ.get("REGION", "us-central1")
SERVICE_NAME = f"ahmed-vip1-{int(time.time())}"
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"

def run_cmd(cmd):
    print(f"🔹 تنفيذ: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️ تحذير: {result.stderr}")
    return result.stdout.strip(), result.stderr

def log(msg): print(f"🔹 {msg}")

# ✅ الإصلاح الجوهري: تعيين المشروع قبل أي أمر
log("0. تعيين المشروع في gcloud...")
run_cmd(["gcloud", "config", "set", "project", PROJECT_ID])

log("1. تفعيل Cloud Run API...")
run_cmd(["gcloud", "services", "enable", "run.googleapis.com", f"--project={PROJECT_ID}"])
time.sleep(5)

log(f"2. نشر الخدمة '{SERVICE_NAME}'...")
cmd_deploy = [
    "gcloud", "run", "deploy", SERVICE_NAME,
    "--image", DOCKER_IMAGE,
    "--region", REGION,
    "--project", PROJECT_ID,
    "--allow-unauthenticated",
    "--quiet"
]
stdout, stderr = run_cmd(cmd_deploy)
if "ERROR" in stderr or "error" in stderr.lower():
    log(f"❌ فشل النشر: {stderr}")
    sys.exit(1)
log("✅ تم إرسال طلب النشر بنجاح.")

log("3. انتظار 30 ثانية لاستقرار الخدمة...")
time.sleep(30)

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

if not service_url:
    print("❌ فشل جلب الرابط")
    sys.exit(1)

log(f"✅ الرابط المستخرج: {service_url}")
email = os.environ.get("EMAIL", "student@qwiklabs.net")
raw = hashlib.md5(email.encode()).hexdigest()
uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
vless = f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

with open("result.txt", "w") as f:
    f.write(f"SERVICE_URL: {service_url}\n")
    f.write(f"VLESS: {vless}\n")

print("\n" + "="*70)
print(f"SERVICE_URL: {service_url}")
print(f"VLESS: {vless}")
print("="*70)