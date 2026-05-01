"""Redis-backed daily-rollup counters for silent-failure call sites.

Review #2 (O-X-003) flagged the cross-cutting "log on failure, never count"
pattern: every drop, every WS error, every silent-fallback path uses one-shot
``logger.warning`` calls and there is no way to ask "how many WS errors did
we have today?" without grepping logs across all 4 central nodes.

This module is the shared primitive — a single ``HINCRBY`` per increment,
keyed by UTC day so old data ages out automatically. ``incr`` is fire-and-
forget; failures (Redis down) are swallowed at debug level so a counter
miss never breaks the call site that's reporting the actual failure.

Usage::

    from monctl_central.observability.counters import incr, sum_recent

    # At the failure site:
    await incr("audit.dropped")

    # Reading recent days:
    rolled = await sum_recent("audit.dropped", days=7)

Daily keys live at ``monctl:counters:YYYY-MM-DD`` (Redis hashes), each
hash mapping ``counter_name -> count``. Each daily key has a 35-day TTL
applied on first INCRBY so the working set bounds itself even if no one
is reading the counters.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Working-set bound: keep ~5 weeks of daily counters, then drop. The
# /v1/observability/counters API only reads up to ``days`` back so anything
# longer would never be surfaced.
_TTL_SECONDS = 35 * 24 * 3600

_KEY_PREFIX = "monctl:counters:"


def _day_str(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%d")


def counter_keys_for(days: int = 7) -> list[str]:
    """Return the Redis hash keys covering the last ``days`` days, newest-first."""
    today = datetime.now(timezone.utc)
    return [
        f"{_KEY_PREFIX}{(today - timedelta(days=d)).strftime('%Y-%m-%d')}"
        for d in range(days)
    ]


async def incr(name: str, by: int = 1, *, day: str | None = None) -> None:
    """Increment ``name`` on today's daily-rollup hash by ``by``.

    Fire-and-forget: a Redis outage does NOT propagate. The caller is
    almost always already on a failure path and shouldn't have to think
    about the counter's success.
    """
    from monctl_central.cache import _redis

    if _redis is None:
        return
    key = f"{_KEY_PREFIX}{day or _day_str()}"
    try:
        await _redis.hincrby(key, name, by)
        # First increment of the day — ensure the hash ages out.
        # Subsequent EXPIREs are cheap and idempotent.
        await _redis.expire(key, _TTL_SECONDS)
    except Exception as exc:
        logger.debug("counter_incr_failed name=%s exc=%s", name, exc)


async def sum_recent(name: str, *, days: int = 1) -> int:
    """Sum ``name`` across the last ``days`` daily rollups.

    ``days=1`` returns just today's value (UTC). ``days=7`` returns the
    rolling 7-day total including today.
    """
    from monctl_central.cache import _redis

    if _redis is None:
        return 0
    total = 0
    for key in counter_keys_for(days):
        try:
            v = await _redis.hget(key, name)
        except Exception as exc:
            logger.debug("counter_sum_recent_failed name=%s exc=%s", name, exc)
            return total
        if v is None:
            continue
        try:
            total += int(v)
        except (TypeError, ValueError):
            continue
    return total


async def all_counters(*, days: int = 1, prefix: str = "") -> dict[str, int]:
    """Return ``{name: rolling_sum}`` for every counter touched in the window.

    Used by the ``/v1/observability/counters`` admin endpoint. Optional
    ``prefix`` filter so an operator can zoom into one subsystem (e.g.
    ``"audit."``).
    """
    from monctl_central.cache import _redis

    if _redis is None:
        return {}
    totals: dict[str, int] = {}
    for key in counter_keys_for(days):
        try:
            day_data = await _redis.hgetall(key)
        except Exception as exc:
            logger.debug("counter_all_failed key=%s exc=%s", key, exc)
            continue
        for raw_name, raw_count in (day_data or {}).items():
            name = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
            if prefix and not name.startswith(prefix):
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            totals[name] = totals.get(name, 0) + count
    return totals
