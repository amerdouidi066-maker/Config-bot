import os, time, json
from datetime import datetime, timedelta
from flask import Flask, Response, render_template_string, jsonify, request, session, redirect, url_for
from functools import wraps
from pymongo import MongoClient
import stream_state, io
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = os.environ.get("WEB_SECRET", "shadow_legion_secret_key_2099")
PASSWORD = os.environ.get("WEB_PASSWORD", "shadow2099")
MONGO_URI = os.environ.get("MONGO_URI")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "shadow_legion")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
users_collection = db["users"]
history_collection = db["deploy_history"]
cookies_collection = db["cookies"]

def create_placeholder_frame(text="⏳ في انتظار البث..."):
    try:
        img = Image.new('RGB', (1280, 720), color=(10, 14, 20))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(((1280-w)//2, (720-h)//2), text, fill=(0, 255, 200), font=font)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return buf.getvalue()
    except Exception as e:
        print(f"خطأ في إنشاء الإطار الافتراضي: {e}")
        return None

PLACEHOLDER_FRAME = create_placeholder_frame()
if PLACEHOLDER_FRAME:
    stream_state.update_frame(PLACEHOLDER_FRAME)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Shadow Legion – Debug Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
<style>
body{background:#0b0e14;color:#e0e6ed;font-family:system-ui}.card{background:#141a24;border:1px solid #2a3546;border-radius:16px}.card-header{background:#1e2736}.stream-container{background:#000;border-radius:12px;aspect-ratio:16/9}.stream-container img{width:100%;height:100%;object-fit:contain}.log-container{height:200px;overflow-y:auto;background:#0a0d12;padding:14px 18px;font-family:monospace;white-space:pre-wrap}.log-container .error{color:#f87171}.log-container .warning{color:#fbbf24}.cookie-textarea{font-family:monospace;background:#0a0d12;color:#b0c4de;border:1px solid #2a3546;border-radius:8px;width:100%;padding:10px;height:120px}.refresh-btn{cursor:pointer}.refresh-btn:hover{transform:rotate(60deg)}
</style>
</head><body>
<div class="container-fluid py-4">
<div class="d-flex justify-content-between"><h1><i class="fas fa-shield-halved text-primary"></i> Shadow Legion <small class="text-secondary">v40.0-Debug</small></h1><div><span id="liveTime"></span> <i class="fas fa-sync-alt refresh-btn text-info" onclick="fetchAll()"></i> <a href="/logout" class="btn btn-sm btn-outline-danger">خروج</a></div></div>
<div class="row g-4"><div class="col-12"><div class="card"><div class="card-header"><i class="fas fa-video text-danger"></i> LIVE <span id="streamStatus" class="badge bg-secondary">⏸ خامل</span></div><div class="stream-container"><img id="streamImg" src="/live_stream"></div><div class="url-bar bg-dark p-2"><span>🔗 <span id="currentUrl">-</span></span></div></div></div></div>
<div class="row g-4 mt-2"><div class="col-md-3"><div class="card p-3 bg-primary-soft"><span id="totalUsers">0</span><br><small>المستخدمين</small></div></div><div class="col-md-3"><div class="card p-3 bg-success-soft"><span id="totalDeploys">0</span><br><small>النشرات</small></div></div><div class="col-md-3"><div class="card p-3 bg-warning-soft"><span id="successRate">0%</span><br><small>نسبة النجاح</small></div></div><div class="col-md-3"><div class="card p-3 bg-danger-soft"><span id="avgDuration">0s</span><br><small>متوسط المدة</small></div></div></div>
<div class="row g-4 mt-2"><div class="col-lg-8"><div class="card"><div class="card-header">آخر النشرات <span id="historyCount">0</span></div><div class="card-body p-0" style="max-height:380px;overflow-y:auto"><table class="table table-dark"><thead><tr><th>#</th><th>المنطقة</th><th>النتيجة</th><th>المدة</th><th>التوقيت</th></tr></thead><tbody id="historyBody"></tbody></table></div></div></div>
<div class="col-lg-4"><div class="card"><div class="card-header">رفع الكوكيز</div><div class="card-body"><textarea id="cookieInput" class="cookie-textarea" placeholder='[{"name":"SAPISID","value":"..."}]'></textarea><button class="btn btn-success w-100 mt-2" onclick="uploadCookies()">رفع</button><div id="cookieStatus"></div></div></div>
<div class="card mt-2"><div class="card-header">اختبار</div><div class="card-body"><button class="btn btn-outline-primary w-100" onclick="testPlaywright()">اختبار Playwright</button><div id="debugOutput" class="mt-2 p-2 bg-dark rounded" style="min-height:40px"></div></div></div></div></div>
<div class="row mt-4"><div class="col-12"><div class="card"><div class="card-header">سجل الأحداث</div><div class="card-body"><div class="log-container" id="logContainer">⏳ جاري التحميل...</div></div></div></div></div>
</div>
<script>
function fetchAll(){fetchStats();fetchHistory();fetchLogs();fetchStreamStatus();document.getElementById('liveTime').innerText=new Date().toLocaleTimeString()}
function fetchStats(){fetch('/api/stats').then(r=>r.json()).then(d=>{document.getElementById('totalUsers').innerText=d.total_users;document.getElementById('totalDeploys').innerText=d.total_deploys;document.getElementById('successRate').innerText=d.success_rate+'%';document.getElementById('avgDuration').innerText=d.avg_duration+'s'})}
function fetchHistory(){fetch('/api/history').then(r=>r.json()).then(data=>{let tbody=document.getElementById('historyBody');tbody.innerHTML='';data.forEach((row,i)=>{let status=row.success?'<span class="badge bg-success">✅</span>':'<span class="badge bg-danger">❌</span>';tbody.innerHTML+='<tr><td>'+(i+1)+'</td><td>'+(row.region_used||'N/A')+'</td><td>'+status+'</td><td>'+(row.duration_seconds||0)+'s</td><td>'+(row.deployed_at||'').slice(0,16)+'</td></tr>'});document.getElementById('historyCount').innerText=data.length})}
function fetchLogs(){fetch('/api/logs').then(r=>r.text()).then(text=>{let container=document.getElementById('logContainer');let html=text||'📭 لا توجد سجلات.';html=html.replace(/ERROR/g,'<span class="error">ERROR</span>').replace(/WARNING/g,'<span class="warning">WARNING</span>');container.innerHTML=html;container.scrollTop=container.scrollHeight})}
function fetchStreamStatus(){fetch('/api/stream_status').then(r=>r.json()).then(d=>{document.getElementById('currentUrl').innerText=d.project||'-';document.getElementById('streamStatus').innerText=d.streaming?'🔴 بث مباشر':'⏸ خامل'})}
function uploadCookies(){let raw=document.getElementById('cookieInput').value.trim();if(!raw){document.getElementById('cookieStatus').innerHTML='⚠️ الرجاء لصق الكوكيز';return}try{let cookies=JSON.parse(raw);if(!Array.isArray(cookies))throw new Error('يجب أن يكون مصفوفة');document.getElementById('cookieStatus').innerHTML='⏳ جاري الرفع...';fetch('/api/upload_cookies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookies:cookies})}).then(r=>r.json()).then(d=>{document.getElementById('cookieStatus').innerHTML='✅ '+d.message;document.getElementById('cookieInput').value=''}).catch(e=>{document.getElementById('cookieStatus').innerHTML='❌ فشل: '+e.message})}catch(e){document.getElementById('cookieStatus').innerHTML='❌ خطأ في JSON: '+e.message}}
function testPlaywright(){document.getElementById('debugOutput').innerHTML='⏳ جاري الاختبار...';fetch('/api/test_playwright').then(r=>r.json()).then(d=>{document.getElementById('debugOutput').innerHTML=d.status==='ok'?'✅ '+d.message:'❌ '+d.message})}
fetchAll();setInterval(fetchLogs,4000);setInterval(fetchStats,10000);setInterval(fetchHistory,15000);setInterval(fetchStreamStatus,2000);setInterval(()=>{let img=document.getElementById('streamImg');if(img)img.src='/live_stream?t='+Date.now()},2000)
</script>
</body></html>
'''

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def generate_frames():
    while True:
        frame = stream_state.get_last_frame()
        if frame:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
        else:
            if PLACEHOLDER_FRAME:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(PLACEHOLDER_FRAME)).encode() + b'\r\n\r\n' + PLACEHOLDER_FRAME + b'\r\n')
            else:
                time.sleep(0.05)
                continue
        time.sleep(0.02)

@app.route('/')
@login_required
def index():
    return render_template_string(HTML_TEMPLATE, now=datetime.now().strftime("%H:%M:%S"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('pass') == PASSWORD:
        session['logged_in'] = True
        return redirect(url_for('index'))
    return '''
    <div style="max-width:400px;margin:100px auto;background:#141a24;padding:40px;border-radius:16px;border:1px solid #2a3546;">
        <h3 class="text-light">🔐 دخول</h3>
        <form method="post">
            <input type="password" name="pass" placeholder="كلمة المرور" class="form-control bg-dark text-light my-3" style="border:1px solid #2a3546;">
            <button class="btn btn-primary w-100" type="submit">دخول</button>
        </form>
    </div>
    '''

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/live_stream')
@login_required
def live_stream():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/stream_status')
@login_required
def api_stream_status():
    s = stream_state.get_status()
    return jsonify({
        "streaming": s.get("streaming", False),
        "project": s.get("project", "-"),
        "duration": s.get("duration", "00:00:00")
    })

@app.route('/api/stats')
@login_required
def api_stats():
    total_users = users_collection.count_documents({})
    total_deploys = history_collection.count_documents({})
    success_count = history_collection.count_documents({"success": 1})
    rate = round((success_count / total_deploys * 100) if total_deploys > 0 else 0, 1)
    pipeline = [{"$match": {"success": 1}}, {"$group": {"_id": None, "avg": {"$avg": "$duration_seconds"}}}]
    avg_result = list(history_collection.aggregate(pipeline))
    avg = avg_result[0]["avg"] if avg_result else 0
    return jsonify({"total_users": total_users, "total_deploys": total_deploys, "success_rate": rate, "avg_duration": round(avg, 1)})

@app.route('/api/history')
@login_required
def api_history():
    docs = history_collection.find({}, sort=[("deployed_at", -1)], limit=20)
    result = [{"region_used": d.get("region_used"), "success": d.get("success", 0), "duration_seconds": d.get("duration_seconds", 0), "deployed_at": d.get("deployed_at", "")} for d in docs]
    return jsonify(result)

@app.route('/api/upload_cookies', methods=['POST'])
@login_required
def api_upload_cookies():
    try:
        data = request.get_json()
        cookies = data.get('cookies')
        if not cookies or not isinstance(cookies, list):
            return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
        user_id = session.get('user_id', 0)
        cookies_collection.update_one({"_id": user_id}, {"$set": {"data": json.dumps(cookies, default=str), "updated_at": datetime.now().isoformat()}}, upsert=True)
        return jsonify({"status": "success", "message": f"تم حفظ {len(cookies)} كوكي بنجاح"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logs')
@login_required
def api_logs():
    try:
        with open("bot.log", "r") as f:
            return "\n".join(f.readlines()[-150:]) or "📭 السجل فارغ."
    except:
        return "⚠️ ملف السجل غير موجود."

@app.route('/api/test_playwright')
@login_required
def api_test_playwright():
    import asyncio
    try:
        from playwright.async_api import async_playwright
        async def test():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = await browser.new_page()
                await page.goto("https://www.google.com")
                title = await page.title()
                await browser.close()
                return f"✅ Playwright يعمل. Title: {title[:30]}"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(test())
        return jsonify({"status": "ok", "message": result})
    except Exception as e:
        return jsonify({"status": "error", "message": f"❌ فشل: {str(e)}"})

def run_web_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)