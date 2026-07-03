FROM python:3.12-slim

WORKDIR /app

# تثبيت المتطلبات الأساسية وإضافة مستودع كروم بطريقة حديثة
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    unzip \
    xvfb \
    libgbm1 \
    libnss3 \
    libxss1 \
    libasound2 \
    libxtst6 \
    libxrandr2 \
    libxcursor1 \
    libxcomposite1 \
    libxi6 \
    libx11-6 \
    libxcb1 \
    libxfixes3 \
    libcups2 \
    libpango-1.0-0 \
    libatk-bridge2.0-0 \
    --no-install-recommends \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/google-chrome-archive-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات وتثبيت مكتبات بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملف البوت
COPY bot.py .

# تشغيل البوت
CMD ["python", "bot.py"]