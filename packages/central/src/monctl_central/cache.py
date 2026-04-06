"""Redis caching layer for frequently accessed data.

Caches:
- API key validation (avoid DB lookup + last_used_at UPDATE per request)
- Credential lookups (5 min TTL)
- Assignment enrichment (device_name, app_name, role, tenant_id per assignment_id)

Supports Redis Sentinel for HA (automatic failover). Falls back to direct
redis_url when Sentinel is not configured (local dev).
"""

from __future__ import annotations

import json
import logging
import time as _time
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis(
    redis_url: str,
    sentinel_hosts: str = "",
    sentinel_master: str = "monctl-redis",
) -> aioredis.Redis:
    """Get or create the shared Redis connection.

    If sentinel_hosts is provided, uses Sentinel discovery for automatic failover.
    Otherwise falls back to direct redis_url connection (local dev).
    """
    global _redis
    if _redis is not None:
        return _redis

    if sentinel_hosts:
        sentinels = []
        for entry in sentinel_hosts.split(","):
            entry = entry.strip()
            if ":" in entry:
                host, port = entry.rsplit(":", 1)
                sentinels.append((host, int(port)))
            else:
                sentinels.append((entry, 26379))

        sentinel = aioredis.sentinel.Sentinel(
            sentinels,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            decode_responses=True,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        _redis = sentinel.master_for(sentinel_master)
        logger.info(
            "redis_sentinel_connected sentinels=%s master=%s",
            sentinel_hosts, sentinel_master,
        )
    else:
        _redis = aioredis.from_url(
            redis_url,
            max_connections=50,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        logger.info("redis_direct_connected url=%s", redis_url)

    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def redis_healthy() -> bool:
    """Quick check if Redis is reachable. Used by health endpoint."""
    if _redis is None:
        return False
    try:
        import asyncio
        await asyncio.wait_for(_redis.ping(), timeout=2.0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# In-process API key cache — survives Redis failover (per-process, not shared)
# ---------------------------------------------------------------------------

_LOCAL_API_KEY_CACHE: dict[str, tuple[dict, float]] = {}
_LOCAL_CACHE_MAX = 500
_LOCAL_CACHE_TTL = 60  # 1 minute — shorter than Redis TTL for safety


def _get_local_api_key(key_hash: str) -> dict | None:
    entry = _LOCAL_API_KEY_CACHE.get(key_hash)
    if entry is None:
        return None
    data, ts = entry
    if _time.monotonic() - ts > _LOCAL_CACHE_TTL:
        del _LOCAL_API_KEY_CACHE[key_hash]
        return None
    return data


def _set_local_api_key(key_hash: str, data: dict) -> None:
    if len(_LOCAL_API_KEY_CACHE) >= _LOCAL_CACHE_MAX:
        sorted_keys = sorted(
            _LOCAL_API_KEY_CACHE.keys(),
            key=lambda k: _LOCAL_API_KEY_CACHE[k][1],
        )
        for k in sorted_keys[: _LOCAL_CACHE_MAX // 10]:
            del _LOCAL_API_KEY_CACHE[k]
    _LOCAL_API_KEY_CACHE[key_hash] = (data, _time.monotonic())


# ---------------------------------------------------------------------------
# API Key cache — avoid DB lookup + UPDATE last_used_at on every request
# ---------------------------------------------------------------------------

_API_KEY_PREFIX = "apikey:"
_API_KEY_TTL = 300  # 5 minutes


async def get_cached_api_key(key_hash: str) -> dict | None:
    # Level 1: Redis
    if _redis is not None:
        try:
            cached = await _redis.get(f"{_API_KEY_PREFIX}{key_hash}")
            if cached:
                data = json.loads(cached)
                _set_local_api_key(key_hash, data)
                return data
        except Exception:
            logger.debug("redis_cache_miss", exc_info=True)

    # Level 2: In-process fallback (survives Redis failover)
    local = _get_local_api_key(key_hash)
    if local is not None:
        return local

    return None


async def set_cached_api_key(key_hash: str, data: dict) -> None:
    _set_local_api_key(key_hash, data)  # Always populate local cache
    if _redis is None:
        return
    try:
        await _redis.setex(f"{_API_KEY_PREFIX}{key_hash}", _API_KEY_TTL, json.dumps(data))
    except Exception:
        logger.debug("redis_cache_set_failed", exc_info=True)


async def delete_cached_api_key(key_hash: str) -> None:
    """Remove a cached API key entry (called on revocation)."""
    _LOCAL_API_KEY_CACHE.pop(key_hash, None)
    if _redis is None:
        return
    try:
        await _redis.delete(f"{_API_KEY_PREFIX}{key_hash}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Credential cache
# ---------------------------------------------------------------------------

_CRED_PREFIX = "cred:"
_CRED_TTL = 300  # 5 minutes


async def get_cached_credential(name: str) -> dict | None:
    if _redis is None:
        return None
    try:
        cached = await _redis.get(f"{_CRED_PREFIX}{name}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def set_cached_credential(name: str, data: dict) -> None:
    if _redis is None:
        return
    try:
        await _redis.setex(f"{_CRED_PREFIX}{name}", _CRED_TTL, json.dumps(data))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Assignment enrichment cache (device_name, app_name, role, tenant_id)
# ---------------------------------------------------------------------------

_ENRICH_PREFIX = "enrich:"
_ENRICH_TTL = 600  # 10 minutes — assignments change rarely


async def get_cached_enrichment(assignment_id: str) -> dict | None:
    if _redis is None:
        return None
    try:
        cached = await _redis.get(f"{_ENRICH_PREFIX}{assignment_id}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def set_cached_enrichment(assignment_id: str, data: dict) -> None:
    if _redis is None:
        return
    try:
        await _redis.setex(
            f"{_ENRICH_PREFIX}{assignment_id}", _ENRICH_TTL, json.dumps(data)
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Interface identity cache (stable interface_id resolution)
# ---------------------------------------------------------------------------

_IFACE_ID_PREFIX = "iface-id:"
_IFACE_ID_TTL = 3600  # 1 hour


async def get_cached_interface_id(device_id: str, if_name: str) -> dict | None:
    if _redis is None:
        return None
    try:
        cached = await _redis.get(f"{_IFACE_ID_PREFIX}{device_id}:{if_name}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def set_cached_interface_id(
    device_id: str, if_name: str, data: dict,
) -> None:
    if _redis is None:
        return
    try:
        await _redis.setex(
            f"{_IFACE_ID_PREFIX}{device_id}:{if_name}", _IFACE_ID_TTL, json.dumps(data),
        )
    except Exception:
        pass


async def invalidate_cached_interface(device_id: str, if_name: str) -> None:
    """Remove cached interface entry so polling_enabled changes take effect immediately."""
    if _redis is None:
        return
    try:
        await _redis.delete(f"{_IFACE_ID_PREFIX}{device_id}:{if_name}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Interface previous counter cache (for rate calculation)
# ---------------------------------------------------------------------------

_IFACE_PREV_PREFIX = "iface-prev:"
_IFACE_PREV_TTL = 7200  # 2 hours — must exceed the longest practical poll interval


async def get_previous_counters(interface_id: str) -> dict | None:
    """Get previous counter values from Redis cache, falling back to ClickHouse interface_latest."""
    if _redis is not None:
        try:
            cached = await _redis.get(f"{_IFACE_PREV_PREFIX}{interface_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # ClickHouse fallback — query interface_latest for the most recent row
    try:
        import asyncio
        from monctl_central.dependencies import get_clickhouse
        ch = get_clickhouse()
        if ch:
            rows = await asyncio.to_thread(
                ch._get_client().query,
                "SELECT in_octets, out_octets, executed_at "
                "FROM interface_latest FINAL "
                "WHERE interface_id = {interface_id:String} "
                "LIMIT 1",
                parameters={"interface_id": interface_id},
            )
            named = list(rows.named_results())
            if named:
                ea = named[0]["executed_at"]
                prev = {
                    "in_octets": named[0]["in_octets"],
                    "out_octets": named[0]["out_octets"],
                    "executed_at": ea.isoformat() if hasattr(ea, "isoformat") else str(ea),
                }
                # Re-populate Redis cache for next poll
                if _redis is not None:
                    try:
                        await _redis.setex(
                            f"{_IFACE_PREV_PREFIX}{interface_id}",
                            _IFACE_PREV_TTL,
                            json.dumps(prev),
                        )
                    except Exception:
                        pass
                return prev
    except Exception:
        pass

    return None


async def cache_current_counters(
    interface_id: str, in_octets: int, out_octets: int, executed_at_iso: str,
) -> None:
    if _redis is None:
        return
    try:
        data = {
            "in_octets": in_octets,
            "out_octets": out_octets,
            "executed_at": executed_at_iso,
        }
        await _redis.setex(
            f"{_IFACE_PREV_PREFIX}{interface_id}", _IFACE_PREV_TTL, json.dumps(data),
        )
    except Exception:
        pass


async def get_previous_counters_batch(
    interface_ids: list[str],
) -> dict[str, dict | None]:
    """Fetch previous counters for multiple interfaces in a single Redis pipeline.

    Returns: {interface_id: counter_dict_or_None}
    """
    if not interface_ids:
        return {}

    result: dict[str, dict | None] = {iid: None for iid in interface_ids}
    cache_misses: list[str] = []

    if _redis is not None:
        try:
            pipe = _redis.pipeline(transaction=False)
            for iid in interface_ids:
                pipe.get(f"{_IFACE_PREV_PREFIX}{iid}")
            raw_values = await pipe.execute()

            for iid, raw in zip(interface_ids, raw_values):
                if raw is not None:
                    result[iid] = json.loads(raw)
                else:
                    cache_misses.append(iid)
        except Exception:
            logger.exception("redis_pipeline_get_error")
            cache_misses = list(interface_ids)
    else:
        cache_misses = list(interface_ids)

    # ClickHouse fallback for cache misses
    if cache_misses:
        try:
            import asyncio as _aio
            from monctl_central.dependencies import get_clickhouse
            ch = get_clickhouse()
            if ch:
                placeholders = ", ".join(f"'{iid}'" for iid in cache_misses)
                sql = (
                    "SELECT toString(interface_id) AS interface_id, "
                    "in_octets, out_octets, executed_at "
                    "FROM interface_latest FINAL "
                    f"WHERE interface_id IN ({placeholders})"
                )
                rows = await _aio.to_thread(ch._get_client().query, sql)
                ch_results = {
                    r["interface_id"]: r for r in rows.named_results()
                }

                backfill_pipe = (
                    _redis.pipeline(transaction=False) if _redis else None
                )
                for iid in cache_misses:
                    row = ch_results.get(iid)
                    if row:
                        ea = row["executed_at"]
                        prev = {
                            "in_octets": row["in_octets"],
                            "out_octets": row["out_octets"],
                            "executed_at": (
                                ea.isoformat()
                                if hasattr(ea, "isoformat")
                                else str(ea)
                            ),
                        }
                        result[iid] = prev
                        if backfill_pipe:
                            backfill_pipe.setex(
                                f"{_IFACE_PREV_PREFIX}{iid}",
                                _IFACE_PREV_TTL,
                                json.dumps(prev),
                            )
                if backfill_pipe:
                    try:
                        await backfill_pipe.execute()
                    except Exception:
                        pass
        except Exception:
            logger.exception("ch_fallback_batch_error")

    return result


async def cache_current_counters_batch(entries: list[dict]) -> None:
    """Cache current counters for multiple interfaces in a single Redis pipeline.

    Each entry: {"interface_id": str, "in_octets": int, "out_octets": int, "executed_at_iso": str}
    """
    if _redis is None or not entries:
        return
    try:
        pipe = _redis.pipeline(transaction=False)
        for e in entries:
            data = json.dumps({
                "in_octets": e["in_octets"],
                "out_octets": e["out_octets"],
                "executed_at": e["executed_at_iso"],
            })
            pipe.setex(
                f"{_IFACE_PREV_PREFIX}{e['interface_id']}",
                _IFACE_PREV_TTL,
                data,
            )
        await pipe.execute()
    except Exception:
        logger.exception("redis_pipeline_set_error")


async def get_or_load_enrichment(
    assignment_id: str,
    loader,
) -> dict[str, Any]:
    """Get enrichment from cache or load via async loader function.

    loader should be an async callable that returns a dict with
    device_name, app_name, role, tenant_id — or empty dict if not found.
    """
    cached = await get_cached_enrichment(assignment_id)
    if cached is not None:
        return cached
    data = await loader(assignment_id)
    if data:
        await set_cached_enrichment(assignment_id, data)
    return data or {}


# ---------------------------------------------------------------------------
# Interface metadata refresh flag
# ---------------------------------------------------------------------------

_IFACE_REFRESH_PREFIX = "iface-refresh:"


async def set_interface_refresh_flag(device_id: str, ttl: int = 600) -> None:
    """Signal that the next interface poll for this device should do a full walk."""
    if _redis:
        await _redis.set(f"{_IFACE_REFRESH_PREFIX}{device_id}", "1", ex=ttl)


async def get_and_clear_interface_refresh_flag(device_id: str) -> bool:
    """Check and atomically clear the refresh flag. Returns True if flag was set."""
    if _redis:
        result = await _redis.getdel(f"{_IFACE_REFRESH_PREFIX}{device_id}")
        return result is not None
    return False


# ---------------------------------------------------------------------------
# SNMP discovery flag
# ---------------------------------------------------------------------------

_DISCOVERY_PREFIX = "discovery:pending:"


async def set_discovery_flag(device_id: str, ttl: int = 600) -> None:
    """Set a flag requesting SNMP discovery for a device.

    The flag is consumed by the collector API's job-fetch endpoint,
    which injects a one-shot snmp_discovery job for this device.
    TTL ensures stale flags expire if never consumed (10 min default).
    """
    if _redis:
        await _redis.set(f"{_DISCOVERY_PREFIX}{device_id}", "1", ex=ttl)


async def get_and_clear_discovery_flag(device_id: str) -> bool:
    """Check and atomically clear the discovery flag.

    Returns True if the flag was set (discovery should be triggered).
    Uses GETDEL for atomic check-and-clear — only one collector picks it up.
    """
    if _redis:
        key = f"{_DISCOVERY_PREFIX}{device_id}"
        try:
            result = await _redis.get(key)
        except Exception as exc:
            logger.warning("discovery_flag_get_error", device_id=device_id, error=str(exc))
            return False
        if result is not None:
            await _redis.delete(key)
            logger.debug("discovery_flag_consumed", device_id=device_id)
            return True
    else:
        logger.warning("discovery_flag_no_redis")
    return False


_DISCOVERY_PHASE2_PREFIX = "discovery:phase2:"
_ELIGIBILITY_RUN_PREFIX = "eligibility:run:"


async def set_discovery_phase2_flag(device_id: str) -> bool:
    """Set phase-2 discovery flag (NX — only if not already set).

    Prevents infinite discovery loops by ensuring phase 2 runs at most once.
    Returns True if the flag was newly set, False if already present.
    """
    if _redis:
        result = await _redis.set(
            f"{_DISCOVERY_PHASE2_PREFIX}{device_id}", "1", ex=600, nx=True,
        )
        return result is not None
    return False


async def clear_discovery_phase2_flag(device_id: str) -> None:
    """Clear the phase-2 flag after successful processing or for re-evaluation."""
    if _redis:
        await _redis.delete(f"{_DISCOVERY_PHASE2_PREFIX}{device_id}")


async def set_eligibility_run_for_device(device_id: str, run_id: str, app_id: str) -> None:
    """Link a device to an active eligibility run (TTL 10 min)."""
    if _redis:
        import json
        await _redis.set(
            f"{_ELIGIBILITY_RUN_PREFIX}{device_id}",
            json.dumps({"run_id": run_id, "app_id": app_id}),
            ex=600,
        )


async def get_eligibility_run_for_device(device_id: str) -> dict | None:
    """Get active eligibility run info for a device, if any."""
    if _redis:
        import json
        val = await _redis.get(f"{_ELIGIBILITY_RUN_PREFIX}{device_id}")
        if val:
            return json.loads(val)
    return None


# ---------------------------------------------------------------------------
# Eligibility OIDs per-device (for test-eligibility probe mode)
# ---------------------------------------------------------------------------

_ELIGIBILITY_OIDS_PREFIX = "eligibility:oids:"


async def set_eligibility_oids_for_device(device_id: str, oids: list[str]) -> None:
    """Store eligibility OIDs to probe for a device (TTL 10 min)."""
    if _redis:
        import json
        await _redis.set(
            f"{_ELIGIBILITY_OIDS_PREFIX}{device_id}",
            json.dumps(oids),
            ex=600,
        )


async def get_eligibility_oids_for_device(device_id: str) -> list[str] | None:
    """Get eligibility OIDs to probe for a device, consuming the key."""
    if _redis:
        import json
        val = await _redis.get(f"{_ELIGIBILITY_OIDS_PREFIX}{device_id}")
        if val:
            await _redis.delete(f"{_ELIGIBILITY_OIDS_PREFIX}{device_id}")
            return json.loads(val)
    return None


# ---------------------------------------------------------------------------
# Docker push cache (worker docker-stats → central via push)
# ---------------------------------------------------------------------------

_DOCKER_PUSH_PREFIX = "docker_push:"
_DOCKER_PUSH_TTL = 300      # 5 min — generous buffer for slow stats collection + missed pushes
_DOCKER_PUSH_IMG_TTL = 600  # 10 min — images pushed every 4th cycle (~60s)


async def store_docker_push(label: str, section: str, data) -> None:
    """Store a pushed docker-stats section in Redis."""
    if _redis is None:
        return
    ttl = _DOCKER_PUSH_IMG_TTL if section == "images" else _DOCKER_PUSH_TTL
    try:
        await _redis.setex(
            f"{_DOCKER_PUSH_PREFIX}{label}:{section}", ttl, json.dumps(data),
        )
    except Exception:
        logger.debug("docker_push_store_failed section=%s label=%s", section, label)


async def get_docker_push(label: str, section: str):
    """Retrieve pushed docker-stats section from Redis."""
    if _redis is None:
        return None
    try:
        cached = await _redis.get(f"{_DOCKER_PUSH_PREFIX}{label}:{section}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def get_pushed_docker_hosts() -> list[dict]:
    """Discover all worker hosts that have pushed docker-stats data recently."""
    if _redis is None:
        return []
    try:
        hosts = []
        cursor = "0"
        pattern = f"{_DOCKER_PUSH_PREFIX}*:_meta"
        while True:
            cursor, keys = await _redis.scan(cursor=cursor, match=pattern, count=50)
            for key in keys:
                raw = await _redis.get(key)
                if raw:
                    hosts.append(json.loads(raw))
            if cursor == 0 or cursor == "0":
                break
        return hosts
    except Exception:
        logger.debug("docker_push_scan_failed", exc_info=True)
        return []


async def append_docker_push_events(label: str, events: list[dict]) -> None:
    """Append events to a per-host Redis list, trimmed to 500."""
    if _redis is None or not events:
        return
    key = f"{_DOCKER_PUSH_PREFIX}{label}:event_list"
    try:
        pipe = _redis.pipeline()
        for ev in events:
            pipe.rpush(key, json.dumps(ev))
        pipe.ltrim(key, -500, -1)
        pipe.expire(key, _DOCKER_PUSH_TTL)
        await pipe.execute()
    except Exception:
        logger.debug("docker_push_events_append_failed label=%s", label)


async def get_docker_push_events(
    label: str, since: float = 0, limit: int = 100,
) -> list[dict]:
    """Read events from Redis list, filtered by timestamp."""
    if _redis is None:
        return []
    key = f"{_DOCKER_PUSH_PREFIX}{label}:event_list"
    try:
        raw_list = await _redis.lrange(key, 0, -1)
        events = [json.loads(r) for r in raw_list]
        if since > 0:
            events = [e for e in events if e.get("time", 0) >= since]
        return events[-limit:]
    except Exception:
        return []


async def append_docker_push_logs(label: str, logs: dict[str, list]) -> None:
    """Store log lines per container. Replaces previous buffer each push."""
    if _redis is None or not logs:
        return
    # Store as a single JSON blob — simpler than per-container keys
    key = f"{_DOCKER_PUSH_PREFIX}{label}:logs"
    try:
        # Merge with existing logs
        existing = await _redis.get(key)
        merged = json.loads(existing) if existing else {}
        for container, lines in logs.items():
            prev = merged.get(container, [])
            prev.extend(lines)
            merged[container] = prev[-500:]  # cap at 500 per container
        await _redis.setex(key, _DOCKER_PUSH_TTL, json.dumps(merged))
    except Exception:
        logger.debug("docker_push_logs_store_failed label=%s", label)


async def get_docker_push_logs(
    label: str, container: str, tail: int = 100,
) -> list[str]:
    """Read last N log lines for a container from Redis."""
    if _redis is None:
        return []
    key = f"{_DOCKER_PUSH_PREFIX}{label}:logs"
    try:
        raw = await _redis.get(key)
        if raw:
            all_logs = json.loads(raw)
            lines = all_logs.get(container, [])
            return lines[-tail:]
    except Exception:
        pass
    return []
