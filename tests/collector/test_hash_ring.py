"""Tests for the consistent hash ring."""

from __future__ import annotations

from monctl_collector.cluster.hash_ring import ConsistentHashRing


def test_empty_ring():
    ring = ConsistentHashRing()
    assert ring.get_primary("test") is None
    assert ring.get_nodes_for_key("test") == []


def test_single_node():
    ring = ConsistentHashRing()
    ring.add_node("node-1")
    assert ring.get_primary("any-key") == "node-1"
    assert ring.node_count == 1


def test_two_nodes_distribution():
    ring = ConsistentHashRing(vnodes=150)
    ring.add_node("node-a")
    ring.add_node("node-b")

    # Both nodes should get some assignments
    primaries = {"node-a": 0, "node-b": 0}
    for i in range(1000):
        primary = ring.get_primary(f"assignment-{i}")
        primaries[primary] += 1

    # Each should get roughly 50% (with some tolerance)
    assert primaries["node-a"] > 300
    assert primaries["node-b"] > 300


def test_replication():
    ring = ConsistentHashRing()
    ring.add_node("node-1")
    ring.add_node("node-2")
    ring.add_node("node-3")

    nodes = ring.get_nodes_for_key("test-assignment", count=2)
    assert len(nodes) == 2
    assert nodes[0] != nodes[1]  # Primary and backup must be different


def test_node_removal_minimal_redistribution():
    ring = ConsistentHashRing(vnodes=150)
    ring.add_node("node-1")
    ring.add_node("node-2")
    ring.add_node("node-3")

    # Record assignments before removal
    assignments_before = {}
    for i in range(100):
        key = f"assignment-{i}"
        assignments_before[key] = ring.get_primary(key)

    # Remove one node
    ring.remove_node("node-2")

    # Check how many assignments changed
    changed = 0
    for i in range(100):
        key = f"assignment-{i}"
        new_primary = ring.get_primary(key)
        if assignments_before[key] != new_primary:
            changed += 1
            # Verify that only assignments that were on node-2 moved
            assert assignments_before[key] == "node-2"

    # Roughly 1/3 should have moved (those that were on node-2)
    assert changed > 0
    assert changed < 60  # Should be around 33


def test_get_my_assignments():
    ring = ConsistentHashRing(vnodes=150)
    ring.add_node("node-1")
    ring.add_node("node-2")
    ring.add_node("node-3")

    all_assignments = [f"assign-{i}" for i in range(30)]
    my_assignments = ring.get_my_assignments("node-1", all_assignments, replication_factor=2)

    # Should have some primary and some backup
    primaries = sum(1 for r in my_assignments.values() if r == "primary")
    backups = sum(1 for r in my_assignments.values() if r == "backup")
    assert primaries > 0
    assert backups > 0
    assert primaries + backups == len(my_assignments)


def test_add_remove_idempotent():
    ring = ConsistentHashRing()
    ring.add_node("node-1")
    ring.add_node("node-1")  # Duplicate add
    assert ring.node_count == 1

    ring.remove_node("node-1")
    ring.remove_node("node-1")  # Duplicate remove
    assert ring.node_count == 0
