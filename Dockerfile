FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates curl unzip \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libxcomposite1 libxdamage1 libxrandr2 \
    libpango-1.0-0 libcairo2 libpixman-1-0 libxtst6 \
    libx11-xcb1 libxcb1 libxfixes3 libcups2 \
    libgdk-pixbuf-2.0-0 libgtk-3-0 libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium && playwright install-deps

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /ms-playwright /app

COPY . .
RUN chown -R appuser:appuser /app

USER appuser
CMD ["python", "bot.py"]