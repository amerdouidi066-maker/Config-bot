# web_dashboard.py
import os
import time
from datetime import datetime, timedelta
from flask import Flask, Response, render_template_string, jsonify, request, session, redirect, url_for
from functools import wraps
from pymongo import MongoClient
import stream_state
import io
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

def create_placeholder_frame(text="⏳ في انتظار البث..."):
    try:
        img = Image.new('RGB', (1280, 720), color=(10, 14, 20))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(((1280-w)//2, (720-h)//2), text, fill=(0, 255, 200), font=font)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80)
        return buf.getvalue()
    except:
        return None

PLACEHOLDER_FRAME = create_placeholder_frame()
if PLACEHOLDER_FRAME:
    stream_state.update_frame(PLACEHOLDER_FRAME)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html dir="ltr" lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Shadow Legion – Live Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body { background: #0b0e14; color: #e0e6ed; font-family: system-ui, -apple-system, 'Tahoma', 'Segoe UI', Roboto, sans-serif; }
        .card { background: #141a24; border: 1px solid #2a3546; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.6); }
        .card-header { background: #1e2736; border-bottom: 1px solid #2a3546; font-weight: 600; }
        .stat-icon { font-size: 2.5rem; opacity: 0.7; }
        .bg-success-soft { background: #0f2b1a; color: #5be08b; }
        .bg-danger-soft { background: #2b1218; color: #f87171; }
        .bg-primary-soft { background: #122238; color: #60a5fa; }
        .bg-warning-soft { background: #2b2412; color: #fbbf24; }
        .stream-container {
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            aspect-ratio: 16/9;
            border: 1px solid #2a3546;
            position: relative;
        }
        .stream-container img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }
        .stream-overlay {
            position: absolute;
            bottom: 12px;
            left: 12px;
            right: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0,0,0,0.7);
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid #2a354688;
            font-size: 11px;
            flex-wrap: wrap;
            gap: 6px;
            font-family: 'Courier New', monospace;
        }
        .stream-overlay .info-item { color: #aac; }
        .stream-overlay .info-value { color: #0ff; font-weight: bold; }
        .log-container { height: 200px; overflow-y: auto; background: #0a0d12; border-radius: 12px; padding: 12px; font-size: 13px; font-family: 'Courier New', monospace; white-space: pre-wrap; word-break: break-all; }
        .log-container::-webkit-scrollbar { width: 6px; }
        .log-container::-webkit-scrollbar-thumb { background: #2a3546; border-radius: 8px; }
        .table-dark { background: transparent; }
        .table-dark td, .table-dark th { border-color: #1e2736; }
        .refresh-btn { cursor: pointer; transition: 0.3s; }
        .refresh-btn:hover { transform: rotate(60deg); }
        .live-badge { animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
        .status-badge { display: inline-block; padding: 2px 12px; border-radius: 20px; font-size: 11px; font-weight: bold; }
        .status-badge.running { background: #00ffcc22; color: #00ffcc; border: 1px solid #00ffcc55; }
        .status-badge.idle { background: #4444; color: #888; border: 1px solid #4444; }
    </style>
</head>
<body>
<div class="container-fluid py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1><i class="fas fa-shield-halved text-primary me-2"></i>Shadow Legion <small class="text-secondary fs-6">v28.0 – Recorder</small></h1>
        <div>
            <span class="badge bg-secondary me-2" id="liveTime">{{ now }}</span>
            <i class="fas fa-sync-alt refresh-btn text-info" onclick="fetchAll()"></i>
            <a href="/logout" class="btn btn-sm btn-outline-danger ms-3"><i class="fas fa-sign-out-alt"></i> خروج</a>
        </div>
    </div>

    <div class="row g-4 mb-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><i class="fas fa-video text-danger me-2 live-badge"></i> <span class="text-danger fw-bold">LIVE</span> البث المباشر</span>
                    <span>
                        <span id="streamStatus" class="status-badge idle">⏸ خامل</span>
                        <span class="badge bg-dark ms-2" id="streamDuration">00:00:00</span>
                    </span>
                </div>
                <div class="card-body p-0">
                    <div class="stream-container">
                        <img id="streamImg" src="/live_stream" alt="البث المباشر">
                        <div class="stream-overlay">
                            <div><span class="info-item">📌</span> <span id="overlayProject" class="info-value">-</span></div>
                            <div><span class="info-item">🌍</span> <span id="overlayRegion" class="info-value">-</span></div>
                            <div><span class="info-item">🍪</span> <span id="overlayCookies" class="info-value">-</span></div>
                            <div><span class="info-item">🔑</span> <span id="overlayToken" class="info-value">-</span></div>
                            <div><span class="info-item">📧</span> <span id="overlayEmail" class="info-value">-</span></div>
                            <div><span id="overlayAction" style="color:#ffcc00;font-weight:bold;">في انتظار البث</span></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="row g-4 mb-4" id="statsCards">
        <div class="col-md-3"><div class="card p-3 bg-primary-soft"><div class="d-flex justify-content-between"><div><i class="fas fa-users stat-icon"></i></div><div class="text-end"><span class="fs-3 fw-bold" id="totalUsers">0</span><br><small>المستخدمين</small></div></div></div></div>
        <div class="col-md-3"><div class="card p-3 bg-success-soft"><div class="d-flex justify-content-between"><div><i class="fas fa-rocket stat-icon"></i></div><div class="text-end"><span class="fs-3 fw-bold" id="totalDeploys">0</span><br><small>إجمالي النشرات</small></div></div></div></div>
        <div class="col-md-3"><div class="card p-3 bg-warning-soft"><div class="d-flex justify-content-between"><div><i class="fas fa-percent stat-icon"></i></div><div class="text-end"><span class="fs-3 fw-bold" id="successRate">0%</span><br><small>نسبة النجاح</small></div></div></div></div>
        <div class="col-md-3"><div class="card p-3 bg-danger-soft"><div class="d-flex justify-content-between"><div><i class="fas fa-clock stat-icon"></i></div><div class="text-end"><span class="fs-3 fw-bold" id="avgDuration">0s</span><br><small>متوسط المدة</small></div></div></div></div>
    </div>

    <div class="row g-4">
        <div class="col-lg-8">
            <div class="card">
                <div class="card-header d-flex justify-content-between"><span><i class="fas fa-list-ul me-2"></i>آخر النشرات</span><span class="badge bg-dark" id="historyCount">0</span></div>
                <div class="card-body p-0" style="max-height: 380px; overflow-y: auto;">
                    <table class="table table-dark table-hover mb-0">
                        <thead><tr><th>#</th><th>المنطقة</th><th>النتيجة</th><th>المدة</th><th>التوقيت</th><th>الرابط</th></tr></thead>
                        <tbody id="historyBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
        <div class="col-lg-4">
            <div class="card">
                <div class="card-header"><i class="fas fa-screwdriver-wrench me-2"></i>لوحة التصحيح</div>
                <div class="card-body">
                    <button class="btn btn-outline-primary w-100 mb-2" onclick="testPlaywright()"><i class="fas fa-play me-2"></i>اختبار Playwright</button>
                    <button class="btn btn-outline-warning w-100 mb-2" onclick="clearCache()"><i class="fas fa-eraser me-2"></i>تنظيف السجل</button>
                    <div class="mt-3 p-2 bg-dark rounded" id="debugOutput" style="font-size:12px; min-height:60px;">🟢 النظام جاهز</div>
                </div>
            </div>
        </div>
    </div>

    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header"><span><i class="fas fa-terminal me-2"></i>سجل الأحداث</span></div>
                <div class="card-body"><div class="log-container" id="logContainer">⏳ جاري التحميل...</div></div>
            </div>
        </div>
    </div>
</div>

<script>
    const BASE = '';
    let logInterval;

    function fetchStats() {
        fetch(BASE + '/api/stats').then(r => r.json()).then(d => {
            document.getElementById('totalUsers').innerText = d.total_users;
            document.getElementById('totalDeploys').innerText = d.total_deploys;
            document.getElementById('successRate').innerText = d.success_rate + '%';
            document.getElementById('avgDuration').innerText = d.avg_duration + 's';
        }).catch(e => console.error(e));
    }

    function fetchHistory() {
        fetch(BASE + '/api/history').then(r => r.json()).then(data => {
            const tbody = document.getElementById('historyBody');
            tbody.innerHTML = '';
            data.forEach((row, i) => {
                const status = row.success ? '<span class="badge badge-success">✅ نجاح</span>' : '<span class="badge badge-danger">❌ فشل</span>';
                const link = row.vless_link ? `<a href="${row.vless_link}" target="_blank" class="text-info small">🔗</a>` : '-';
                tbody.innerHTML += `<tr><td>${i+1}</td><td>${row.region_used || 'N/A'}</td><td>${status}</td><td>${row.duration_seconds || 0}s</td><td>${row.deployed_at.slice(0,16)}</td><td>${link}</td></tr>`;
            });
            document.getElementById('historyCount').innerText = data.length;
        });
    }

    function fetchLogs() {
        fetch(BASE + '/api/logs').then(r => r.text()).then(text => {
            const container = document.getElementById('logContainer');
            container.innerText = text || '📭 لا توجد سجلات.';
            container.scrollTop = container.scrollHeight;
        });
    }

    function fetchStreamStatus() {
        fetch(BASE + '/api/stream_status').then(r => r.json()).then(d => {
            const badge = document.getElementById('streamStatus');
            if (d.streaming) { badge.textContent = '🔴 بث مباشر'; badge.className = 'status-badge running'; }
            else { badge.textContent = '⏸ خامل'; badge.className = 'status-badge idle'; }
            document.getElementById('overlayProject').textContent = d.project || '-';
            document.getElementById('overlayRegion').textContent = d.region || '-';
            document.getElementById('overlayCookies').textContent = d.cookies || '-';
            document.getElementById('overlayToken').textContent = d.token || '-';
            document.getElementById('overlayEmail').textContent = d.email || '-';
            document.getElementById('overlayAction').textContent = d.action || 'في انتظار البث';
            document.getElementById('streamDuration').textContent = d.duration || '00:00:00';
        }).catch(() => {});
    }

    function fetchAll() { fetchStats(); fetchHistory(); fetchLogs(); fetchStreamStatus(); document.getElementById('liveTime').innerText = new Date().toLocaleTimeString(); }

    function testPlaywright() {
        document.getElementById('debugOutput').innerHTML = '⏳ جاري الاختبار...';
        fetch(BASE + '/api/test_playwright').then(r => r.json()).then(d => {
            document.getElementById('debugOutput').innerHTML = d.status === 'ok' ? '✅ ' + d.message : '❌ ' + d.message;
        });
    }

    function clearCache() {
        if(!confirm('⚠️ حذف السجلات الأقدم من 30 يوم؟')) return;
        fetch(BASE + '/api/clear_old_history', {method: 'POST'}).then(r => r.json()).then(d => {
            document.getElementById('debugOutput').innerHTML = '🗑️ ' + d.message;
            fetchHistory(); fetchStats();
        });
    }

    fetchAll();
    setInterval(fetchLogs, 3000);
    setInterval(fetchStats, 10000);
    setInterval(fetchHistory, 15000);
    setInterval(fetchStreamStatus, 2000);
    setInterval(() => { const img = document.getElementById('streamImg'); if (img) img.src = '/live_stream?t=' + Date.now(); }, 2000);
</script>
</body>
</html>
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
                time.sleep(0.1)
                continue
        time.sleep(0.05)

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
        "region": s.get("region", "-"),
        "cookies": s.get("cookies", 0),
        "token": s.get("token", "-"),
        "email": s.get("email", "-"),
        "action": s.get("action", "في انتظار البث"),
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
    return jsonify({
        "total_users": total_users,
        "total_deploys": total_deploys,
        "success_rate": rate,
        "avg_duration": round(avg, 1)
    })

@app.route('/api/history')
@login_required
def api_history():
    docs = history_collection.find({}, sort=[("deployed_at", -1)], limit=20)
    result = []
    for doc in docs:
        result.append({
            "region_used": doc.get("region_used"),
            "success": doc.get("success", 0),
            "duration_seconds": doc.get("duration_seconds", 0),
            "deployed_at": doc.get("deployed_at", ""),
            "vless_link": doc.get("vless_link", "")
        })
    return jsonify(result)

@app.route('/api/logs')
@login_required
def api_logs():
    try:
        with open("bot.log", "r") as f:
            lines = f.readlines()
            return "\n".join(lines[-100:]) or "📭 السجل فارغ."
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

@app.route('/api/clear_old_history', methods=['POST'])
@login_required
def api_clear_old():
    cutoff = datetime.now() - timedelta(days=30)
    result = history_collection.delete_many({"deployed_at": {"$lt": cutoff.isoformat()}})
    return jsonify({"message": f"تم حذف {result.deleted_count} سجل قديم."})

def run_web_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)