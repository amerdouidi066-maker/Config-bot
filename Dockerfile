FROM mcr.microsoft.com/playwright:python-3.10

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m -u 1000 shadow && chown -R shadow:shadow /app
USER shadow

CMD ["python", "bot.py"]