#!/bin/sh
set -e

# Wait for database to be ready (via HAProxy or direct)
echo "Waiting for database..."
until pg_isready -h 127.0.0.1 -p 5432 -U monctl -q 2>/dev/null; do
  echo "  Database not ready, retrying in 2s..."
  sleep 2
done

# Advisory lock: only one instance runs migrations at a time
echo "Running database migrations (with advisory lock)..."
cd /app/alembic
python -c "
import psycopg2, os, subprocess, time, sys

db_url = os.environ.get('MONCTL_DATABASE_URL', '')
# Convert asyncpg URL to psycopg2 format
sync_url = db_url.replace('+asyncpg', '').replace('postgresql+asyncpg', 'postgresql')
if not sync_url:
    sync_url = 'postgresql://monctl:monctl@127.0.0.1:5432/monctl'

conn = psycopg2.connect(sync_url)
conn.autocommit = True
cur = conn.cursor()
cur.execute('SELECT pg_try_advisory_lock(1)')
got_lock = cur.fetchone()[0]

if got_lock:
    print('Got migration lock, running alembic upgrade head...')
    result = subprocess.run(['alembic', 'upgrade', 'head'])
    cur.execute('SELECT pg_advisory_unlock(1)')
    if result.returncode != 0:
        sys.exit(result.returncode)
else:
    print('Another instance is running migrations, waiting...')
    for i in range(120):
        time.sleep(1)
        cur.execute('SELECT pg_try_advisory_lock(1)')
        if cur.fetchone()[0]:
            cur.execute('SELECT pg_advisory_unlock(1)')
            print('Migrations completed by other instance.')
            break
    else:
        print('WARNING: Timed out waiting for migrations, proceeding anyway...')

conn.close()
"
cd /app

echo "Starting central server..."
exec uvicorn monctl_central.main:app \
  --host ${MONCTL_HOST:-0.0.0.0} \
  --port ${MONCTL_PORT:-8443}
