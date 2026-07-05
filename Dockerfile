# استخدام صورة Playwright الرسمية (جاهزة بكل التبعيات)
FROM mcr.microsoft.com/playwright:python-1.40.0

WORKDIR /app

# نسخ ملف المتطلبات وتثبيت حزم بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كود البوت
COPY bot.py .

# تشغيل البوت
CMD ["python", "bot.py"]