#!/bin/sh
set -e

# Extract DB host/port from DATABASE_URL (works with both local and external PostgreSQL)
DB_URL="${MONCTL_DATABASE_URL:-postgresql+asyncpg://monctl:monctl@127.0.0.1:5432/monctl}"
# Strip scheme prefix, extract host:port — handles postgresql+asyncpg://user:pass@host:port/db
DB_HOST=$(echo "$DB_URL" | sed -E 's|.*@([^:/]+).*|\1|')
DB_PORT=$(echo "$DB_URL" | sed -E 's|.*@[^:]+:([0-9]+).*|\1|')
DB_PORT="${DB_PORT:-5432}"

echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U monctl -q 2>/dev/null; do
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

# Stamp head if alembic_version table doesn't exist yet (fresh DB).
# For a fresh DB we also need to create the initial schema — do it here,
# gated on 'no alembic_version' so existing DBs never run create_all.
# (create_all on existing DBs would race with migrations that add new
# tables: create_all pre-creates them from models.py and alembic upgrade
# then hits DuplicateTableError.)
cur.execute(\"\"\"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version')\"\"\")
has_alembic = cur.fetchone()[0]
if not has_alembic:
    print('Fresh database — creating base schema + stamping alembic head...')
    from sqlalchemy import create_engine
    from monctl_central.storage.models import Base
    engine = create_engine(sync_url)
    try:
        Base.metadata.create_all(engine, checkfirst=True)
    except Exception as e:
        print(f'Note: create_all skipped ({e.__class__.__name__}), migrations will handle it.')
    engine.dispose()
    subprocess.run(['alembic', 'stamp', 'head'], check=True)
    print('Stamped.')
    conn.close()
    sys.exit(0)

# Check if there's already a revision stamped
cur.execute('SELECT version_num FROM alembic_version LIMIT 1')
row = cur.fetchone()
if row is None:
    print('No alembic version found — stamping head...')
    subprocess.run(['alembic', 'stamp', 'head'], check=True)
    conn.close()
    sys.exit(0)

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
