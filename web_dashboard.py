# web_dashboard.py
import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("WEB_SECRET", "shadow_legion_secret_key_2099")
DB_PATH = os.environ.get("DB_PATH", "shadow_legion.db")
PASSWORD = os.environ.get("WEB_PASSWORD", "shadow2099")

# ============ HTML قالب متكامل (مع Bootstrap + JS) ============
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html dir="ltr" lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Shadow Legion – Control Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body { background: #0b0e14; color: #e0e6ed; font-family: 'Segoe UI', monospace; }
        .card { background: #141a24; border: 1px solid #2a3546; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.6); }
        .card-header { background: #1e2736; border-bottom: 1px solid #2a3546; font-weight: 600; }
        .stat-icon { font-size: 2.5rem; opacity: 0.7; }
        .bg-success-soft { background: #0f2b1a; color: #5be08b; }
        .bg-danger-soft { background: #2b1218; color: #f87171; }
        .bg-primary-soft { background: #122238; color: #60a5fa; }
        .bg-warning-soft { background: #2b2412; color: #fbbf24; }
        .log-container { height: 400px; overflow-y: auto; background: #0a0d12; border-radius: 12px; padding: 12px; font-size: 13px; font-family: 'Courier New', monospace; white-space: pre-wrap; word-break: break-all; }
        .log-container::-webkit-scrollbar { width: 6px; }
        .log-container::-webkit-scrollbar-thumb { background: #2a3546; border-radius: 8px; }
        .table-dark { background: transparent; }
        .table-dark td, .table-dark th { border-color: #1e2736; }
        .btn-outline-telegram { border-color: #2a7de1; color: #2a7de1; }
        .btn-outline-telegram:hover { background: #2a7de1; color: #fff; }
        .badge-success { background: #2d7a4a; }
        .badge-danger { background: #7a2d3a; }
        .refresh-btn { cursor: pointer; transition: 0.3s; }
        .refresh-btn:hover { transform: rotate(60deg); }
    </style>
</head>
<body>
<div class="container-fluid py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1><i class="fas fa-shield-halved text-primary me-2"></i>Shadow Legion <small class="text-secondary fs-6">v15.5 – Enterprise</small></h1>
        <div>
            <span class="badge bg-secondary me-2" id="liveTime">{{ now }}</span>
            <i class="fas fa-sync-alt refresh-btn text-info" onclick="fetchAll()" title="تحديث يدوي"></i>
            <a href="/logout" class="btn btn-sm btn-outline-danger ms-3"><i class="fas fa-sign-out-alt"></i> خروج</a>
        </div>
    </div>

    <!-- Stats Cards -->
    <div class="row g-4 mb-4" id="statsCards">
        <div class="col-md-3">
            <div class="card p-3 bg-primary-soft">
                <div class="d-flex justify-content-between">
                    <div><i class="fas fa-users stat-icon"></i></div>
                    <div class="text-end"><span class="fs-3 fw-bold" id="totalUsers">0</span><br><small>المستخدمين</small></div>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-success-soft">
                <div class="d-flex justify-content-between">
                    <div><i class="fas fa-rocket stat-icon"></i></div>
                    <div class="text-end"><span class="fs-3 fw-bold" id="totalDeploys">0</span><br><small>إجمالي النشرات</small></div>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-warning-soft">
                <div class="d-flex justify-content-between">
                    <div><i class="fas fa-percent stat-icon"></i></div>
                    <div class="text-end"><span class="fs-3 fw-bold" id="successRate">0%</span><br><small>نسبة النجاح</small></div>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-danger-soft">
                <div class="d-flex justify-content-between">
                    <div><i class="fas fa-clock stat-icon"></i></div>
                    <div class="text-end"><span class="fs-3 fw-bold" id="avgDuration">0s</span><br><small>متوسط المدة</small></div>
                </div>
            </div>
        </div>
    </div>

    <div class="row g-4">
        <!-- History Table -->
        <div class="col-lg-8">
            <div class="card">
                <div class="card-header d-flex justify-content-between">
                    <span><i class="fas fa-list-ul me-2"></i>آخر النشرات</span>
                    <span class="badge bg-dark" id="historyCount">0</span>
                </div>
                <div class="card-body p-0" style="max-height: 420px; overflow-y: auto;">
                    <table class="table table-dark table-hover mb-0">
                        <thead><tr><th>#</th><th>المنطقة</th><th>النتيجة</th><th>المدة</th><th>التوقيت</th><th>الرابط</th></tr></thead>
                        <tbody id="historyBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
        <!-- Quick Debug -->
        <div class="col-lg-4">
            <div class="card">
                <div class="card-header"><i class="fas fa-screwdriver-wrench me-2"></i>لوحة التصحيح</div>
                <div class="card-body">
                    <button class="btn btn-outline-primary w-100 mb-2" onclick="testPlaywright()"><i class="fas fa-play me-2"></i>اختبار Playwright</button>
                    <button class="btn btn-outline-warning w-100 mb-2" onclick="clearCache()"><i class="fas fa-eraser me-2"></i>تنظيف قاعدة البيانات (احتراسي)</button>
                    <div class="mt-3 p-2 bg-dark rounded" id="debugOutput" style="font-size:12px; min-height:60px;">🟢 النظام جاهز</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Live Logs -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header d-flex justify-content-between">
                    <span><i class="fas fa-terminal me-2"></i>سجل الأحداث المباشر (Live Logs)</span>
                    <span><span class="badge bg-dark" id="logAutoRefresh">تحديث تلقائي</span></span>
                </div>
                <div class="card-body">
                    <div class="log-container" id="logContainer">⏳ جاري تحميل السجلات...</div>
                </div>
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
                tbody.innerHTML += `<tr>
                    <td>${i+1}</td>
                    <td>${row.region_used || 'N/A'}</td>
                    <td>${status}</td>
                    <td>${row.duration_seconds || 0}s</td>
                    <td>${row.deployed_at.slice(0,16)}</td>
                    <td>${link}</td>
                </tr>`;
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

    function fetchAll() {
        fetchStats();
        fetchHistory();
        fetchLogs();
        document.getElementById('liveTime').innerText = new Date().toLocaleTimeString();
    }

    // Debug Actions
    function testPlaywright() {
        document.getElementById('debugOutput').innerHTML = '⏳ جاري اختبار متصفح Chromium...';
        fetch(BASE + '/api/test_playwright').then(r => r.json()).then(d => {
            document.getElementById('debugOutput').innerHTML = d.status === 'ok' ? 
                '✅ ' + d.message : '❌ ' + d.message;
        });
    }

    function clearCache() {
        if(!confirm('⚠️ هل أنت متأكد من حذف سجل النشرات القديمة (آخر 30 يوم)؟')) return;
        fetch(BASE + '/api/clear_old_history', {method: 'POST'}).then(r => r.json()).then(d => {
            document.getElementById('debugOutput').innerHTML = '🗑️ ' + d.message;
            fetchHistory();
            fetchStats();
        });
    }

    // Auto-refresh every 5 seconds
    fetchAll();
    logInterval = setInterval(fetchLogs, 4000);
    setInterval(fetchStats, 10000);
    setInterval(fetchHistory, 15000);
</script>
</body>
</html>
'''

# ============ دوال المساعدة للـ API ============
def get_db_connection():
    return sqlite3.connect(DB_PATH)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

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
        <h3 class="text-light">🔐 دخول لوحة التحكم</h3>
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

# ============ API Endpoints ============
@app.route('/api/stats')
@login_required
def api_stats():
    conn = get_db_connection()
    c = conn.cursor()
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_deploys = c.execute("SELECT COUNT(*) FROM deploy_history").fetchone()[0]
    success = c.execute("SELECT COUNT(*) FROM deploy_history WHERE success=1").fetchone()[0]
    rate = round((success / total_deploys * 100) if total_deploys > 0 else 0, 1)
    avg = c.execute("SELECT AVG(duration_seconds) FROM deploy_history WHERE success=1").fetchone()[0] or 0
    conn.close()
    return jsonify({
        "total_users": total_users,
        "total_deploys": total_deploys,
        "success_rate": rate,
        "avg_duration": round(avg, 1)
    })

@app.route('/api/history')
@login_required
def api_history():
    conn = get_db_connection()
    c = conn.cursor()
    rows = c.execute("""
        SELECT region_used, success, duration_seconds, deployed_at, vless_link
        FROM deploy_history ORDER BY deployed_at DESC LIMIT 20
    """).fetchall()
    conn.close()
    return jsonify([{
        "region_used": r[0], "success": bool(r[1]),
        "duration_seconds": r[2], "deployed_at": r[3], "vless_link": r[4]
    } for r in rows])

@app.route('/api/logs')
@login_required
def api_logs():
    try:
        with open("bot.log", "r") as f:
            lines = f.readlines()
            return "\n".join(lines[-100:]) or "📭 السجل فارغ."
    except:
        return "⚠️ ملف السجل غير موجود (bot.log). تأكد من تفعيل التسجيل."

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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM deploy_history WHERE deployed_at < datetime('now', '-30 days')")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return jsonify({"message": f"تم حذف {deleted} سجل قديم."})

# ============ تشغيل الخادم ============
def run_web_server(port=8080):
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
