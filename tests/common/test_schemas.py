"""Tests for monctl-common schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from monctl_common.constants import CheckState
from monctl_common.schemas.metrics import CheckResult, Event, IngestPayload, Metric


def test_metric_creation():
    m = Metric(name="cpu_percent", value=85.5, labels={"host": "web-01"}, unit="%")
    assert m.name == "cpu_percent"
    assert m.value == 85.5
    assert m.labels == {"host": "web-01"}
    assert m.unit == "%"
    assert m.timestamp is None


def test_metric_with_timestamp():
    ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    m = Metric(name="temp", value=22.3, timestamp=ts)
    assert m.timestamp == ts


def test_check_result_ok():
    result = CheckResult(
        state=CheckState.OK,
        output="Everything is fine",
        metrics=[Metric(name="response_time", value=0.5)],
    )
    assert result.state == CheckState.OK
    assert result.state == 0
    assert len(result.metrics) == 1


def test_check_result_critical():
    result = CheckResult(
        state=CheckState.CRITICAL,
        output="Service down",
        performance_data={"response_time": 30.0},
    )
    assert result.state == CheckState.CRITICAL
    assert result.state == 2
    assert result.performance_data["response_time"] == 30.0


def test_event_creation():
    event = Event(
        source="syslog",
        severity="warning",
        message="Disk usage above 90%",
        data={"disk": "/dev/sda1", "usage_percent": 92},
    )
    assert event.source == "syslog"
    assert event.severity == "warning"


def test_ingest_payload():
    payload = IngestPayload(
        collector_id="test-collector-1",
        timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC),
        sequence=42,
        app_results=[],
        events=[
            Event(source="test", severity="info", message="test event"),
        ],
    )
    assert payload.collector_id == "test-collector-1"
    assert payload.sequence == 42
    assert len(payload.events) == 1
