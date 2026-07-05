FROM python:3.10-slim

WORKDIR /app

# تثبيت حزم أساسية فقط (curl، wget، unzip، ca-certificates)
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    ca-certificates \
    fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# تثبيت حزم بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Chromium مع تبعياته (playwright install-deps ستدير كل شيء)
RUN playwright install chromium && playwright install-deps

# نسخ كود البوت
COPY bot.py .

CMD ["python", "bot.py"]