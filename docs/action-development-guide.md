# Action Development Guide

This guide covers how to write actions for MonCTL's Run Book Automation system. Actions are the executable building blocks of automations — Python scripts that run on a collector or on central to inspect, diagnose, or remediate issues across your monitored infrastructure.

---

## 1. Overview

An **action** is a standalone Python script that executes as a subprocess. Actions are organized into **automations**, which are ordered sequences of steps. Each step runs one action, and data flows between steps via a shared context.

Automations can be triggered in three ways:

- **Event-driven** — Fires when an event policy promotes an alert (e.g., a critical interface-down event).
- **Scheduled (cron)** — Runs on a recurring schedule (e.g., daily config backup).
- **Manual** — Triggered by an operator from the UI.

Each action receives a pre-populated `ActionContext` object called `context`. The script uses this object to read device information, credentials, data from previous steps, and to write structured output for downstream steps.

---

## 2. ActionContext API Reference

The `context` object is available as a global variable in every action script. It provides the following properties and methods.

### Properties

| Property                 | Type   | Description                                                                               |
| ------------------------ | ------ | ----------------------------------------------------------------------------------------- |
| `context.device_id`      | `str`  | UUID of the target device.                                                                |
| `context.device_name`    | `str`  | Device display name.                                                                      |
| `context.device_ip`      | `str`  | Device IP address.                                                                        |
| `context.collector_id`   | `str`  | Collector UUID. Empty string if the action runs on central.                               |
| `context.collector_name` | `str`  | Collector name. Empty string if the action runs on central.                               |
| `context.credential`     | `dict` | Decrypted credential dictionary. Keys depend on the credential type (see examples below). |
| `context.trigger_type`   | `str`  | One of `"event"`, `"cron"`, or `"manual"`.                                                |
| `context.event_id`       | `str`  | ClickHouse event ID. Empty string for cron/manual triggers.                               |
| `context.event_severity` | `str`  | Event severity (e.g., `"critical"`, `"warning"`). Empty string for cron/manual triggers.  |
| `context.event_message`  | `str`  | Event message text. Empty string for cron/manual triggers.                                |
| `context.shared_data`    | `dict` | Data from previous steps, namespaced by step number.                                      |
| `context.step_number`    | `int`  | Current step number (1-based).                                                            |
| `context.action_name`    | `str`  | Name of this action.                                                                      |

### Methods

| Method                           | Description                                                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `context.set_output(key, value)` | Store a key-value pair for subsequent steps. `value` must be JSON-serializable (str, int, float, bool, list, dict, or None). |

### Credential examples

The shape of `context.credential` depends on the credential type assigned to the action:

**SSH:**

```python
{
    "username": "admin",
    "password": "secret",
    "port": 22
}
```

**SNMP:**

```python
{
    "community": "public",
    "version": "2c"
}
```

**API Token:**

```python
{
    "api_key": "tok_abc123...",
    "base_url": "https://api.example.com"
}
```

### shared_data structure

Data from earlier steps is namespaced by step number as a string key:

```python
{
    "step_1": {"raw_output": "...", "line_count": 42},
    "step_2": {"status": "ok"}
}
```

Access it like:

```python
step1_data = context.shared_data.get("step_1", {})
output = step1_data.get("raw_output", "")
```

---

## 3. Execution Environment

### Runtime

- **Python 3.11+** on central nodes.
- **Python 3.12+** on collector nodes.
- Scripts run in a **temporary directory** that is created before execution and cleaned up afterward.
- The `context` object is injected as a global variable — you do not need to import or instantiate it.

### Timeouts and limits

- Configurable timeout per action: **5 to 300 seconds** (default: 60 seconds).
- `stdout` and `stderr` are captured, each capped at **50 KB**. Output beyond this limit is truncated.

### Exit codes

| Exit code | Meaning                                                              |
| --------- | -------------------------------------------------------------------- |
| `0`       | Success. The automation continues to the next step.                  |
| Non-zero  | Failure. The automation chain stops; remaining steps are skipped.    |
| `-1`      | Typically indicates the subprocess crashed or was killed by timeout. |

### Output data

Data written via `context.set_output(key, value)` is serialized as JSON and stored alongside the run history. Subsequent steps can read it from `context.shared_data`.

---

## 4. Available Libraries

The following libraries are pre-installed in the Docker containers and available for import:

### Standard library (always available)

