FROM python:3.12-slim

WORKDIR /app

# تثبيت متطلبات النظام (كروم ومكتباته)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    libgl1-mesa-glx libglib2.0-0 xvfb libgbm1 libnss3 libxss1 \
    libgtk-3-0 libasound2 libxtst6 libxrandr2 libxcomposite1 \
    libxcursor1 libxdamage1 libxi6 libx11-6 libxcb1 libxfixes3 \
    libcups2 libpango-1.0-0 libatk-bridge2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملفات المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كود البوت
COPY bot.py .
COPY Procfile .

CMD ["python", "bot.py"]
