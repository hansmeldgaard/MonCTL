"""Cluster membership table — SWIM-style failure detection state machine.

Each node tracks the status of every other node in the cluster:
  ALIVE     — node is responding normally
  SUSPECTED — direct ping failed; waiting for indirect probe result
  DEAD      — indirect probe also failed; node is removed from the ring

The membership table is merged via gossip: the node with the higher
generation number always wins (prevents stale data from overwriting fresh).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class MemberStatus(str, Enum):
    ALIVE = "ALIVE"
    SUSPECTED = "SUSPECTED"
    DEAD = "DEAD"


@dataclass
class MemberInfo:
    node_id: str
    address: str                    # host:port for gRPC
    status: MemberStatus = MemberStatus.ALIVE
    generation: int = 0             # incremented on restart; higher wins during merge
    last_seen: float = field(default_factory=time.time)
    load_info: dict = field(default_factory=dict)  # NodeLoadInfo as dict


class MemberEvent(NamedTuple):
    """A state transition that occurred during a membership merge."""
    node_id: str
    old_status: MemberStatus
    new_status: MemberStatus


class MembershipTable:
    """Thread-safe (asyncio-compatible) SWIM membership state machine."""

    def __init__(self, local_node_id: str) -> None:
        self._local_id = local_node_id
        self._members: dict[str, MemberInfo] = {}

    @property
    def members(self) -> dict[str, MemberInfo]:
        return self._members

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def add_local(self, address: str, generation: int = 0) -> None:
        """Register the local node (always ALIVE).

        Uses a time-based generation so that restarts are detected by peers
        and the ALIVE status propagates via gossip even if the node was
        previously declared DEAD.
        """
        self._members[self._local_id] = MemberInfo(
            node_id=self._local_id,
            address=address,
            status=MemberStatus.ALIVE,
            generation=generation or int(time.time()),
            last_seen=time.time(),
        )

    def add_seed(self, node_id: str, address: str) -> None:
        """Add a seed peer (initially ALIVE — will be confirmed via gossip)."""
        if node_id not in self._members:
            self._members[node_id] = MemberInfo(
                node_id=node_id,
                address=address,
                status=MemberStatus.ALIVE,
                generation=0,
                last_seen=time.time(),  # use current time so suspect expiry doesn't trigger immediately
            )

    # ── Merge (gossip) ────────────────────────────────────────────────────────

    def merge(self, remote_members: list[dict]) -> list[MemberEvent]:
        """Merge incoming gossip member list into local state.

        Higher generation wins. For same generation, DEAD > SUSPECTED > ALIVE
        (pessimistic: trust bad news).

        Returns a list of MemberEvent for state transitions that occurred.
        """
        events: list[MemberEvent] = []
        _STATUS_RANK = {
            MemberStatus.ALIVE: 0,
            MemberStatus.SUSPECTED: 1,
            MemberStatus.DEAD: 2,
        }

        for r in remote_members:
            node_id = r["node_id"]
            if node_id == self._local_id:
                continue  # Never update our own entry from remote gossip

            remote_status = MemberStatus(r.get("status", "ALIVE"))
            remote_gen = int(r.get("generation", 0))
            remote_addr = r.get("address", "")
            remote_load = r.get("load_info", {})
            remote_last_seen = float(r.get("last_seen", time.time()))

            existing = self._members.get(node_id)

            if existing is None:
                # New node — add it
                self._members[node_id] = MemberInfo(
                    node_id=node_id,
                    address=remote_addr,
                    status=remote_status,
                    generation=remote_gen,
                    last_seen=remote_last_seen,
                    load_info=remote_load,
                )
                if remote_status != MemberStatus.DEAD:
                    events.append(MemberEvent(node_id, MemberStatus.DEAD, remote_status))
            else:
                # Always update load info from gossip (it's auxiliary data
                # that should flow freely regardless of status changes)
                if remote_load:
                    existing.load_info = remote_load

                # Apply status/generation update if remote has higher generation,
                # or same gen + worse status
                if remote_gen > existing.generation or (
                    remote_gen == existing.generation
                    and _STATUS_RANK[remote_status] > _STATUS_RANK[existing.status]
                ):
                    old = existing.status
                    existing.status = remote_status
                    existing.generation = remote_gen
                    existing.address = remote_addr or existing.address
                    existing.last_seen = max(existing.last_seen, remote_last_seen)
                    if old != remote_status:
                        events.append(MemberEvent(node_id, old, remote_status))

        return events

    # ── Local state updates ───────────────────────────────────────────────────

    def mark_alive(self, node_id: str, address: str = "", generation: int | None = None) -> None:
        member = self._members.get(node_id)
        if member is None:
            self._members[node_id] = MemberInfo(
                node_id=node_id,
                address=address,
                status=MemberStatus.ALIVE,
                generation=generation or 0,
            )
        else:
            member.status = MemberStatus.ALIVE
            member.last_seen = time.time()
            if address:
                member.address = address
            if generation is not None:
                member.generation = max(member.generation, generation)

    def mark_suspected(self, node_id: str) -> None:
        member = self._members.get(node_id)
        if member and member.status == MemberStatus.ALIVE:
            member.status = MemberStatus.SUSPECTED
            member.last_seen = time.time()  # record suspicion start for timeout

    def remove(self, node_id: str) -> None:
        """Remove a node entirely from the membership table."""
        self._members.pop(node_id, None)

    def mark_dead(self, node_id: str) -> None:
        member = self._members.get(node_id)
        if member:
            member.status = MemberStatus.DEAD

    def update_load(self, node_id: str, load_info: dict) -> None:
        member = self._members.get(node_id)
        if member:
            member.load_info = load_info
            member.last_seen = time.time()

    def update_local_load(self, load_info: dict) -> None:
        self.update_load(self._local_id, load_info)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_alive(self) -> list[MemberInfo]:
        """Return all members currently in ALIVE status."""
        return [m for m in self._members.values() if m.status == MemberStatus.ALIVE]

    def get_suspected(self) -> list[MemberInfo]:
        return [m for m in self._members.values() if m.status == MemberStatus.SUSPECTED]

    def get_all(self) -> list[MemberInfo]:
        return list(self._members.values())

    def get(self, node_id: str) -> MemberInfo | None:
        return self._members.get(node_id)

    def get_random_peer(self, exclude: str | None = None) -> MemberInfo | None:
        """Return a random ALIVE peer, excluding `exclude` (usually local node)."""
        peers = [
            m for m in self._members.values()
            if m.status == MemberStatus.ALIVE and m.node_id != (exclude or self._local_id)
        ]
        return random.choice(peers) if peers else None

    def get_k_random_peers(self, k: int, exclude: str | None = None) -> list[MemberInfo]:
        """Return up to k distinct ALIVE peers for indirect probing."""
        peers = [
            m for m in self._members.values()
            if m.status == MemberStatus.ALIVE and m.node_id != (exclude or self._local_id)
        ]
        return random.sample(peers, min(k, len(peers)))

    def get_all_load_info(self) -> list[dict]:
        """Return load info for all known alive nodes."""
        return [
            {"node_id": m.node_id, **m.load_info}
            for m in self._members.values()
            if m.status == MemberStatus.ALIVE
        ]

    def to_gossip_list(self) -> list[dict]:
        """Serialize all members for inclusion in a GossipMessage."""
        return [
            {
                "node_id": m.node_id,
                "address": m.address,
                "status": m.status.value,
                "generation": m.generation,
                "last_seen": m.last_seen,
                "load_info": m.load_info,
            }
            for m in self._members.values()
        ]

    def check_suspects(self, suspicion_timeout: float) -> list[str]:
        """Return node_ids that have been SUSPECTED longer than suspicion_timeout.

        Called by the gossip protocol to decide when to mark a node DEAD.
        """
        now = time.time()
        timed_out = []
        for m in self._members.values():
            if m.status == MemberStatus.SUSPECTED:
                if now - m.last_seen > suspicion_timeout:
                    timed_out.append(m.node_id)
        return timed_out