`json`, `os`, `sys`, `subprocess`, `socket`, `re`, `datetime`, `time`, `pathlib`, `urllib`, `csv`, `io`, `hashlib`, `base64`, `ipaddress`, `logging`, `traceback`, `textwrap`, and all other stdlib modules.

### Third-party libraries

| Library    | Use case                     | Notes                                               |
| ---------- | ---------------------------- | --------------------------------------------------- |
| `paramiko` | SSH connections              | Available on both central and collector.            |
| `requests` | HTTP client (synchronous)    | Simple API calls, webhooks.                         |
| `httpx`    | HTTP client (sync and async) | More modern alternative to requests.                |
| `pysnmp`   | SNMP operations              | **Collector only.** Not available on central nodes. |

### Installing additional packages

Additional Python packages can be installed via MonCTL's **Python Module Registry** (Settings > Python Modules). Packages uploaded there are distributed to collectors and become importable in action scripts.

---

## 5. Example Actions

### a. SSH command execution

Connect to a device, run a command, and store the parsed output for the next step.

```python
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(
        hostname=context.device_ip,
        port=int(context.credential.get("port", 22)),
        username=context.credential.get("username", ""),
        password=context.credential.get("password", ""),
        timeout=10,
    )
    stdin, stdout, stderr = client.exec_command("show version")
    output = stdout.read().decode("utf-8")
    errors = stderr.read().decode("utf-8")

    context.set_output("raw_output", output)
    context.set_output("line_count", len(output.strip().split("\n")))
    print(f"Collected {len(output)} bytes from {context.device_name}")
finally:
    client.close()
```

### b. HTTP API call

Call a REST API on the device and extract status information.

```python
import requests

url = f"http://{context.device_ip}:8080/api/status"
headers = {"Authorization": f"Bearer {context.credential.get('api_key', '')}"}

resp = requests.get(url, headers=headers, timeout=10, verify=False)
resp.raise_for_status()

data = resp.json()
context.set_output("status", data.get("status"))
context.set_output("uptime", data.get("uptime"))
print(f"Device status: {data.get('status')}")
```

### c. Read from previous step

Use structured data produced by step 1 to perform analysis in step 2.

```python
# This action runs as step 2, reading data from step 1
step1_data = context.shared_data.get("step_1", {})
raw_output = step1_data.get("raw_output", "")

if not raw_output:
    print("No output from previous step")
    import sys
    sys.exit(1)

# Parse and analyze
lines = raw_output.strip().split("\n")
error_lines = [l for l in lines if "error" in l.lower()]

context.set_output("total_lines", len(lines))
context.set_output("error_count", len(error_lines))
context.set_output("errors", error_lines[:10])  # First 10 errors

if error_lines:
    print(f"Found {len(error_lines)} errors")
else:
    print("No errors found")
```

### d. Conditional remediation

Take action only when the triggering event meets specific criteria.

```python
import paramiko

# Only act on critical events
if context.trigger_type == "event" and context.event_severity != "critical":
    print(f"Skipping: severity is {context.event_severity}, not critical")
    context.set_output("action_taken", False)
    import sys
    sys.exit(0)  # Exit success but skip

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(
        hostname=context.device_ip,
        port=int(context.credential.get("port", 22)),
        username=context.credential.get("username", ""),
        password=context.credential.get("password", ""),
        timeout=10,
    )

    # Restart the service
    stdin, stdout, stderr = client.exec_command("sudo systemctl restart my-service")
    exit_status = stdout.channel.recv_exit_status()

    context.set_output("action_taken", True)
    context.set_output("restart_exit_code", exit_status)

    if exit_status == 0:
        print(f"Service restarted on {context.device_name}")
    else:
        print(f"Restart failed with exit code {exit_status}")
        import sys
        sys.exit(1)
finally:
    client.close()
```

### e. Send notification via webhook

Post a summary to Slack (or any webhook endpoint) at the end of an automation.

```python
import json
import requests

webhook_url = "https://hooks.slack.com/services/T.../B.../xxx"

payload = {
    "text": f"Automation '{context.action_name}' completed on {context.device_name} ({context.device_ip})",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Automation Run*\n"
                        f"Device: `{context.device_name}` ({context.device_ip})\n"
                        f"Trigger: {context.trigger_type}\n"
                        f"Step: {context.step_number}"
            }
        }
    ]
}

resp = requests.post(webhook_url, json=payload, timeout=10)
print(f"Webhook response: {resp.status_code}")
context.set_output("webhook_status", resp.status_code)
```

