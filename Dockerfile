FROM mcr.microsoft.com/playwright/python:v1.44.0-focal

WORKDIR /app

# تثبيت التبعيات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح Chromium مع جميع التبعيات
RUN playwright install chromium && playwright install-deps

# نسخ ملفات البوت
COPY bot.py .
COPY deploy_script.py .

# تشغيل البوت
CMD ["python3", "bot.py"]