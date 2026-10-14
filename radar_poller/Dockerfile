FROM python:3.12-slim

WORKDIR /app

# gdal_translate converts downloads to compressed Cloud Optimized GeoTIFF
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poller.py .

RUN mkdir -p /data/dbz/geotiff

ENV OUTPUT_DIR=/data/dbz/geotiff \
    POLL_INTERVAL_SECONDS=10

CMD ["python", "-u", "poller.py"]
