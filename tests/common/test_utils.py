"""Tests for shared utility functions."""

from __future__ import annotations

from monctl_common.constants import COLLECTOR_KEY_PREFIX, MANAGEMENT_KEY_PREFIX
from monctl_common.utils import generate_api_key, hash_api_key, key_prefix_display


def test_generate_collector_key():
    key = generate_api_key(COLLECTOR_KEY_PREFIX)
    assert key.startswith("monctl_c_")
    assert len(key) == len("monctl_c_") + 32


def test_generate_management_key():
    key = generate_api_key(MANAGEMENT_KEY_PREFIX)
    assert key.startswith("monctl_m_")


def test_keys_are_unique():
    keys = {generate_api_key(COLLECTOR_KEY_PREFIX) for _ in range(100)}
    assert len(keys) == 100


def test_hash_api_key():
    key = "monctl_c_abc123"
    h = hash_api_key(key)
    assert len(h) == 64  # SHA-256 hex digest
    assert hash_api_key(key) == h  # Deterministic


def test_key_prefix_display():
    key = "monctl_c_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    display = key_prefix_display(key)
    assert display.startswith("monctl_c_")
    assert len(display) < len(key)
