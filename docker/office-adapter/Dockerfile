# DocMonitor Office adapter: doc/docx -> текст для file://-watch CDIO.
# Зависимости в образе; сам скрипт монтируется из ./src (правки без пересборки).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir python-docx==1.1.2 httpx==0.27.2 pyyaml==6.0.2 watchdog==4.0.2

WORKDIR /app
