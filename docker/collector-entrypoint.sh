#!/bin/bash
set -e

CREDS_FILE="${MONCTL_COLLECTOR_CREDENTIALS_FILE:-/var/lib/monctl/credentials.json}"

# Wait for central to be ready
echo "Waiting for central server at ${MONCTL_COLLECTOR_CENTRAL_URL}..."
until curl -sf "${MONCTL_COLLECTOR_CENTRAL_URL}/v1/health" > /dev/null 2>&1; do
    sleep 2
done
echo "Central server is ready."

# Register if not already registered
if [ ! -f "$CREDS_FILE" ]; then
    echo "Registering collector with central..."

    # Build registration JSON with Python to avoid quoting issues
    REG_JSON=$(python3 -c "
import json, os, socket
payload = {
    'hostname': socket.gethostname(),
    'registration_token': os.environ['MONCTL_COLLECTOR_REGISTRATION_TOKEN'],
    'labels': json.loads(os.environ.get('MONCTL_COLLECTOR_LABELS', '{}')),
}
cluster_id = os.environ.get('MONCTL_COLLECTOR_CLUSTER_ID', '')
if cluster_id:
    payload['cluster_id'] = cluster_id
print(json.dumps(payload))
")

    RESPONSE=$(curl -sf -X POST "${MONCTL_COLLECTOR_CENTRAL_URL}/v1/collectors/register" \
        -H "Content-Type: application/json" \
        -d "$REG_JSON")

    if [ $? -ne 0 ]; then
        echo "ERROR: Registration failed"
        exit 1
    fi

    COLLECTOR_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['collector_id'])")
    API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

    # Store credentials
    mkdir -p "$(dirname "$CREDS_FILE")"
    echo "$RESPONSE" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    echo "Registered as ${COLLECTOR_ID}"

    # Export for the daemon
    export MONCTL_COLLECTOR_COLLECTOR_ID="$COLLECTOR_ID"
    export MONCTL_COLLECTOR_API_KEY="$API_KEY"
else
    echo "Already registered, loading credentials..."
    COLLECTOR_ID=$(python3 -c "import json; print(json.load(open('$CREDS_FILE'))['collector_id'])")
    API_KEY=$(python3 -c "import json; print(json.load(open('$CREDS_FILE'))['api_key'])")

    export MONCTL_COLLECTOR_COLLECTOR_ID="$COLLECTOR_ID"
    export MONCTL_COLLECTOR_API_KEY="$API_KEY"

    echo "Loaded collector ${COLLECTOR_ID}"
fi

echo "Starting collector daemon..."
exec monctl-collector start
