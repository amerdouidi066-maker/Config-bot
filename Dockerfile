# ===================================================================
# SHADOW LEGION v38.0 – DOCKERFILE (OFFICIAL PLAYWRIGHT IMAGE)
# ===================================================================
FROM mcr.microsoft.com/playwright:python-3.10

# متغيرات البيئة الأساسية
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# نسخ ملفات الاعتماديات
COPY requirements.txt .

# تثبيت حزم Python (لا حاجة لتثبيت Playwright لأنه مثبت مسبقاً)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# نسخ الكود المصدري
COPY . .

# إنشاء مستخدم غير جذري (اختياري)
RUN useradd -m -u 1000 shadow && chown -R shadow:shadow /app
USER shadow

# التشغيل
CMD ["python", "bot.py"]