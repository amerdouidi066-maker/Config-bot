FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl tar && apt-get clean

WORKDIR /tmp
RUN curl -L -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-474.0.0-linux-x86_64.tar.gz && \
    tar -xzf google-cloud-sdk-474.0.0-linux-x86_64.tar.gz && \
    mv google-cloud-sdk /opt/ && \
    rm google-cloud-sdk-474.0.0-linux-x86_64.tar.gz

ENV PATH="/opt/google-cloud-sdk/bin:${PATH}"
RUN gcloud --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

CMD ["python3", "bot.py"]