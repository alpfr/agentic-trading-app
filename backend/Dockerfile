FROM python:3.11-slim

WORKDIR /app

# System packages needed for:
#   - build-essential, libssl-dev, libffi-dev: curl_cffi, cffi C extensions
#   - libxml2-dev, libxslt-dev: lxml
#   - libpq-dev: psycopg2-binary
#   - tzdata: zoneinfo support for scheduler (America/New_York)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libssl-dev \
        libffi-dev \
        libxml2-dev \
        libxslt-dev \
        libpq-dev \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=America/New_York

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
