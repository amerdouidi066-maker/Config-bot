FROM python:3.10-slim

WORKDIR /app

# تثبيت التبعيات الأساسية (بدون apt.txt)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libdrm2 \
    libgbm1 \
    libxfixes3 \
    libxrender1 \
    libxext6 \
    libxshmfence1 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libxss1 \
    fonts-liberation \
    libappindicator3-1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# تثبيت حزم بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Chromium فقط (بدون install-deps)
RUN playwright install chromium

# نسخ كود البوت
COPY bot.py .

CMD ["python", "bot.py"]