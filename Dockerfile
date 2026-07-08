FROM mcr.microsoft.com/playwright:v1.40.0-focal
WORKDIR /app
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt
COPY . .
ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"
ENV WEB_SECRET="shadow_legion_secret"
ENV CLEANUP_DAYS="7"
EXPOSE 8080
CMD ["python3", "bot.py"]