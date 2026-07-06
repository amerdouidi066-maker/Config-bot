FROM python:3.10-slim
WORKDIR /app
COPY apt.txt /tmp/apt.txt
RUN apt-get update && apt-get install -y $(cat /tmp/apt.txt) \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]