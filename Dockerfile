FROM python:3.11-slim

WORKDIR /app

# libusb-1.0-0 is required by pyvisa-py for USB instrument support.
# Not strictly needed for TCP/LXI-only use, but included for completeness
# and to avoid import warnings from pyvisa-py at startup.
RUN apt-get update && apt-get install -y \
    libusb-1.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
