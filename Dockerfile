FROM mcr.microsoft.com/playwright:python-v1.40.0-focal

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium && \
    playwright install-deps

COPY . .

ENV TOKEN=""
ENV WEB_PASSWORD="shadow2099"
ENV WEB_SECRET="shadow_legion_secret"
ENV CLEANUP_DAYS="7"

EXPOSE 8080

CMD ["python3", "bot.py"]