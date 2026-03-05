#!/bin/sh
set -e

echo "Running database migrations..."
cd /app/alembic && alembic upgrade head && cd /app

echo "Starting central server..."
exec uvicorn monctl_central.main:app --host 0.0.0.0 --port 8443
