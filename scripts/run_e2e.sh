#!/usr/bin/env bash
# Run the F-X-007 e2e smoke harness end-to-end: fresh stack → tests → teardown.
#
# Usage:
#   ./scripts/run_e2e.sh            # boot, test, teardown
#   ./scripts/run_e2e.sh up         # just boot + wait for healthy
#   ./scripts/run_e2e.sh down       # tear down + remove volumes
#   SKIP_BUILD=1 ./scripts/run_e2e.sh   # reuse existing monctl-central image
set -euo pipefail

COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/docker/docker-compose.e2e.yml"
PROJECT="monctl-e2e"
COMPOSE="docker compose -f ${COMPOSE_FILE} -p ${PROJECT}"

cmd="${1:-run}"

case "$cmd" in
  up)
    if [[ -z "${SKIP_BUILD:-}" ]]; then
      ${COMPOSE} build central
    fi
    ${COMPOSE} up -d --wait
    echo "Stack up at http://localhost:18443"
    ;;
  down)
    ${COMPOSE} down -v --remove-orphans
    ;;
  run)
    if [[ -z "${SKIP_BUILD:-}" ]]; then
      ${COMPOSE} build central
    fi
    ${COMPOSE} up -d --wait
    trap "${COMPOSE} down -v --remove-orphans" EXIT
    pytest tests/integration -v
    ;;
  *)
    echo "Unknown command: $cmd (expected: up | down | run)" >&2
    exit 2
    ;;
esac
