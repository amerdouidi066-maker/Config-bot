# ===================================================================
# SHADOW LEGION v38.0 – DOCKERFILE (ARCHITECT_EDITION)
# ===================================================================
# القاعدة: Debian 12 (Bookworm) + Python 3.10
FROM python:3.10-slim AS builder

# تعيين متغيرات البيئة الأساسية (غير حساسة)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# ===================================================================
# 1. تحديث الحزم وتثبيت الأدوات الأساسية
# ===================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ===================================================================
# 2. تثبيت Google Chrome بالطريقة الحديثة (بدون apt-key)
# ===================================================================
# تحميل المفتاح وتحويله إلى تنسيق gpg
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg

# إضافة المستودع مع التوقيع
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

# ===================================================================
# 3. تثبيت Chrome + تبعيات Playwright الأساسية
# ===================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    google-chrome-stable \
    # تبعيات Playwright (Chromium Headless)
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm-dev \
    libpango-1.0-0 \
    libcairo2 \
    libpixman-1-0 \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# ===================================================================
# 4. تثبيت الاعتماديات البرمجية (Python)
# ===================================================================
COPY requirements.txt .

# تثبيت Playwright أولاً لتجنب تعارض الإصدارات
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ===================================================================
# 5. تثبيت متصفحات Playwright (مدمجة) مع تبعياتها
# ===================================================================
RUN playwright install chromium && \
    playwright install-deps

# ===================================================================
# 6. نسخ الكود المصدري
# ===================================================================
COPY . .

# ===================================================================
# 7. (اختياري) مستخدم غير جذري لتشغيل آمن
# ===================================================================
RUN useradd -m -u 1000 shadow && chown -R shadow:shadow /app
USER shadow

# ===================================================================
# 8. أمر التشغيل
# ===================================================================
CMD ["python", "bot.py"]