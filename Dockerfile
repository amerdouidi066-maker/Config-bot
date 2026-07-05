FROM python:3.10-slim

WORKDIR /app

# تثبيت تبعيات النظام من apt.txt
COPY apt.txt /tmp/apt.txt
RUN apt-get update && apt-get install -y $(cat /tmp/apt.txt) \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# تثبيت حزم بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح Chromium
RUN playwright install chromium

# نسخ الكود
COPY bot.py .

CMD ["python", "bot.py"]