FROM python:3.11-slim

WORKDIR /app

# تثبيت حزم النظام الضرورية لـ Playwright
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# تثبيت المكتبات المطلوبة
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium && \
    playwright install-deps

# نسخ جميع ملفات المشروع
COPY . .

# متغيرات البيئة
ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"
ENV WEB_SECRET="some_random_secret"

# كشف المنافذ
EXPOSE 8080

# تشغيل البوت
CMD ["python", "bot.py"]