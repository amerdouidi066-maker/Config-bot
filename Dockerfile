FROM mcr.microsoft.com/playwright:v1.40.0-focal

WORKDIR /app

# تثبيت pip إذا لم يكن موجوداً
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

# المتغيرات الحساسة تُضاف عبر Railway، وليس هنا (لتجنب تحذيرات Docker)
EXPOSE 8080

CMD ["python3", "bot.py"]