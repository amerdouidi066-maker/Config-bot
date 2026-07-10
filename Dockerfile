FROM python:3.10-slim

WORKDIR /app

# تثبيت اعتماديات النظام الضرورية لتشغيل Chromium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Google Chrome (بديل أكثر استقراراً من Chromium)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# تثبيت متطلبات Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Playwright مع Chromium (كاحتياطي)
RUN playwright install chromium
RUN playwright install-deps

# نسخ ملفات المشروع
COPY *.py ./
COPY start.sh ./
RUN chmod +x start.sh

# متغيرات البيئة
ENV TOKEN=""
ENV MONGO_URI=""
ENV WEB_PASSWORD="shadow2099"
ENV PLAYWRIGHT_BROWSERS_PATH=/app/playwright-browsers
ENV PYTHONUNBUFFERED=1

# المنفذ
EXPOSE 8080

# أمر البدء
CMD ["./start.sh"]