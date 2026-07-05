# ⚠️ هذا هو الاسم الصحيح الوحيد الذي يعمل - لا تغيره ⚠️
FROM mcr.microsoft.com/playwright:python-1.40.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python", "main.py"]