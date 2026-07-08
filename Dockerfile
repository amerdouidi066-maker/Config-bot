FROM mcr.microsoft.com/playwright:v1.40.0-focal

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

# المتغيرات الحساسة لا توضع داخل الـ Dockerfile – استخدم متغيرات البيئة في Railway
ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"
ENV WEB_SECRET="shadow_legion_secret"

EXPOSE 8080

CMD ["python3", "bot.py"]