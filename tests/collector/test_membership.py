"""Tests for cluster membership tracking."""

from __future__ import annotations

import time

from monctl_collector.cluster.membership import MembershipTable, PeerState


def test_add_and_get_peer():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    peer = table.get_peer("node-1")
    assert peer is not None
    assert peer.address == "192.168.1.1"
    assert peer.state == PeerState.ALIVE


def test_mark_suspect():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    changed = table.mark_suspect("node-1")
    assert changed is True
    assert table.get_peer("node-1").state == PeerState.SUSPECT


def test_mark_dead():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    table.mark_suspect("node-1")
    changed = table.mark_dead("node-1")
    assert changed is True
    assert table.get_peer("node-1").state == PeerState.DEAD


def test_suspect_timeout():
    table = MembershipTable(suspect_timeout=0.1)  # 100ms for testing
    table.add_peer("node-1", "192.168.1.1", 9901)
    table.mark_suspect("node-1")

    # Not enough time has passed
    newly_dead = table.check_suspects()
    assert len(newly_dead) == 0

    # Wait for timeout
    time.sleep(0.15)
    newly_dead = table.check_suspects()
    assert "node-1" in newly_dead
    assert table.get_peer("node-1").state == PeerState.DEAD


def test_alive_recovery():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    table.mark_suspect("node-1")
    assert table.get_peer("node-1").state == PeerState.SUSPECT

    changed = table.mark_alive("node-1")
    assert changed is True
    assert table.get_peer("node-1").state == PeerState.ALIVE


def test_get_alive_peers():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    table.add_peer("node-2", "192.168.1.2", 9901)
    table.add_peer("node-3", "192.168.1.3", 9901)
    table.mark_dead("node-2")

    alive = table.get_alive_peers()
    alive_ids = [p.collector_id for p in alive]
    assert "node-1" in alive_ids
    assert "node-3" in alive_ids
    assert "node-2" not in alive_ids


def test_events_generated():
    table = MembershipTable()
    table.add_peer("node-1", "192.168.1.1", 9901)
    table.mark_suspect("node-1")
    table.mark_dead("node-1")

    events = table.get_recent_events()
    assert len(events) == 2
    assert events[0].state == PeerState.SUSPECT
    assert events[1].state == PeerState.DEAD
