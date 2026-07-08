FROM mcr.microsoft.com/playwright/python:v1.44.0-focal

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفحات Playwright مع الدعم الكامل
RUN playwright install chromium

COPY bot.py .
COPY deploy_script.py .

CMD ["python3", "bot.py"]