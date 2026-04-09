# MonCTL App Development Guide

This guide describes exactly how to build monitoring apps for MonCTL.
Follow it precisely — every section is load-bearing.

---

## What Is an App?

A MonCTL monitoring app is a Python class named `Poller` that subclasses `BasePoller`
and implements `async def poll()`. The collector engine:

1. Creates **one instance per (app_id, version)** and calls `setup()` once.
2. Calls `poll(context)` on a schedule (every `job.interval` seconds).
3. Calls `teardown()` on shutdown or when a new version is deployed.

Apps are **distributed inside pack JSON files** — the source code is embedded as a
string in the pack. Pack files live in `packs/` and are auto-imported at startup.

---

## BasePoller Interface

```python
# packages/collector/src/monctl_collector/polling/base.py

from abc import ABC, abstractmethod
from monctl_collector.jobs.models import PollContext, PollResult

class BasePoller(ABC):

    async def setup(self) -> None:
        """One-time init before the first poll. Override to cache expensive
        resources (MIB trees, TLS sessions, etc.). Default is a no-op."""

    @abstractmethod
    async def poll(self, context: PollContext) -> PollResult:
        """Execute the monitoring check and return a result.
        Any unhandled exception is caught by the engine and converted to
        a PollResult with status="error" and error_category="app"."""
        ...

    async def teardown(self) -> None:
        """Clean up on shutdown or version upgrade. Default is a no-op."""
```

In practice, nearly all apps only implement `poll()`.
Use `setup()` only for genuinely expensive one-time work (e.g. pre-loading a MIB).

---

## PollContext — What You Receive

```python
@dataclass
class PollContext:
    job: JobDefinition       # Full job definition (job_id, device_id, interval, …)
    credential: dict         # Merged decrypted credential dict ({} if none)
    node_id: str             # Collector hostname (e.g. "worker1")
    device_host: str         # Resolved device IP or hostname
    parameters: dict         # App config — all $credential: refs already substituted
    connectors: dict         # alias → connector instance (e.g. {"snmp": <SNMPConnector>})
    cache: AppCacheAccessor | None  # Shared KV store (rarely needed)
```

**Commonly used fields:**

| Field                             | What to use it for                                             |
| --------------------------------- | -------------------------------------------------------------- |
| `context.device_host`             | Target IP/hostname — prefer this over `parameters.get("host")` |
| `context.parameters`              | App-specific config values (from `config_schema`)              |
| `context.connectors.get("alias")` | Get a connector (e.g. SNMP, SSH)                               |
| `context.job.job_id`              | Required for all PollResult constructors                       |
| `context.job.device_id`           | Required for all PollResult constructors                       |
| `context.node_id`                 | Required for all PollResult constructors                       |

---

## PollResult — What You Return

```python
@dataclass
class PollResult:
    job_id: str                        # = context.job.job_id
    device_id: str | None              # = context.job.device_id
    collector_node: str                # = context.node_id
    timestamp: float                   # time.time() at result creation
    metrics: list[dict]                # List of metric dicts (see below)
    config_data: dict | None           # Discovered config (for target_table="config")
    status: str                        # "ok" | "warning" | "critical" | "unknown" | "error"
    reachable: bool                    # Whether target was reachable
    error_message: str | None          # Human-readable error (None on success)
    execution_time_ms: int             # Wall-clock time in ms
    started_at: float | None = None    # Rarely used
    rtt_ms: float | None = None        # Round-trip time in ms (optional)
    response_time_ms: float | None = None  # HTTP response time (optional)
    interface_rows: list[dict] | None = None  # Per-interface data (target_table="interface")
    error_category: str = ""           # MUST be set on all error results (see below)
```

### Metric dict format

```python
{"name": "metric_name", "value": 42.5}                           # minimal
{"name": "rtt_ms", "value": 3.14, "unit": "ms"}                  # with unit
{"name": "snmp_rtt_ms", "value": 3.14, "labels": {"host": host}} # with labels
```

`value` must be a `float`. Booleans: use `1.0` / `0.0`.

### target_table and what to put in metrics / special fields

| `target_table`           | Put data in      | Use case                             |
| ------------------------ | ---------------- | ------------------------------------ |
| `"availability_latency"` | `metrics`        | Ping, port, SNMP reachability, HTTP  |
| `"performance"`          | `metrics`        | Uptime, CPU, memory, temperature     |
| `"interface"`            | `interface_rows` | SNMP ifTable counters                |
| `"config"`               | `config_data`    | Discovery results, sysDescr, sysName |

---

## Error Categories — Critical Rule

**Every error PollResult MUST set `error_category`.** The engine auto-fills `"device"`
if omitted, but explicit is always correct.

| `error_category` | When to use                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| `"device"`       | Target unreachable, ping timeout, SNMP timeout, TCP refused                                             |
| `"config"`       | Missing connector (`connectors.get("snmp") is None`), missing required parameter, bad credential format |
| `"app"`          | Bug or crash in app logic (parse error, key error, logic failure)                                       |
| `""`             | No error — status is `"ok"`                                                                             |

