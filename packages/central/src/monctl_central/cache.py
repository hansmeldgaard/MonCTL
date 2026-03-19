"""Redis caching layer for frequently accessed data.

Caches:
- API key validation (avoid DB lookup + last_used_at UPDATE per request)
- Credential lookups (5 min TTL)
- Assignment enrichment (device_name, app_name, role, tenant_id per assignment_id)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis(redis_url: str) -> aioredis.Redis:
    """Get or create the shared Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


# ---------------------------------------------------------------------------
# API Key cache — avoid DB lookup + UPDATE last_used_at on every request
# ---------------------------------------------------------------------------

_API_KEY_PREFIX = "apikey:"
_API_KEY_TTL = 300  # 5 minutes


async def get_cached_api_key(key_hash: str) -> dict | None:
    if _redis is None:
        return None
    try:
        cached = await _redis.get(f"{_API_KEY_PREFIX}{key_hash}")
        if cached:
            return json.loads(cached)
    except Exception:
        logger.debug("redis_cache_miss", exc_info=True)
    return None


async def set_cached_api_key(key_hash: str, data: dict) -> None:
    if _redis is None:
        return
    try:
        await _redis.setex(f"{_API_KEY_PREFIX}{key_hash}", _API_KEY_TTL, json.dumps(data))
    except Exception:
        logger.debug("redis_cache_set_failed", exc_info=True)


async def delete_cached_api_key(key_hash: str) -> None:
    """Remove a cached API key entry (called on revocation)."""
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
