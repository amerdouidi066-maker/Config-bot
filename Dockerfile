# ===================================================================
# SHADOW LEGION v38.0 – DOCKERFILE (FINAL_ARCHITECT_EDITION)
# ===================================================================
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1. الأساسيات والخطوط
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    curl \
    unzip \
    fonts-liberation \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-tlwg-loma-otf \
    && rm -rf /var/lib/apt/lists/*

# 2. مفتاح Google Chrome (طريقة gpg الحديثة)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

# 3. تثبيت Chrome + تبعيات Debian 12 (بدون libpng6 أو libjpeg-turbo8 القديمة)
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

# 5. تثبيت متصفح Playwright (بدون install-deps)
RUN playwright install chromium

# 6. نسخ الكود ومنح الصلاحيات
COPY . .
RUN useradd -m -u 1000 shadow && chown -R shadow:shadow /app
USER shadow

# 7. التشغيل
CMD ["python", "bot.py"]