---

## 6. Best Practices

### Connection management

- Always use `try/finally` to close connections (SSH clients, file handles, etc.). Actions that crash or time out cannot clean up, so be defensive.
- Set explicit timeouts on all network calls (SSH, HTTP, SNMP). Do not rely solely on the action-level timeout — a hung socket can block the entire timeout window with no useful output.

### Exit codes and flow control

- Use `sys.exit(1)` (or any non-zero code) to signal failure. The automation chain stops and remaining steps are skipped.
- Use `sys.exit(0)` for success, even when the action decides there is "nothing to do". This allows the chain to continue.
- Avoid bare `exit()` — always use `sys.exit()` for clarity.

### Output and logging

- Use `context.set_output(key, value)` for structured data that downstream steps need.
- Use `print()` for human-readable log messages (visible in Run History).
- Keep stdout concise. It is stored in ClickHouse and capped at 50 KB. Avoid dumping large payloads to stdout — store them via `set_output()` instead.

### Credential handling

- Validate that expected keys exist in `context.credential` before using them. A missing or misconfigured credential will have an empty dict.
  ```python
  if not context.credential.get("username"):
      print("ERROR: SSH credential not configured for this device")
      import sys
      sys.exit(1)
  ```
- Never write credentials to stdout or stderr. They will be persisted in ClickHouse run history.

### Multi-step automations

- Use consistent, descriptive key names in `set_output()` so downstream steps can rely on a stable contract.
- Always guard against missing data from previous steps:
  ```python
  prev = context.shared_data.get("step_1", {})
  value = prev.get("expected_key")
  if value is None:
      print("Required data missing from step 1")
      import sys
      sys.exit(1)
  ```

### General

- Keep actions focused on a single task. Prefer multiple steps over one monolithic script.
- For idempotent operations (e.g., "ensure service is running"), check the current state before taking action.
- Test actions manually (via the UI's manual trigger) before attaching them to event-driven automations.

---

## 7. Troubleshooting

| Symptom                                | Likely cause                                                                          | Resolution                                                                                                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Action fails with no stdout/stderr     | Script crashed before producing output, or timed out.                                 | Check the exit code in Run History. `-1` usually means timeout or subprocess crash. Increase the timeout or add early `print()` statements to trace progress. |
| `"Action disabled or not found"`       | The action was disabled or deleted between automation creation and execution.         | Re-enable the action or update the automation to reference an active action.                                                                                  |
| `"No active collector found"`          | The device's collector group has no healthy (online) collectors.                      | Check the Collectors page for offline collectors. Verify the device is assigned to a valid collector group.                                                   |
| `ImportError` or `ModuleNotFoundError` | The required Python package is not installed in the container.                        | Install the package via the Python Module Registry (Settings > Python Modules) or add it to the Docker image.                                                 |
| `context.credential` is empty          | No credential is assigned to the action, or the credential type does not match.       | Verify the action has a credential assigned and that the credential type matches what the script expects (SSH, SNMP, etc.).                                   |
| `context.shared_data` is empty         | This is step 1 (no previous steps), or the previous step did not call `set_output()`. | Verify the previous step calls `context.set_output()` and completed successfully.                                                                             |
| Output truncated                       | stdout or stderr exceeded the 50 KB capture limit.                                    | Reduce logging verbosity. Use `context.set_output()` for large data payloads instead of `print()`.                                                            |
| Timeout on SSH/HTTP calls              | The action-level timeout fired while waiting for a network response.                  | Set explicit, shorter timeouts on individual network calls (e.g., `timeout=10` on `paramiko.connect()`).                                                      |

---

## 8. Security Notes

- **Credentials in memory only.** Credentials are decrypted on central and passed to the action via the `context` object. They are never written to disk.
- **Collector transport.** For actions targeting a collector, the decrypted credential travels over the WebSocket command channel, which is TLS-encrypted.
- **Temporary directory.** Each action runs in a dedicated temporary directory that is created before execution and removed afterward. Do not assume files persist between runs.
- **Do not log credentials.** Anything written to stdout or stderr is stored in ClickHouse run history. Never print passwords, API keys, community strings, or other secrets.
- **Script isolation.** Actions run as subprocesses with captured I/O. They do not have direct access to the central or collector application internals, databases, or other actions' runtime state.
