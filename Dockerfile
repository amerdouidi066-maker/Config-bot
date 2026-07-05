FROM python:3.10-slim

WORKDIR /app

# نسخ ملف تبعيات النظام وتثبيتها
COPY apt.txt /tmp/apt.txt
RUN apt-get update && apt-get install -y $(cat /tmp/apt.txt) \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملفات بايثون وتثبيت الحزم
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح Chromium لـ Playwright مع تبعياته
RUN playwright install chromium && playwright install-deps

# نسخ كود البوت
COPY bot.py .

# تشغيل البوت (بدون منفذ، يعتمد على الـ Polling)
CMD ["python", "bot.py"]