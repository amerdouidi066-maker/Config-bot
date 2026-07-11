#!/bin/bash
set -e
echo "📦 تثبيت متصفح Chromium..."
playwright install chromium
playwright install-deps
echo "🌐 تعيين المنفذ: $PORT"
export PORT=${PORT:-8080}
echo "🚀 تشغيل خادم الويب..."
gunicorn web_dashboard:app --bind 0.0.0.0:$PORT --daemon --workers 1 --threads 2 --timeout 120
echo "🤖 تشغيل البوت..."
python bot.py