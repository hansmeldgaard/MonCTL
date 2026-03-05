"""Cluster membership state tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class PeerState(str, Enum):
    ALIVE = "ALIVE"
    SUSPECT = "SUSPECT"
    DEAD = "DEAD"


@dataclass
class PeerInfo:
    """Information about a peer in the cluster."""

    collector_id: str
    address: str
    port: int
    state: PeerState = PeerState.ALIVE
    last_seen: float = field(default_factory=time.time)
    suspect_since: float | None = None
    incarnation: int = 0  # Monotonic counter to resolve conflicts


@dataclass
class MembershipEvent:
    """A membership state change event for gossip dissemination."""

    collector_id: str
    state: PeerState
    incarnation: int
    timestamp: float = field(default_factory=time.time)


class MembershipTable:
    """Tracks the membership state of all peers in the cluster."""

    def __init__(self, suspect_timeout: float = 15.0):
        self.suspect_timeout = suspect_timeout
        self._peers: dict[str, PeerInfo] = {}
        self._recent_events: list[MembershipEvent] = []
        self._max_recent_events = 100

    def add_peer(self, collector_id: str, address: str, port: int) -> None:
        """Add or update a peer."""
        if collector_id in self._peers:
            peer = self._peers[collector_id]
            peer.address = address
            peer.port = port
        else:
            self._peers[collector_id] = PeerInfo(
                collector_id=collector_id,
                address=address,
                port=port,
            )

    def mark_alive(self, collector_id: str) -> bool:
        """Mark a peer as alive. Returns True if state changed."""
        peer = self._peers.get(collector_id)
        if peer is None:
            return False
        old_state = peer.state
        peer.state = PeerState.ALIVE
        peer.last_seen = time.time()
        peer.suspect_since = None
        if old_state != PeerState.ALIVE:
            self._add_event(MembershipEvent(
                collector_id=collector_id,
                state=PeerState.ALIVE,
                incarnation=peer.incarnation,
            ))
            return True
        return False

    def mark_suspect(self, collector_id: str) -> bool:
        """Mark a peer as suspect. Returns True if state changed."""
        peer = self._peers.get(collector_id)
        if peer is None:
            return False
        if peer.state == PeerState.DEAD:
            return False  # Don't go back from DEAD to SUSPECT
        old_state = peer.state
        if old_state != PeerState.SUSPECT:
            peer.state = PeerState.SUSPECT
            peer.suspect_since = time.time()
            self._add_event(MembershipEvent(
                collector_id=collector_id,
                state=PeerState.SUSPECT,
                incarnation=peer.incarnation,
            ))
            return True
        return False

    def mark_dead(self, collector_id: str) -> bool:
        """Mark a peer as dead. Returns True if state changed."""
        peer = self._peers.get(collector_id)
        if peer is None:
            return False
        old_state = peer.state
        if old_state != PeerState.DEAD:
            peer.state = PeerState.DEAD
            self._add_event(MembershipEvent(
                collector_id=collector_id,
                state=PeerState.DEAD,
                incarnation=peer.incarnation,
            ))
            return True
        return False

    def check_suspects(self) -> list[str]:
        """Check if any SUSPECT peers should be marked DEAD.

        Returns list of collector_ids that were promoted to DEAD.
        """
        now = time.time()
        newly_dead: list[str] = []
        for peer in self._peers.values():
            if (
                peer.state == PeerState.SUSPECT
                and peer.suspect_since is not None
                and (now - peer.suspect_since) >= self.suspect_timeout
            ):
                peer.state = PeerState.DEAD
                newly_dead.append(peer.collector_id)
                self._add_event(MembershipEvent(
                    collector_id=peer.collector_id,
                    state=PeerState.DEAD,
                    incarnation=peer.incarnation,
                ))
        return newly_dead

    def get_alive_peers(self) -> list[PeerInfo]:
        """Get all peers in ALIVE state."""
        return [p for p in self._peers.values() if p.state == PeerState.ALIVE]

    def get_all_peers(self) -> list[PeerInfo]:
        """Get all peers."""
        return list(self._peers.values())

    def get_peer(self, collector_id: str) -> PeerInfo | None:
        return self._peers.get(collector_id)

    def get_recent_events(self, since: float = 0) -> list[MembershipEvent]:
        """Get recent membership events since a given timestamp."""
        return [e for e in self._recent_events if e.timestamp > since]

    def apply_events(self, events: list[dict]) -> None:
        """Apply membership events received from gossip."""
        for event_data in events:
            collector_id = event_data["collector_id"]
            state = PeerState(event_data["state"])
            incarnation = event_data.get("incarnation", 0)

            peer = self._peers.get(collector_id)
            if peer is None:
                continue

            # Only apply if incarnation is >= current
            if incarnation < peer.incarnation:
                continue

            if state == PeerState.ALIVE:
                self.mark_alive(collector_id)
            elif state == PeerState.SUSPECT:
                self.mark_suspect(collector_id)
            elif state == PeerState.DEAD:
                self.mark_dead(collector_id)

    def _add_event(self, event: MembershipEvent) -> None:
        self._recent_events.append(event)
        if len(self._recent_events) > self._max_recent_events:
            self._recent_events = self._recent_events[-self._max_recent_events:]
