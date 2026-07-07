FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl unzip \
    && curl -sSL https://sdk.cloud.google.com | bash \
    && /root/google-cloud-sdk/install.sh --quiet \
    && /root/google-cloud-sdk/bin/gcloud config set core/disable_usage_reporting true \
    && /root/google-cloud-sdk/bin/gcloud config set component_manager/disable_update_check true \
    && rm -rf /var/lib/apt/lists/*
ENV PATH $PATH:/root/google-cloud-sdk/bin
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]