---

## Timing Pattern

Always use `time.monotonic()` for elapsed time and `time.time()` for timestamps:

```python
start = time.monotonic()
try:
    # ... do the check ...
    elapsed_ms = (time.monotonic() - start) * 1000
    return PollResult(..., execution_time_ms=int(elapsed_ms), rtt_ms=elapsed_ms)
except SomeNetworkError as exc:
    elapsed_ms = (time.monotonic() - start) * 1000
    return PollResult(..., execution_time_ms=int(elapsed_ms), error_category="device")
```

---

## Connector Usage

Connectors (SNMP, SSH, etc.) are instantiated and connected by the engine before
`poll()` is called. **Apps must never call `connector.connect()`.**

```python
snmp = context.connectors.get("snmp")  # Returns None if not bound
if snmp is None:
    return PollResult(
        job_id=context.job.job_id,
        device_id=context.job.device_id,
        collector_node=context.node_id,
        timestamp=time.time(),
        metrics=[], config_data=None,
        status="error", reachable=False,
        error_message="No SNMP connector bound (expected alias 'snmp')",
        error_category="config",
        execution_time_ms=0,
    )

# SNMP connector methods:
result = await snmp.get([oid])                    # GET one or more OIDs → dict
rows   = await snmp.walk(oid_base)                # WALK subtree → list of (oid, value)
result = await snmp.get_many(list_of_oid_lists)   # Batched GET (falls back to individual gets)
```

Always guard with `if snmp is None` before using the connector.

---

## Complete App Examples

### Example 1: ping_check (no connector)

Source from `packs/basic-checks-v1.0.0.json`, `ping_check` v2.1.0:

```python
"""ICMP ping check — measures reachability and round-trip time."""
import asyncio
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        count = context.parameters.get("count", 3)
        timeout = context.parameters.get("timeout", 5)
        start = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", str(timeout), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout * count + 5
            )
            output = stdout.decode()
            execution_ms = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                rtt = self._parse_rtt(output)
                loss = self._parse_loss(output)
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[
                        {"name": "rtt_ms", "value": rtt},
                        {"name": "packet_loss_pct", "value": loss},
                    ],
                    config_data=None,
                    status="ok" if loss < 100 else "critical",
                    reachable=True,
                    error_message=None,
                    execution_time_ms=execution_ms,
                    rtt_ms=rtt,
                )
            else:
                detail = stderr.decode().strip() or "no response"
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "packet_loss_pct", "value": 100.0}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"Ping failed: {detail}",
                    execution_time_ms=execution_ms,
                    error_category="device",
                )
        except asyncio.TimeoutError:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Ping timed out after {timeout * count}s",
                execution_time_ms=execution_ms,
                error_category="device",
            )

    def _parse_rtt(self, output: str) -> float:
        for line in output.splitlines():
            if "avg" in line and "/" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    vals = parts[-1].strip().split("/")
                    if len(vals) >= 2:
                        try:
                            return float(vals[1])
                        except ValueError:
                            pass
        return 0.0

    def _parse_loss(self, output: str) -> float:
        for line in output.splitlines():
            if "packet loss" in line or "loss" in line:
                for part in line.split(","):
                    part = part.strip()
                    if "%" in part:
                        try:
                            return float(part.split("%")[0].strip().split()[-1])
                        except (ValueError, IndexError):
                            pass
        return 0.0
```

### Example 2: snmp_check (with connector)

Source from `packs/snmp-core-v1.0.0.json`, `snmp_check` v2.1.0:

```python
"""SNMP monitoring app — checks reachability via SNMP GET and measures response time."""
from __future__ import annotations
import time
from monctl_collector.jobs.models import PollContext, PollResult
from monctl_collector.polling.base import BasePoller


class Poller(BasePoller):

    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "localhost")
        oid = context.parameters.get("oid", "1.3.6.1.2.1.1.3.0")

        snmp = context.connectors.get("snmp")
        if snmp is None:
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="error",
                reachable=False,
                error_message="No SNMP connector bound (expected alias 'snmp')",
                error_category="config",
                execution_time_ms=0,
            )

        start = time.monotonic()
        try:
            result = await snmp.get([oid])
            rtt_ms = (time.monotonic() - start) * 1000

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "snmp_reachable", "value": 1.0, "labels": {"host": host, "oid": oid}},
                    {"name": "snmp_rtt_ms", "value": rtt_ms, "labels": {"host": host, "oid": oid}, "unit": "ms"},
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=int(rtt_ms),
                rtt_ms=rtt_ms,
            )

        except Exception as exc:
            rtt_ms = (time.monotonic() - start) * 1000
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "snmp_reachable", "value": 0.0, "labels": {"host": host, "oid": oid}},
                ],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"SNMP CRITICAL — {host} unreachable: {exc}",
                error_category="device",
                execution_time_ms=int(rtt_ms),
                rtt_ms=0.0,
            )
```

