
FROM mcr.microsoft.com/playwright:v1.40.0-focal

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"

EXPOSE 8080
CMD ["python", "bot.py"]