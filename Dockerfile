FROM python:3.11-slim

WORKDIR /app

# libusb-1.0-0 is required by pyvisa-py for USB instrument support.
# curl is required for Docker health check.
RUN apt-get update && apt-get install -y \
    libusb-1.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
