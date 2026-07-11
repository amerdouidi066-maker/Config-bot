#!/bin/bash
set -e
echo "📦 تثبيت متصفح Chromium..."
playwright install chromium
playwright install-deps
echo "🌐 تعيين المنفذ: $PORT"
export PORT=${PORT:-8080}
echo "🤖 تشغيل البوت (سيبدأ خادم الويب داخلياً)..."
python bot.py