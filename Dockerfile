# Letsma MSP Platform - production container image
# Build:  docker build -t letsma-msp:latest .
# Run:    docker run -p 8000:8000 --env-file .env letsma-msp:latest
#
# This image is deployed to Azure Container Registry (ACR) and run as an
# App Service "Web App for Containers" - see docs/DEPLOYMENT.md.

FROM python:3.12-slim

WORKDIR /app

# System deps needed for psycopg2 (Postgres) and building some wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY agent/ ./agent/

# Azure App Service for Containers expects the app to listen on port 8000
# (or whatever WEBSITES_PORT is set to in App Settings)
EXPOSE 8000

CMD ["gunicorn", "app.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
