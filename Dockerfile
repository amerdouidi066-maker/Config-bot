# ===================================================================
# SHADOW LEGION v38.0 – DOCKERFILE (FIXED USER)
# ===================================================================
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# 1. الأدوات الأساسية والخطوط
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    curl \
    unzip \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 2. تثبيت Google Chrome (طريقة gpg الحديثة)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

# 3. تثبيت Chrome + تبعيات Debian 12 الضرورية
RUN apt-get update && apt-get install -y --no-install-recommends \
    google-chrome-stable \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libpixman-1-0 \
    libxtst6 \
    libx11-xcb1 \
    libxcb1 \
    libxfixes3 \
    libcups2 \
    libgdk-pixbuf-2.0-0 \
    libgtk-3-0 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# 4. تثبيت اعتماديات Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. تثبيت متصفح Playwright (تنزيل فقط)
RUN playwright install chromium

# 6. نسخ الكود ومنح الصلاحيات (باستخدام اسم مستخدم فريد)
COPY . .
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 7. التشغيل
CMD ["python", "bot.py"]