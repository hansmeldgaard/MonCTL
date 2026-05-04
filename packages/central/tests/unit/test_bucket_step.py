"""Tests for `_bucket_step_for_range` (T-X-006 / PR #141 regression cover).

`*_history` endpoints that return N rows per timestamp (one per
ingestion table per sample, one per host per sample, …) silently
truncated around 7 days of history when LIMIT 10000 hit. PR #141
introduced server-side ``toStartOfInterval`` bucketing keyed off
this helper; if its mapping ever drifts (1h returning 600 instead
of 60, say), every history endpoint quietly returns sparser data
without any error surface.

Per memory `feedback_per_row_multiplier_hits_limit`, the bucket
width must scale with the range so each series returns 250-400
rows — small enough to fit under the LIMIT, large enough to keep
chart resolution. Pin the documented thresholds:

    span <= 1h    -> 60s
    span <= 6h    -> 120s
    span <= 24h   -> 300s
    span >  24h   -> 1800s

Also: bucket >= 15s sidecar push interval so we never synthesize
detail we don't have.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from monctl_central.system.router import _bucket_step_for_range


_NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "span,expected_step",
    [
        (timedelta(minutes=15), 60),     # well under 1h
        (timedelta(hours=1), 60),        # exact 1h boundary
        (timedelta(hours=2), 120),       # 1h < span <= 6h
        (timedelta(hours=6), 120),       # exact 6h boundary
        (timedelta(hours=12), 300),      # 6h < span <= 24h
        (timedelta(hours=24), 300),      # exact 24h boundary
        (timedelta(days=7), 1800),       # > 24h tier
        (timedelta(days=30), 1800),      # well into long-range tier
    ],
)
def test_bucket_step_for_range_matches_documented_thresholds(
    span, expected_step
) -> None:
    assert _bucket_step_for_range(_NOW - span, _NOW) == expected_step


def test_bucket_step_returns_default_when_either_endpoint_is_none() -> None:
    """`from`/`to` are query-string-derived; either one being None
    (caller forgot a param) should yield the safe default of 300s."""
    assert _bucket_step_for_range(None, _NOW) == 300
    assert _bucket_step_for_range(_NOW, None) == 300
    assert _bucket_step_for_range(None, None) == 300


def test_bucket_step_floor_is_above_sidecar_push_interval() -> None:
    """The smallest tier (1h span -> 60s) must be >= 15s — the docker-stats
    sidecar push interval. Bucketing finer than the source data would
    just synthesize empty rows."""
    assert _bucket_step_for_range(_NOW - timedelta(minutes=10), _NOW) >= 15


def test_bucket_step_zero_or_negative_span_clamps_to_smallest_tier() -> None:
    """If `from_ts >= to_ts`, the span is clamped to >=1s — pick the
    finest tier rather than crashing."""
    assert _bucket_step_for_range(_NOW, _NOW) == 60
    assert _bucket_step_for_range(_NOW + timedelta(hours=1), _NOW) == 60


def test_bucket_step_just_over_thresholds_promotes_tier() -> None:
    """One-second past each threshold flips to the next tier — pin the
    boundary behavior so a future refactor doesn't accidentally invert
    `<=` vs `<` and double the row count on hour-aligned queries."""
    one_sec = timedelta(seconds=1)
    assert _bucket_step_for_range(
        _NOW - (timedelta(hours=1) + one_sec), _NOW
    ) == 120
    assert _bucket_step_for_range(
        _NOW - (timedelta(hours=6) + one_sec), _NOW
    ) == 300
    assert _bucket_step_for_range(
        _NOW - (timedelta(hours=24) + one_sec), _NOW
    ) == 1800
