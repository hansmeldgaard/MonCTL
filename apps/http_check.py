#!/usr/bin/env python3
"""HTTP/HTTPS monitoring app — checks if a URL is reachable and returns the expected status.

Protocol:
  stdin:  JSON config
  stdout: JSON result with check_result (including performance_data) and metrics
  exit:   0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN

Config keys:
  url             str        Full URL to check, e.g. "https://example.com/health"
                             If not set, "host" (injected from device) is used as the URL.
  timeout         int        Request timeout in seconds (default: 10)
  expected_status list[int]  HTTP status codes considered OK (default: [200, 201, 204, 301, 302])
  follow_redirects bool      Follow HTTP redirects (default: true)
  verify_ssl      bool       Verify TLS certificate (default: true)

Performance data (always present in check_result.performance_data):
  response_time_ms  Total request time in milliseconds (0 if unreachable)
  status_code       HTTP response status code (0 if connection failed)
  reachable         1.0 if response received with expected status, 0.0 otherwise
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import ssl


def http_check(
    url: str,
    timeout: int,
    expected_status: list[int],
    follow_redirects: bool,
    verify_ssl: bool,
) -> tuple[int, float, str]:
    """Perform an HTTP GET request.

    Returns:
        (status_code, response_time_ms, detail)
        status_code = 0 on connection error
    """
    ssl_ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()

    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "monctl-http-check/1.0"},
    )

    start = time.monotonic()
    try:
        if follow_redirects:
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_ctx))
        else:
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl_ctx),
                # Override redirect handler to NOT follow redirects
                urllib.request.HTTPErrorProcessor,
            )
            opener.handle_error = {}  # type: ignore

        with opener.open(req, timeout=timeout) as resp:
            elapsed_ms = (time.monotonic() - start) * 1000
            return resp.status, elapsed_ms, f"HTTP {resp.status} {resp.reason}"

    except urllib.error.HTTPError as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return e.code, elapsed_ms, f"HTTP {e.code} {e.reason}"

    except urllib.error.URLError as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return 0, elapsed_ms, f"Connection error: {e.reason}"

    except TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return 0, elapsed_ms, f"Timed out after {timeout}s"

    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return 0, elapsed_ms, f"Error: {e}"


def main() -> None:
    raw = sys.stdin.read().strip()
    config: dict = json.loads(raw) if raw else {}

    # "url" takes priority; fall back to "host" (device address injection)
    url: str = config.get("url") or config.get("host", "")
    if not url:
        print(json.dumps({
            "check_result": {
                "state": 3,
                "output": "HTTP UNKNOWN — no url or host configured",
                "performance_data": {"response_time_ms": 0.0, "status_code": 0.0, "reachable": 0.0},
            },
            "metrics": [],
        }))
        sys.exit(3)

    # Ensure the URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    timeout: int = int(config.get("timeout", 10))
    expected_status: list[int] = config.get("expected_status", [200, 201, 204, 301, 302])
    follow_redirects: bool = bool(config.get("follow_redirects", True))
    verify_ssl: bool = bool(config.get("verify_ssl", True))

    status_code, response_time_ms, detail = http_check(
        url, timeout, expected_status, follow_redirects, verify_ssl
    )

    reachable = status_code in expected_status

    if reachable:
        state = 0  # OK
        output = f"HTTP OK — {url} returned {status_code} in {response_time_ms:.0f}ms"
    elif status_code == 0:
        state = 2  # CRITICAL — connection failed
        output = f"HTTP CRITICAL — {url} unreachable: {detail}"
    else:
        state = 2  # CRITICAL — unexpected status
        output = f"HTTP CRITICAL — {url} returned {status_code} (expected {expected_status}): {detail}"

    performance_data = {
        "response_time_ms": round(response_time_ms, 3),
        "status_code": float(status_code),
        "reachable": 1.0 if reachable else 0.0,
    }

    metrics = [
        {"name": "http_reachable", "value": 1.0 if reachable else 0.0, "labels": {"url": url}},
        {"name": "http_response_time_ms", "value": response_time_ms, "labels": {"url": url}, "unit": "ms"},
        {"name": "http_status_code", "value": float(status_code), "labels": {"url": url}},
    ]

    result = {
        "check_result": {
            "state": state,
            "output": output,
            "performance_data": performance_data,
        },
        "metrics": metrics,
    }

    print(json.dumps(result))
    sys.exit(state)


if __name__ == "__main__":
    main()
