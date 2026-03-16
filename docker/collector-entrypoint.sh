#!/bin/bash
set -e

CREDS_FILE="${MONCTL_CREDENTIALS_FILE:-/var/lib/monctl/credentials.json}"
CENTRAL_URL="${MONCTL_CENTRAL_URL}"
API_KEY="${MONCTL_CENTRAL_API_KEY}"
REG_TOKEN="${MONCTL_REGISTRATION_TOKEN}"

# Build curl flags (skip TLS verify if configured)
CURL_OPTS="-sf"
if [ "${MONCTL_VERIFY_SSL:-true}" = "false" ]; then
    CURL_OPTS="-skf"
fi

# Wait for central to be ready
echo "Waiting for central server at ${CENTRAL_URL}..."
until curl $CURL_OPTS "${CENTRAL_URL}/v1/health" > /dev/null 2>&1; do
    sleep 2
done
echo "Central server is ready."

# If arguments were passed (e.g. from compose "command: monctl-poll-worker"),
# and we don't need to resolve collector credentials, just run the command.
# poll-worker and forwarder connect to cache-node, not central directly.
if [ $# -gt 0 ] && [ -z "$MONCTL_REGISTRATION_TOKEN" ] && [ -z "$MONCTL_COLLECTOR_ID" ] && [ ! -f "$CREDS_FILE" ]; then
    echo "Starting: $@"
    exec "$@"
fi

# If MONCTL_COLLECTOR_ID is already set in env, skip registration
if [ -n "$MONCTL_COLLECTOR_ID" ] && [ -n "$MONCTL_COLLECTOR_API_KEY" ]; then
    echo "Collector ID already set: ${MONCTL_COLLECTOR_ID}"
elif [ -f "$CREDS_FILE" ]; then
    echo "Loading credentials from ${CREDS_FILE}..."
    COLLECTOR_ID=$(python3 -c "import json; print(json.load(open('$CREDS_FILE'))['collector_id'])")
    REG_API_KEY=$(python3 -c "import json; print(json.load(open('$CREDS_FILE'))['api_key'])")

    export MONCTL_COLLECTOR_ID="$COLLECTOR_ID"
    export MONCTL_COLLECTOR_API_KEY="$REG_API_KEY"

    echo "Loaded collector ${COLLECTOR_ID}"
elif [ -n "$REG_TOKEN" ]; then
    echo "Registering collector with central..."

    REG_JSON=$(python3 -c "
import json, os, socket
payload = {
    'hostname': os.environ.get('MONCTL_NODE_ID', socket.gethostname()),
    'registration_token': os.environ['MONCTL_REGISTRATION_TOKEN'],
    'labels': json.loads(os.environ.get('MONCTL_REGISTRATION_LABELS', '{}')),
}
cluster_id = os.environ.get('MONCTL_CLUSTER_ID', '')
if cluster_id:
    payload['cluster_id'] = cluster_id
print(json.dumps(payload))
")

    RESPONSE=$(curl $CURL_OPTS -X POST "${CENTRAL_URL}/v1/collectors/register" \
        -H "Content-Type: application/json" \
        -d "$REG_JSON")

    if [ $? -ne 0 ]; then
        echo "ERROR: Registration failed"
        exit 1
    fi

    COLLECTOR_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['collector_id'])")
    REG_API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

    # Store credentials
    mkdir -p "$(dirname "$CREDS_FILE")"
    echo "$RESPONSE" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    echo "Registered as ${COLLECTOR_ID}"

    export MONCTL_COLLECTOR_ID="$COLLECTOR_ID"
    export MONCTL_COLLECTOR_API_KEY="$REG_API_KEY"
else
    echo "No registration token set and no credentials file found."
    echo "Set MONCTL_REGISTRATION_TOKEN or MONCTL_COLLECTOR_ID to proceed."
    exit 1
fi

# If arguments were passed (e.g. from compose "command: monctl-cache-node"),
# execute that command instead of starting all processes
if [ $# -gt 0 ]; then
    echo "Starting: $@"
    exec "$@"
fi

# Standalone mode: start all three collector processes
echo "Starting collector processes..."

monctl-cache-node &
CACHE_PID=$!

# Give cache-node a moment to start the gRPC server
sleep 2

monctl-poll-worker &
POLL_PID=$!

monctl-forwarder &
FWD_PID=$!

echo "Started cache-node (PID $CACHE_PID), poll-worker (PID $POLL_PID), forwarder (PID $FWD_PID)"

# Wait for any process to exit, then stop all
wait -n $CACHE_PID $POLL_PID $FWD_PID
EXIT_CODE=$?

echo "A collector process exited with code $EXIT_CODE, shutting down..."
kill $CACHE_PID $POLL_PID $FWD_PID 2>/dev/null
wait
exit $EXIT_CODE
