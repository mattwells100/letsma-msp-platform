#!/bin/bash
# Azure App Service (Linux) startup command for code-based deployment.
#
# Set this as the App Service "Startup Command" (Configuration > General settings),
# or reference it via: az webapp config set --startup-file "startup.sh"
#
# Gunicorn manages worker processes; each worker runs FastAPI via Uvicorn's
# ASGI worker class. Oryx (App Service's Linux build system) already installs
# requirements.txt automatically on deploy, so no pip install is needed here.

gunicorn app.main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile '-' \
    --error-logfile '-'
