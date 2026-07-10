#!/bin/bash
set -e

echo "📦 تثبيت متصفح Chromium..."
playwright install chromium
playwright install-deps

echo "📦 تثبيت اعتماديات النظام..."
apt-get update && apt-get install -y fonts-dejavu-core

echo "🌐 تعيين المنفذ: $PORT"
export PORT=${PORT:-8080}

echo "🚀 تشغيل خادم الويب مع gunicorn..."
gunicorn web_dashboard:app --bind 0.0.0.0:$PORT --daemon --workers 1 --threads 2

echo "🤖 تشغيل البوت..."
python bot.py
