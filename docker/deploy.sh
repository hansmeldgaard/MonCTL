#!/bin/bash
# MonCTL Full HA Deployment Script
# Run from management host (/home/monctl/MonCTL)
set -e

CENTRAL_IPS=(10.145.210.41 10.145.210.42 10.145.210.43 10.145.210.44)
COLLECTOR_IPS=(10.145.210.31 10.145.210.32 10.145.210.33 10.145.210.34)
ALL_IPS=("${CENTRAL_IPS[@]}" "${COLLECTOR_IPS[@]}")
SSH_USER=monctl

echo "=== MonCTL HA Deployment ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Fase 1: Docker on all servers
# ─────────────────────────────────────────────────────────────────────────────
fase1_docker() {
  echo ">>> Fase 1: Installing Docker on all servers..."
  for IP in "${ALL_IPS[@]}"; do
    echo "  [$IP] Installing Docker..."
    ssh ${SSH_USER}@${IP} 'sudo apt-get update -qq && sudo apt-get install -y -qq docker.io docker-compose-v2 && sudo usermod -aG docker monctl && sudo systemctl enable --now docker' &
  done
  wait
  echo "  Verifying Docker..."
  for IP in "${ALL_IPS[@]}"; do
    echo -n "  [$IP] "
    ssh ${SSH_USER}@${IP} 'docker --version && docker compose version' 2>/dev/null || echo "FAILED"
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# Fase 2: Build images
# ─────────────────────────────────────────────────────────────────────────────
fase2_build() {
  echo ">>> Fase 2: Building Docker images..."
  cd /home/monctl/MonCTL

  echo "  Building monctl-central:latest..."
  docker build --platform linux/amd64 --no-cache \
    -t monctl-central:latest -f docker/Dockerfile.central .

  echo "  Building monctl-collector:latest..."
  docker build --platform linux/amd64 --no-cache \
    -t monctl-collector:latest -f docker/Dockerfile.collector-v2 packages/collector/
}

# ─────────────────────────────────────────────────────────────────────────────
# Fase 3: Distribute images
# ─────────────────────────────────────────────────────────────────────────────
fase3_distribute() {
  echo ">>> Fase 3: Distributing images..."

  echo "  Saving central image..."
  docker save monctl-central:latest > /tmp/monctl-central.tar
  echo "  Saving collector image..."
  docker save monctl-collector:latest > /tmp/monctl-collector.tar

  for IP in "${CENTRAL_IPS[@]}"; do
    echo "  [$IP] Loading central image..."
    cat /tmp/monctl-central.tar | ssh ${SSH_USER}@${IP} 'docker load' &
  done

  for IP in "${COLLECTOR_IPS[@]}"; do
    echo "  [$IP] Loading collector image..."
    cat /tmp/monctl-collector.tar | ssh ${SSH_USER}@${IP} 'docker load' &
  done
  wait
  rm -f /tmp/monctl-central.tar /tmp/monctl-collector.tar
}

# ─────────────────────────────────────────────────────────────────────────────
# Fase 5: Deploy central1 (single-node)
# ─────────────────────────────────────────────────────────────────────────────
fase5_central1() {
  echo ">>> Fase 5: Deploying central1 (single-node)..."
  IP=10.145.210.41

  ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/central && sudo chown monctl:monctl /opt/monctl/central'
  scp docker/docker-compose.central-prod.yml ${SSH_USER}@${IP}:/opt/monctl/central/docker-compose.yml
  scp .env.central ${SSH_USER}@${IP}:/opt/monctl/central/.env
  ssh ${SSH_USER}@${IP} 'cd /opt/monctl/central && docker compose up -d'

  echo "  Waiting for central1 to be healthy..."
  for i in $(seq 1 30); do
    if curl -sf http://${IP}:8443/v1/health >/dev/null 2>&1; then
      echo "  central1 is UP!"
      return 0
    fi
    sleep 2
  done
  echo "  WARNING: central1 health check timed out"
}

# ─────────────────────────────────────────────────────────────────────────────
# Fase 6: Deploy collectors
# ─────────────────────────────────────────────────────────────────────────────
fase6_collectors() {
  echo ">>> Fase 6: Deploying collectors..."

  for i in 1 2 3 4; do
    IP="10.145.210.3${i}"
    echo "  [$IP] Deploying collector-0${i}..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/collector /etc/monctl && sudo chown monctl:monctl /opt/monctl/collector && sudo touch /etc/monctl/setup.yaml'
    scp docker/docker-compose.collector-prod.yml ${SSH_USER}@${IP}:/opt/monctl/collector/docker-compose.yml
    scp .env.collector-${i} ${SSH_USER}@${IP}:/opt/monctl/collector/.env
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/collector && docker compose up -d'
  done

  echo "  Verifying collectors..."
  for i in 1 2 3 4; do
    IP="10.145.210.3${i}"
    echo -n "  [$IP] "
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/collector && docker compose ps --format "table {{.Name}}\t{{.Status}}"' 2>/dev/null || echo "FAILED"
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# Fase 7: HA setup
# ─────────────────────────────────────────────────────────────────────────────
fase7_ha() {
  echo ">>> Fase 7: HA setup..."

  # 7a: etcd cluster
  echo "  7a: Deploying etcd cluster..."
  ETCD_NODES=("10.145.210.41:etcd1" "10.145.210.42:etcd2" "10.145.210.43:etcd3")
  for entry in "${ETCD_NODES[@]}"; do
    IP="${entry%%:*}"
    NAME="${entry##*:}"
    echo "    [$IP] etcd node ${NAME}..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/etcd && sudo chown monctl:monctl /opt/monctl/etcd'
    scp docker/docker-compose.etcd.yml ${SSH_USER}@${IP}:/opt/monctl/etcd/docker-compose.yml
    ssh ${SSH_USER}@${IP} "echo 'ETCD_NAME=${NAME}' > /opt/monctl/etcd/.env && echo 'ETCD_ADVERTISE_IP=${IP}' >> /opt/monctl/etcd/.env"
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/etcd && docker compose up -d'
  done

  # 7b: Patroni
  echo "  7b: Deploying Patroni..."
  source .env.secrets
  for entry in "10.145.210.41:pg1:all" "10.145.210.42:pg2:api"; do
    IFS=: read -r IP NAME ROLE <<< "$entry"
    echo "    [$IP] Patroni node ${NAME} (role=${ROLE})..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/central-ha && sudo chown monctl:monctl /opt/monctl/central-ha'
    scp docker/docker-compose.central-ha.yml ${SSH_USER}@${IP}:/opt/monctl/central-ha/docker-compose.yml
    scp docker/patroni.yml ${SSH_USER}@${IP}:/opt/monctl/central-ha/patroni.yml

    cat > /tmp/.env.ha <<EOF
PG_PASSWORD=${PG_PASSWORD}
PG_REPL_PASSWORD=${PG_REPL_PASSWORD}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
JWT_SECRET=${JWT_SECRET}
COLLECTOR_API_KEY=${COLLECTOR_API_KEY}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
PATRONI_NAME=${NAME}
NODE_IP=${IP}
MONCTL_ROLE=${ROLE}
PG_HOST=${IP}
REDIS_HOST=10.145.210.41
CLICKHOUSE_HOSTS=10.145.210.43,10.145.210.44
COMPOSE_PROFILES=db,redis
EOF
    # central2 doesn't run redis
    if [ "$IP" = "10.145.210.42" ]; then
      sed -i 's/COMPOSE_PROFILES=db,redis/COMPOSE_PROFILES=db/' /tmp/.env.ha
    fi
    scp /tmp/.env.ha ${SSH_USER}@${IP}:/opt/monctl/central-ha/.env
  done

  # central3 + central4: app only (no Patroni)
  for entry in "10.145.210.43:api" "10.145.210.44:api"; do
    IFS=: read -r IP ROLE <<< "$entry"
    echo "    [$IP] Central app (role=${ROLE})..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/central-ha && sudo chown monctl:monctl /opt/monctl/central-ha'
    scp docker/docker-compose.central-ha.yml ${SSH_USER}@${IP}:/opt/monctl/central-ha/docker-compose.yml

    cat > /tmp/.env.ha <<EOF
PG_PASSWORD=${PG_PASSWORD}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
JWT_SECRET=${JWT_SECRET}
COLLECTOR_API_KEY=${COLLECTOR_API_KEY}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
NODE_IP=${IP}
MONCTL_ROLE=${ROLE}
PG_HOST=10.145.210.41
REDIS_HOST=10.145.210.41
CLICKHOUSE_HOSTS=10.145.210.43,10.145.210.44
EOF
    scp /tmp/.env.ha ${SSH_USER}@${IP}:/opt/monctl/central-ha/.env
  done
  rm -f /tmp/.env.ha

  # 7c: Redis Sentinel
  echo "  7c: Deploying Redis Sentinel..."
  SENTINEL_NODES=("10.145.210.41" "10.145.210.42" "10.145.210.43")
  for IP in "${SENTINEL_NODES[@]}"; do
    echo "    [$IP] Deploying sentinel.conf..."
    scp docker/sentinel.conf ${SSH_USER}@${IP}:/opt/monctl/central-ha/sentinel.conf
  done

  # Update COMPOSE_PROFILES for Redis HA
  # central1: redis → redis-primary,redis-sentinel
  ssh ${SSH_USER}@10.145.210.41 "sed -i 's/COMPOSE_PROFILES=db,redis/COMPOSE_PROFILES=db,redis-primary,redis-sentinel/' /opt/monctl/central-ha/.env"
  # central2: add redis-replica,redis-sentinel
  ssh ${SSH_USER}@10.145.210.42 "sed -i 's/COMPOSE_PROFILES=db/COMPOSE_PROFILES=db,redis-replica,redis-sentinel/' /opt/monctl/central-ha/.env"
  # central3: add redis-sentinel (tiebreaker)
  ssh ${SSH_USER}@10.145.210.43 "grep -q redis-sentinel /opt/monctl/central-ha/.env || sed -i 's/COMPOSE_PROFILES=\(.*\)/COMPOSE_PROFILES=\1,redis-sentinel/' /opt/monctl/central-ha/.env"

  # Add Sentinel env vars to all central nodes
  for IP in "${CENTRAL_IPS[@]}"; do
    ssh ${SSH_USER}@${IP} "grep -q MONCTL_REDIS_SENTINEL_HOSTS /opt/monctl/central-ha/.env || echo 'MONCTL_REDIS_SENTINEL_HOSTS=10.145.210.41:26379,10.145.210.42:26379,10.145.210.43:26379' >> /opt/monctl/central-ha/.env"
    ssh ${SSH_USER}@${IP} "grep -q MONCTL_REDIS_SENTINEL_MASTER /opt/monctl/central-ha/.env || echo 'MONCTL_REDIS_SENTINEL_MASTER=monctl-redis' >> /opt/monctl/central-ha/.env"
  done

  # 7d: ClickHouse
  echo "  7d: Deploying ClickHouse..."
  for entry in "10.145.210.43:ch1:1" "10.145.210.44:ch2:2"; do
    IFS=: read -r IP REPLICA KEEPER_ID <<< "$entry"
    echo "    [$IP] ClickHouse replica ${REPLICA}..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/clickhouse && sudo chown monctl:monctl /opt/monctl/clickhouse'
    scp docker/docker-compose.clickhouse.yml ${SSH_USER}@${IP}:/opt/monctl/clickhouse/docker-compose.yml
    scp docker/clickhouse-config.xml ${SSH_USER}@${IP}:/opt/monctl/clickhouse/clickhouse-config.xml
    ssh ${SSH_USER}@${IP} "echo 'CLICKHOUSE_REPLICA=${REPLICA}' > /opt/monctl/clickhouse/.env && echo 'KEEPER_SERVER_ID=${KEEPER_ID}' >> /opt/monctl/clickhouse/.env"
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/clickhouse && docker compose up -d'
  done

  # 7e: Generate TLS cert
  echo "  7e: Generating TLS certificate..."
  bash docker/generate-tls-cert.sh

  # 7f: HAProxy + Keepalived
  echo "  7f: Deploying HAProxy + Keepalived..."
  PRIORITIES=("100" "99" "98" "97")
  for idx in 0 1 2 3; do
    IP="${CENTRAL_IPS[$idx]}"
    PRIO="${PRIORITIES[$idx]}"
    echo "    [$IP] HAProxy + Keepalived (priority=${PRIO})..."
    ssh ${SSH_USER}@${IP} 'sudo mkdir -p /opt/monctl/haproxy && sudo chown monctl:monctl /opt/monctl/haproxy'
    scp docker/docker-compose.haproxy.yml ${SSH_USER}@${IP}:/opt/monctl/haproxy/docker-compose.yml
    scp docker/haproxy.cfg ${SSH_USER}@${IP}:/opt/monctl/haproxy/haproxy.cfg
    scp docker/keepalived.conf ${SSH_USER}@${IP}:/opt/monctl/haproxy/keepalived.conf
    scp -r docker/certs ${SSH_USER}@${IP}:/opt/monctl/haproxy/certs
    ssh ${SSH_USER}@${IP} "echo 'KEEPALIVED_PRIORITY=${PRIO}' > /opt/monctl/haproxy/.env && echo 'KEEPALIVED_INTERFACE=eth0' >> /opt/monctl/haproxy/.env"
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/haproxy && docker compose up -d'
  done

  # Update collector CENTRAL_URL to VIP
  echo "  Updating collectors to use VIP..."
  for i in 1 2 3 4; do
    IP="10.145.210.3${i}"
    ssh ${SSH_USER}@${IP} "sed -i 's|CENTRAL_URL=http://10.145.210.41:8443|CENTRAL_URL=https://10.145.210.40|' /opt/monctl/collector/.env"
    ssh ${SSH_USER}@${IP} 'cd /opt/monctl/collector && docker compose up -d'
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
case "${1:-all}" in
  fase1|docker)     fase1_docker ;;
  fase2|build)      fase2_build ;;
  fase3|distribute) fase3_distribute ;;
  fase5|central1)   fase5_central1 ;;
  fase6|collectors) fase6_collectors ;;
  fase7|ha)         fase7_ha ;;
  all)
    fase1_docker
    fase2_build
    fase3_distribute
    fase5_central1
    fase6_collectors
    fase7_ha
    echo ""
    echo "=== Deployment complete ==="
    echo "VIP: https://10.145.210.40"
    echo "Admin: admin / (see .env.secrets for password)"
    ;;
  *)
    echo "Usage: $0 {fase1|fase2|fase3|fase5|fase6|fase7|all}"
    exit 1
    ;;
esac
