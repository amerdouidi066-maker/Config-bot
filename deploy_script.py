import os, subprocess, time, hashlib, re, json, sys

PROJECT_ID = os.environ.get("PROJECT_ID")
TOKEN = os.environ.get("TOKEN")
if not PROJECT_ID or not TOKEN:
    print("❌ PROJECT_ID أو TOKEN غير موجود")
    sys.exit(1)

REGION = "us-central1"
SERVICE_NAME = f"vip-{int(time.time())}"
DOCKER_IMAGE = "docker.io/ajndjd2/ahmed-vip1"

def run_cmd(cmd):
    print(f"🔹 تنفيذ: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️ تحذير: {result.stderr}")
    return result.stdout.strip(), result.stderr

def build_vless(service_url):
    host = service_url.replace('https://', '').replace('http://', '').split('/')[0]
    raw = hashlib.md5(("cloudshell_" + str(int(time.time()))).encode()).hexdigest()
    uid = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return f"vless://{uid}@{host}:443?path=%2FTelegram%2F%40AM2_D3%2F%40AHMAD3214&security=tls&encryption=none&host={host}&type=ws&sni={host}#CloudRun"

# 1. تسجيل الدخول باستخدام التوكن (معرف مسبقاً في Cloud Shell)
print("🔹 1. تفعيل Cloud Run API...")
run_cmd(["gcloud", "services", "enable", "run.googleapis.com", f"--project={PROJECT_ID}"])
time.sleep(5)

# 2. نشر الخدمة
print(f"🔹 2. نشر الخدمة '{SERVICE_NAME}'...")
stdout, stderr = run_cmd([
    "gcloud", "run", "deploy", SERVICE_NAME,
    "--image", DOCKER_IMAGE,
    "--region", REGION,
    "--platform", "managed",
    "--port", "8080",
    "--allow-unauthenticated",
    "--project", PROJECT_ID,
    "--quiet"
])
output = stdout + stderr
if "ERROR" in stderr or "error" in stderr.lower():
    print(f"❌ فشل النشر: {stderr}")
    sys.exit(1)

# 3. استخراج الرابط
service_url = ""
match = re.search(r'https://[a-zA-Z0-9\-]+\.run\.app', output)
if match:
    service_url = match.group(0)
else:
    print("🔹 3. محاولة استخراج الرابط عبر describe...")
    for i in range(6):
        time.sleep(5)
        url, _ = run_cmd([
            "gcloud", "run", "services", "describe", SERVICE_NAME,
            "--region", REGION,
            "--project", PROJECT_ID,
            "--format", "value(status.url)"
        ])
        if url and url.startswith("http"):
            service_url = url
            break

if not service_url:
    print("❌ لم أجد الرابط")
    sys.exit(1)

vless = build_vless(service_url)
print("\n" + "="*70)
print(f"✅ SERVICE_URL: {service_url}")
print(f"✅ VLESS: {vless}")
print("="*70)
