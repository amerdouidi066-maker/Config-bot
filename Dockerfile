FROM python:3.11-slim

# تثبيت أدوات أساسية
RUN apt-get update && apt-get install -y curl tar && apt-get clean

# تحميل Google Cloud SDK يدوياً (بدون apt-key)
WORKDIR /tmp
RUN curl -L -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-474.0.0-linux-x86_64.tar.gz && \
    tar -xzf google-cloud-sdk-474.0.0-linux-x86_64.tar.gz && \
    mv google-cloud-sdk /opt/ && \
    rm google-cloud-sdk-474.0.0-linux-x86_64.tar.gz

# إضافة gcloud إلى PATH
ENV PATH="/opt/google-cloud-sdk/bin:${PATH}"

# تحقق من التثبيت
RUN gcloud --version

# نسخ ملفات البوت
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# تشغيل البوت
CMD ["python3", "bot.py"]