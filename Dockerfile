# healthcare-backend/Dockerfile
FROM python:3.13.1-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# CRITICAL: Add WebSocket flags to uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "websockets", "--ws-ping-interval", "20", "--ws-ping-timeout", "20", "--proxy-headers", "--forwarded-allow-ips", "*"]