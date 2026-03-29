#!/usr/bin/env bash
set -euo pipefail

# ── MonCTL Deploy Script ─────────────────────────────────────────────────────
# Usage:
#   ./deploy.sh central          # Build + deploy central to all 4 nodes
#   ./deploy.sh collector        # Build + deploy collector to all 4 workers
#   ./deploy.sh central --no-build   # Deploy only (skip build, use existing image)
#   ./deploy.sh central 41 42       # Deploy to specific nodes only (last octet)

CENTRAL_IPS=(10.145.210.41 10.145.210.42 10.145.210.43 10.145.210.44)
WORKER_IPS=(10.145.210.31 10.145.210.32 10.145.210.33 10.145.210.34)
SSH_USER=monctl

# Central 1-3 use central-ha, central 4 uses central
central_compose_dir() {
  local ip=$1
  if [[ "$ip" == "10.145.210.44" ]]; then
    echo "/opt/monctl/central"
  else
    echo "/opt/monctl/central-ha"
  fi
}

# ── Parse args ───────────────────────────────────────────────────────────────
TARGET="${1:-}"
shift || true

if [[ -z "$TARGET" || ( "$TARGET" != "central" && "$TARGET" != "collector" ) ]]; then
  echo "Usage: $0 <central|collector> [--no-build] [node-suffixes...]"
  echo ""
  echo "Examples:"
  echo "  $0 central              # Build + deploy to all central nodes"
  echo "  $0 collector            # Build + deploy to all worker nodes"
  echo "  $0 central --no-build   # Skip build, deploy existing image"
  echo "  $0 central 41 42        # Deploy to central1 + central2 only"
  exit 1
fi

DO_BUILD=true
SPECIFIC_NODES=()
for arg in "$@"; do
  if [[ "$arg" == "--no-build" ]]; then
    DO_BUILD=false
  else
    SPECIFIC_NODES+=("$arg")
  fi
done

# ── Determine image + nodes ──────────────────────────────────────────────────
if [[ "$TARGET" == "central" ]]; then
  IMAGE="monctl-central:latest"
  DOCKERFILE="docker/Dockerfile.central"
  ALL_IPS=("${CENTRAL_IPS[@]}")
else
  IMAGE="monctl-collector:latest"
  DOCKERFILE="docker/Dockerfile.collector-v2"
  ALL_IPS=("${WORKER_IPS[@]}")
fi

# Filter to specific nodes if provided
DEPLOY_IPS=()
if [[ ${#SPECIFIC_NODES[@]} -gt 0 ]]; then
  for suffix in "${SPECIFIC_NODES[@]}"; do
    for ip in "${ALL_IPS[@]}"; do
      if [[ "$ip" == *".$suffix" ]]; then
        DEPLOY_IPS+=("$ip")
      fi
    done
  done
  if [[ ${#DEPLOY_IPS[@]} -eq 0 ]]; then
    echo "Error: No matching nodes for suffixes: ${SPECIFIC_NODES[*]}"
    exit 1
  fi
else
  DEPLOY_IPS=("${ALL_IPS[@]}")
fi

echo "═══════════════════════════════════════════════════"
echo "  MonCTL Deploy: $TARGET"
echo "  Nodes: ${DEPLOY_IPS[*]}"
echo "  Build: $DO_BUILD"
echo "═══════════════════════════════════════════════════"

# ── Build ────────────────────────────────────────────────────────────────────
if [[ "$DO_BUILD" == true ]]; then
  echo ""
  echo "▸ Building $IMAGE ..."
  BUILD_START=$(date +%s)
  docker build --platform linux/amd64 -t "$IMAGE" -f "$DOCKERFILE" . 2>&1 | tail -3
  BUILD_END=$(date +%s)
  echo "  Build: $((BUILD_END - BUILD_START))s"
fi

# ── Save image once to a temp file ───────────────────────────────────────────
echo ""
echo "▸ Saving image to temp file ..."
SAVE_START=$(date +%s)
TMPFILE=$(mktemp /tmp/monctl-deploy-XXXXXX.tar)
docker save "$IMAGE" > "$TMPFILE"
SAVE_END=$(date +%s)
IMAGE_SIZE=$(du -h "$TMPFILE" | cut -f1)
echo "  Saved: $IMAGE_SIZE in $((SAVE_END - SAVE_START))s"

# ── Deploy in parallel ───────────────────────────────────────────────────────
echo ""
echo "▸ Deploying to ${#DEPLOY_IPS[@]} nodes in parallel ..."
DEPLOY_START=$(date +%s)

deploy_node() {
  local ip=$1
  local tmpfile=$2
  local target=$3
  local node_start=$(date +%s)

  # Transfer + load
  ssh "$SSH_USER@$ip" 'docker load' < "$tmpfile" > /dev/null 2>&1

  # Restart service
  if [[ "$target" == "central" ]]; then
    local compose_dir
    compose_dir=$(central_compose_dir "$ip")
    ssh "$SSH_USER@$ip" "cd $compose_dir && docker compose up -d central" > /dev/null 2>&1
  else
    ssh "$SSH_USER@$ip" "cd /opt/monctl/collector && docker compose up -d" > /dev/null 2>&1
  fi

  # Prune old images
  ssh "$SSH_USER@$ip" 'docker image prune -f' > /dev/null 2>&1

  local node_end=$(date +%s)
  echo "  ✓ $ip ($((node_end - node_start))s)"
}

# Launch all deploys in background
PIDS=()
for ip in "${DEPLOY_IPS[@]}"; do
  deploy_node "$ip" "$TMPFILE" "$TARGET" &
  PIDS+=($!)
done

# Wait for all
FAILED=0
for pid in "${PIDS[@]}"; do
  if ! wait "$pid"; then
    FAILED=$((FAILED + 1))
  fi
done

DEPLOY_END=$(date +%s)
rm -f "$TMPFILE"

echo ""
if [[ $FAILED -gt 0 ]]; then
  echo "⚠ $FAILED node(s) failed!"
  exit 1
else
  echo "═══════════════════════════════════════════════════"
  echo "  Done! ${#DEPLOY_IPS[@]} nodes deployed in $((DEPLOY_END - DEPLOY_START))s"
  [[ "$DO_BUILD" == true ]] && echo "  Total (build + deploy): $((DEPLOY_END - BUILD_START))s"
  echo "═══════════════════════════════════════════════════"
fi
