FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libnss3 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
    libxi6 libxtst6 libxrandr2 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    libgbm1 libxshmfence1 fonts-liberation libappindicator3-1 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY . .

ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"
ENV WEB_SECRET="shadow_legion_secret"
ENV CLEANUP_DAYS="7"
ENV TWOCAPTCHA_API_KEY=""
ENV PROXY_LIST=""

EXPOSE 8080

CMD ["python3", "bot.py"]