---

## Pack JSON Structure

Apps are delivered inside pack JSON files. Each pack can contain multiple apps.
File naming: `packs/{pack_uid}-v{version}.json`

```json
{
  "monctl_pack": "1.0",
  "pack_uid": "my-pack",
  "name": "My Monitoring Pack",
  "version": "1.0.0",
  "description": "Short description of what this pack monitors.",
  "author": "MonCTL",
  "changelog": "v1.0.0 - Initial release",
  "exported_at": null,
  "contents": {
    "apps": [
      {
        "name": "my_check",
        "description": "One-line description — what it checks and how.",
        "app_type": "script",
        "target_table": "availability_latency",
        "config_schema": {
          "type": "object",
          "properties": {
            "timeout": {
              "type": "integer",
              "title": "Timeout",
              "default": 5,
              "description": "Timeout in seconds"
            }
          }
        },
        "connector_bindings": [
          {
            "alias": "snmp",
            "connector_name": "snmp"
          }
        ],
        "versions": [
          {
            "version": "1.0.0",
            "source_code": "...full Python source as a string...",
            "requirements": [],
            "entry_class": "Poller",
            "is_latest": true
          }
        ]
      }
    ]
  }
}
```

### Pack field reference

| Field                | Notes                                                                               |
| -------------------- | ----------------------------------------------------------------------------------- |
| `pack_uid`           | Unique identifier, kebab-case (e.g. `"my-pack"`)                                    |
| `app_type`           | Always `"script"` for BasePoller apps                                               |
| `target_table`       | `"availability_latency"` \| `"performance"` \| `"interface"` \| `"config"`          |
| `config_schema`      | JSON Schema — properties become `context.parameters` keys                           |
| `connector_bindings` | Omit entirely if the app uses no connectors                                         |
| `requirements`       | pip requirements list — prefer `[]` unless an external library is needed            |
| `entry_class`        | Always `"Poller"`                                                                   |
| `is_latest`          | `true` on the newest version; `false` on all older ones                             |
| `source_code`        | Complete Python source as a single string (escape `\n`, `\"` etc. as JSON requires) |

---

## config_schema Tips

Parameters defined here are available as `context.parameters.get("key", default)`.

```json
"config_schema": {
  "type": "object",
  "properties": {
    "oid": {
      "type": "string",
      "title": "SNMP OID",
      "default": "1.3.6.1.2.1.1.3.0",
      "description": "OID to query",
      "x-widget": "snmp-oid"
    },
    "timeout": {
      "type": "integer",
      "title": "Timeout (s)",
      "default": 10
    },
    "expected_status": {
      "type": "array",
      "title": "Expected HTTP Status Codes",
      "default": [200, 201, 204]
    }
  }
}
```

`x-widget` hints understood by the UI: `"snmp-oid"`, `"credential-select"`.

Omit `config_schema` entirely if the app has no configurable parameters.

---

## Checklist Before Submitting an App

- [ ] Class is named `Poller` and subclasses `BasePoller`
- [ ] `poll()` is `async` and returns `PollResult` in ALL code paths
- [ ] Every non-OK result sets `error_category` (`"device"` / `"config"` / `"app"`)
- [ ] Connector guard (`if snmp is None: return … error_category="config"`) present for all connector apps
- [ ] `time.monotonic()` used for elapsed time, `time.time()` used for `timestamp`
- [ ] `job_id`, `device_id`, `collector_node` always set from `context`
- [ ] `target_table` in pack JSON matches what the app returns (`metrics` / `interface_rows` / `config_data`)
- [ ] `is_latest: true` on the version being added
- [ ] `requirements: []` unless a third-party library is genuinely needed

---

## Reference Apps

**Do NOT use `apps/` directory as reference — those files are outdated.**

Read the source code embedded in the pack JSON files instead:

| App                     | Pack file                        | Pattern shown                                      |
| ----------------------- | -------------------------------- | -------------------------------------------------- |
| `ping_check`            | `packs/basic-checks-v1.0.0.json` | asyncio subprocess, two error paths                |
| `port_check`            | `packs/basic-checks-v1.0.0.json` | asyncio TCP, OSError handling                      |
| `http_check`            | `packs/basic-checks-v1.0.0.json` | aiohttp + urllib fallback, verify_ssl              |
| `snmp_check`            | `packs/snmp-core-v1.0.0.json`    | connector guard, `time.monotonic()`, metric labels |
| `snmp_uptime`           | `packs/snmp-core-v1.0.0.json`    | fallback OID logic, helper parse function          |
| `snmp_interface_poller` | `packs/snmp-core-v1.0.0.json`    | walk + targeted GET, `interface_rows`              |
| `snmp_discovery`        | `packs/snmp-core-v1.0.0.json`    | one-shot, `config_data`, hex-decode helper         |

To read a specific app's source: `jq '.contents.apps[] | select(.name=="ping_check") | .versions[0].source_code' packs/basic-checks-v1.0.0.json`
