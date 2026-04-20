"""Redis-based leader election for singleton tasks.

Uses SETNX + TTL to ensure only one Central API instance runs
the scheduler (health monitor + alert engine) at a time.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LEADER_KEY = "monctl:scheduler:leader"
_LEADER_TTL = 30  # seconds — must renew before this expires

# Atomic compare-and-renew: refresh TTL only if the key still holds our ID.
# Avoids the TOCTOU between GET and EXPIRE where another instance could
# acquire in between. Returns 1 if renewed, 0 if not ours.
_RENEW_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class LeaderElection:
    """Redis-based leader election using SETNX + TTL renewal."""

    def __init__(self, redis_client: aioredis.Redis, instance_id: str | None = None):
        self._redis = redis_client
        self._instance_id = instance_id or str(uuid.uuid4())[:12]
        self._is_leader = False
        self._task: asyncio.Task | None = None

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def start(self) -> asyncio.Task:
        """Start the leader election renewal loop."""
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Release leadership if we hold it — atomic compare-and-delete so we
        # don't wipe another instance's freshly-acquired key.
        if self._is_leader:
            try:
                await self._redis.eval(
                    'if redis.call("GET", KEYS[1]) == ARGV[1] then '
                    'return redis.call("DEL", KEYS[1]) else return 0 end',
                    1, _LEADER_KEY, self._instance_id,
                )
            except Exception:
                logger.warning("leader_release_failed instance_id=%s", self._instance_id)
            self._is_leader = False

    async def _run(self) -> None:
        while True:
            try:
                await self._try_acquire()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("leader_election_error")
            await asyncio.sleep(_LEADER_TTL // 3)

    async def _try_acquire(self) -> None:
        # Try to acquire or renew
        try:
            acquired = await self._redis.set(
                _LEADER_KEY, self._instance_id, nx=True, ex=_LEADER_TTL
            )
        except Exception as e:
            if self._is_leader:
                logger.warning(
                    "leader_redis_unreachable_during_leadership instance_id=%s error=%s",
                    self._instance_id, e,
                )
            self._is_leader = False
            raise  # Let outer loop handle retry

        if acquired:
            if not self._is_leader:
                logger.info("leader_acquired instance_id=%s", self._instance_id)
            self._is_leader = True
            return

        # Atomic compare-and-renew — only refresh TTL if the key still holds
        # our instance ID. Returns 1 if renewed, 0 if someone else is leader.
        renewed = await self._redis.eval(
            _RENEW_LUA, 1, _LEADER_KEY, self._instance_id, _LEADER_TTL
        )
        if renewed:
            self._is_leader = True
        else:
            if self._is_leader:
                logger.info("leader_lost instance_id=%s", self._instance_id)
            self._is_leader = False
