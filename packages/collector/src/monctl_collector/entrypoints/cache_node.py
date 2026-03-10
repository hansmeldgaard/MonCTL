"""cache-node entrypoint — the cluster brain.

Responsibilities:
  - Joins the collector cluster via SWIM gossip
  - Syncs job definitions from central (delta-sync every 60s)
  - Assigns jobs to registered poll-workers (app-affinity)
  - Runs distributed cache (get/put with consistent-hash replication)
  - Work-stealing: offloads jobs to under-loaded peers when overloaded
  - Serves gRPC API for peer nodes AND local poll-workers

Configuration (in priority order):
  1. config.yaml (path via MONCTL_CONFIG or /etc/monctl/config.yaml)
  2. Environment variables (MONCTL_*)

Required env vars (if no config.yaml):
  MONCTL_NODE_ID         — unique name for this cache-node
  MONCTL_CENTRAL_URL     — e.g. https://central.example.com
  MONCTL_CENTRAL_API_KEY — API key for /api/v1/* endpoints
  MONCTL_PEERS           — comma-separated host:port of other cache-nodes
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import signal
import socket

from aiohttp import web
import structlog

from monctl_collector.cache.distributed_cache import DistributedCache
from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient
from monctl_collector.central.credentials import CredentialManager
from monctl_collector.cluster.gossip import GossipProtocol
from monctl_collector.cluster.hash_ring import HashRing
from monctl_collector.cluster.membership import MembershipTable
from monctl_collector.config import CollectorConfig, load_config
from monctl_collector.jobs.scheduler import JobScheduler
from monctl_collector.jobs.work_stealer import WorkStealer
from monctl_collector.peer.client import PeerChannelPool
from monctl_collector.peer.server import CollectorPeerServicer, start_server

logger = structlog.get_logger()


async def run(cfg: CollectorConfig) -> None:
    node_id = cfg.node_id or socket.gethostname()
    listen_addr = f"{cfg.listen_address}:{cfg.listen_port}"

    logger.info("cache_node_starting", node_id=node_id, listen=listen_addr)

    # ── Infrastructure ────────────────────────────────────────────────────────
    local_cache = LocalCache(cfg.cache.db_path)
    await local_cache.open()

    channel_pool = PeerChannelPool()
    central_client = CentralAPIClient(
        cfg.central.url,
        api_key=cfg.central.api_key,
        timeout=cfg.central.timeout,
        verify_ssl=cfg.central.verify_ssl,
    )
    await central_client.open()

    encryption_key = CredentialManager.make_key()
    credential_manager = CredentialManager(
        central_client=central_client,
        local_cache=local_cache,
        encryption_key=encryption_key,
        refresh_interval=cfg.central.credential_refresh,
    )

    # ── Cluster ───────────────────────────────────────────────────────────────
    hash_ring = HashRing(
        vnodes_per_node=cfg.cluster.vnodes,
        replication_factor=cfg.cluster.replication_factor,
    )
    # Advertise external IP:port to peers (not 0.0.0.0 which is unreachable from outside)
    advertise_addr = cfg.advertise_address or listen_addr
    membership = MembershipTable(node_id)
    membership.add_local(advertise_addr)
    hash_ring.add_node(node_id)

    # ── Dynamic peer discovery from central ─────────────────────────────────
    if cfg.collector_id and cfg.collector_api_key:
        central_peers = await _discover_peers_from_central(
            central_client, node_id, cfg.collector_id, cfg.collector_api_key
        )
        if central_peers:
            logger.info("central_peer_discovery", peers=len(central_peers))
            for peer_info in central_peers:
                peer_id = peer_info.get("node_id", "")
                peer_addr = peer_info.get("address", "")
                if peer_id and peer_addr and peer_id != node_id:
                    membership.add_seed(peer_id, peer_addr)
                    hash_ring.add_node(peer_id)
    else:
        logger.info("peer_discovery_skipped", reason="no collector_id or collector_api_key")

    # Seed peers into membership.
    # Format: "nodeid=host:port"  (preferred) or bare "host:port" (uses host as node_id)
    for peer_spec in cfg.seeds:
        if "=" in peer_spec:
            peer_id, peer_addr = peer_spec.split("=", 1)
        else:
            peer_addr = peer_spec
            peer_id = peer_addr.split(":")[0]  # fall back: use host part as node_id
        membership.add_seed(peer_id, peer_addr)
        hash_ring.add_node(peer_id)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = JobScheduler(
        node_id=node_id,
        local_cache=local_cache,
        central_client=central_client,
        hash_ring=hash_ring,
        membership=membership,
        config=cfg.scheduling,
        sync_interval=float(cfg.central.sync_interval),
        collector_id=cfg.collector_id,
    )

    # ── Work stealer ──────────────────────────────────────────────────────────
    work_stealer = WorkStealer(
        node_id=node_id,
        scheduler=scheduler,
        membership=membership,
        channel_pool=channel_pool,
        config=cfg.work_stealing,
    )

    # ── Distributed cache ─────────────────────────────────────────────────────
    dist_cache = DistributedCache(
        node_id=node_id,
        local_cache=local_cache,
        channel_pool=channel_pool,
        hash_ring=hash_ring,
        membership=membership,
        replication_factor=cfg.cluster.replication_factor,
        remote_cache_ttl=cfg.cache.remote_cache_ttl,
    )

    # ── Gossip ────────────────────────────────────────────────────────────────
    gossip = GossipProtocol(
        node_id=node_id,
        membership=membership,
        channel_pool=channel_pool,
        hash_ring=hash_ring,
        get_load_info=scheduler.get_current_load_info,
        gossip_interval=cfg.cluster.gossip_interval,
        suspicion_timeout=cfg.cluster.suspicion_timeout,
    )

    # ── gRPC server ───────────────────────────────────────────────────────────
    servicer = CollectorPeerServicer(
        local_cache=local_cache,
        distributed_cache=dist_cache,
        membership=membership,
        gossip=gossip,
        job_scheduler=scheduler,
        credential_manager=credential_manager,
        app_manager=None,   # cache-node doesn't run apps
        work_stealer=work_stealer,
        node_id=node_id,
    )
    grpc_server = await start_server(servicer, listen_addr)
    logger.info("grpc_server_started", address=listen_addr)

    # ── Wait for central ──────────────────────────────────────────────────────
    await central_client.wait_for_central(max_wait=120, check_interval=5)

    # ── Status HTTP server (port 50052) ───────────────────────────────────────
    status_server = await _start_status_server(
        node_id=node_id,
        membership=membership,
        scheduler=scheduler,
        port=int(os.environ.get("MONCTL_STATUS_PORT", "50052")),
    )

    # ── Start background tasks ────────────────────────────────────────────────
    await scheduler.start()
    await gossip.start()
    await work_stealer.start()
    asyncio.create_task(_cache_cleanup_loop(local_cache, cfg.cache.cleanup_interval))
    asyncio.create_task(_heartbeat_loop(central_client, node_id, scheduler, membership, advertise_addr))
    if cfg.collector_id and cfg.collector_api_key:
        asyncio.create_task(_peer_refresh_loop(
            central_client, node_id, cfg.collector_id, cfg.collector_api_key,
            membership, hash_ring,
        ))

    logger.info("cache_node_ready", node_id=node_id)

    # ── Shutdown handler ──────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("cache_node_shutting_down")
    await gossip.stop()
    await scheduler.stop()
    await work_stealer.stop()
    if status_server:
        await status_server.cleanup()
    grpc_server.stop(grace=5)
    await central_client.close()
    await local_cache.close()
    await channel_pool.close_all()
    logger.info("cache_node_stopped")


async def _start_status_server(
    node_id: str,
    membership: MembershipTable,
    scheduler: JobScheduler,
    port: int = 50052,
) -> web.AppRunner | None:
    """Start a lightweight HTTP server on port 50052 for TUI status queries."""
    try:
        app = web.Application()

        async def _handle_status(request: web.Request) -> web.Response:
            members = []
            for mid, info in membership.members.items():
                members.append({
                    "node_id": mid,
                    "address": info.address,
                    "status": info.status.name if hasattr(info.status, "name") else str(info.status),
                })

            load_info = scheduler.get_current_load_info()
            body = {
                "node_id": node_id,
                "membership": members,
                "load": {
                    "total_jobs": load_info.total_jobs,
                    "load_score": load_info.load_score,
                },
            }
            return web.Response(
                text=json.dumps(body),
                content_type="application/json",
            )

        app.router.add_get("/status", _handle_status)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("status_server_started", port=port)
        return runner
    except Exception as exc:
        logger.warning("status_server_failed", error=str(exc))
        return None


async def _discover_peers_from_central(
    central_client: CentralAPIClient,
    node_id: str,
    collector_id: str,
    collector_api_key: str,
) -> list[dict]:
    """Fetch peer info from central config endpoint.

    Returns list of {"node_id": ..., "address": ...} dicts.
    Only returns peers in the same collector group.
    """
    config = await central_client.get_config(collector_id, collector_api_key)
    cluster_info = config.get("data", {}).get("cluster")
    if cluster_info and "peers" in cluster_info:
        return cluster_info["peers"]
    return []


async def _heartbeat_loop(
    central_client: CentralAPIClient,
    node_id: str,
    scheduler: JobScheduler,
    membership: MembershipTable,
    peer_address: str,
    interval: int = 30,
) -> None:
    """Send periodic heartbeats to central so the collector stays ACTIVE."""
    while True:
        try:
            load_info = dataclasses.asdict(scheduler.get_current_load_info())
            # Report peer states so central can track group health
            peer_states = {
                m.node_id: m.status.value
                for m in membership.get_all()
                if m.node_id != node_id
            }
            ok = await central_client.post_heartbeat(
                node_id, load_info, peer_address=peer_address,
                peer_states=peer_states if peer_states else None,
            )
            if ok:
                logger.debug("heartbeat_sent", node_id=node_id)
            else:
                logger.warning("heartbeat_rejected", node_id=node_id)
        except Exception as exc:
            logger.warning("heartbeat_error", error=str(exc))
        await asyncio.sleep(interval)


async def _peer_refresh_loop(
    central_client: CentralAPIClient,
    node_id: str,
    collector_id: str,
    collector_api_key: str,
    membership: MembershipTable,
    hash_ring: HashRing,
    interval: int = 60,
) -> None:
    """Periodically fetch peers from central and update membership.

    This ensures that when collectors are added/removed from a group,
    gossip membership is updated automatically.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            peers = await _discover_peers_from_central(
                central_client, node_id, collector_id, collector_api_key
            )
            central_peer_ids = set()
            for peer_info in peers:
                peer_id = peer_info.get("node_id", "")
                peer_addr = peer_info.get("address", "")
                if peer_id and peer_addr and peer_id != node_id:
                    central_peer_ids.add(peer_id)
                    if peer_id not in membership.members:
                        membership.add_seed(peer_id, peer_addr)
                        hash_ring.add_node(peer_id)
                        logger.info("peer_added_from_central", peer_id=peer_id, address=peer_addr)

            # Remove peers no longer in our group
            for mid in list(membership.members):
                if mid == node_id:
                    continue
                if central_peer_ids and mid not in central_peer_ids:
                    if mid in hash_ring._nodes:
                        hash_ring.remove_node(mid)
                    membership.remove(mid)
                    logger.info("peer_removed", peer_id=mid, reason="not_in_group")

            if peers:
                logger.debug("peer_refresh_complete", peers=len(peers))
        except Exception as exc:
            logger.warning("peer_refresh_error", error=str(exc))


async def _cache_cleanup_loop(cache: LocalCache, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            deleted = await cache.cleanup_expired()
            if deleted:
                logger.debug("cache_cleanup", deleted=deleted)
        except Exception as exc:
            logger.warning("cache_cleanup_error", error=str(exc))


def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
