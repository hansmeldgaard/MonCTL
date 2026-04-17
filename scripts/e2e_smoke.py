#!/usr/bin/env python3
"""End-to-end smoke check for MonCTL. Run after every deploy, connector
upload, scheduler change, or any other change that could plausibly break
the fleet-wide collection flow.

Checks:
  1. /v1/system/health/status returns overall = healthy
  2. Every ACTIVE collector has last_seen_at within 120s
  3. Each (result_table, app_name) seen in the last 5 min has reasonable
     OK/error counts — and, if a baseline is on disk, err_pct hasn't jumped
     +20 percentage points and recent row count hasn't dropped > 50%.

Exit codes:
  0  all good
  1  regression / failure
  2  configuration / auth error

Usage:
  scripts/e2e_smoke.py                 # run checks, compare to baseline
  scripts/e2e_smoke.py --baseline      # overwrite baseline with current state
  scripts/e2e_smoke.py --since 10      # look back 10 min instead of 5
  scripts/e2e_smoke.py --no-baseline   # skip baseline comparison (first run)

Baseline file: .monctl-smoke/baseline.json (git-ignored).

Future (v2+):
  - SSH into centrals + workers, grep last N min of logs for ERROR /
    CRITICAL / Traceback with an allowlist. Kept out of v1 because it
    adds SSH dependency + log parsing complexity.
  - Playwright UI smoke (login, device detail loads, checks tab renders).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://10.145.210.40"
ENV_FILE = REPO_ROOT / ".env.local-dev"
BASELINE_DIR = REPO_ROOT / ".monctl-smoke"
BASELINE_FILE = BASELINE_DIR / "baseline.json"

RESULT_TABLES = ["availability_latency", "performance", "interface", "config"]
RECENT_WINDOW_SECONDS = 300          # default look-back, overridable via --since
COLLECTOR_STALE_SECONDS = 120        # ACTIVE collector without heartbeat > this = bad
ERR_PCT_REGRESSION_DELTA = 20.0      # percentage-point increase that flags regression
COUNT_DROP_FRACTION = 0.5            # >50% drop in fresh row count flags regression

# ANSI colours for human-readable output
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _read_env() -> tuple[str, str]:
    """Read MONCTL_TEST_USER / MONCTL_TEST_PASSWORD from .env.local-dev."""
    if not ENV_FILE.exists():
        print(f"{RED}Missing {ENV_FILE} — can't authenticate.{RESET}", file=sys.stderr)
        sys.exit(2)
    user = password = ""
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() == "MONCTL_TEST_USER":
            user = v
        elif k.strip() == "MONCTL_TEST_PASSWORD":
            password = v
    if not user or not password:
        print(f"{RED}MONCTL_TEST_USER / MONCTL_TEST_PASSWORD missing.{RESET}", file=sys.stderr)
        sys.exit(2)
    return user, password


class Client:
    """Tiny HTTPS client that keeps the session cookie across requests."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._cookies: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self._cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        return h

    def _stash_cookies(self, resp) -> None:
        for sc in resp.headers.get_all("Set-Cookie") or []:
            kv = sc.split(";", 1)[0].strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                self._cookies[k] = v

    def request(
        self, method: str, path: str, body: dict | None = None, timeout: float = 10.0,
    ) -> Any:
        url = self.base + path
        data = None
        headers = self._headers()
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=timeout) as resp:
                self._stash_cookies(resp)
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read()[:200]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"{method} {path} -> {e}") from e
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", errors="replace")

    def login(self, user: str, password: str) -> None:
        resp = self.request(
            "POST", "/v1/auth/login", body={"username": user, "password": password},
        )
        if not resp or resp.get("status") != "success":
            raise RuntimeError(f"Login failed: {resp}")


def _age_seconds(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        ts = iso_ts.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()


# ── Checks ────────────────────────────────────────────────────────────────

def check_health(client: Client) -> tuple[bool, str]:
    """Top-bar /system/health/status must report overall = healthy."""
    try:
        r = client.request("GET", "/v1/system/health/status")
    except RuntimeError as e:
        return False, str(e)
    data = (r or {}).get("data") or {}
    overall = data.get("overall_status") or data.get("overall") or "unknown"
    if overall == "healthy":
        return True, f"overall={overall}"
    subs = data.get("unhealthy_subsystems") or []
    return False, f"overall={overall} unhealthy_subsystems={subs}"


def check_collectors(client: Client) -> tuple[bool, list[str], dict]:
    """Every ACTIVE collector must have heartbeat within 120s."""
    issues: list[str] = []
    summary: dict[str, Any] = {"collectors": {}}
    try:
        r = client.request("GET", "/v1/collectors?limit=200")
    except RuntimeError as e:
        return False, [f"collectors list failed: {e}"], summary
    for c in (r or {}).get("data", []):
        status = c.get("status")
        name = c.get("name")
        age = _age_seconds(c.get("last_seen_at"))
        summary["collectors"][name] = {
            "status": status,
            "last_seen_age_s": round(age) if age is not None else None,
        }
        if status == "ACTIVE":
            if age is None:
                issues.append(f"{name}: ACTIVE but no last_seen_at")
            elif age > COLLECTOR_STALE_SECONDS:
                issues.append(f"{name}: last_seen_at {int(age)}s ago (> {COLLECTOR_STALE_SECONDS}s)")
    return len(issues) == 0, issues, summary


def collect_app_stats(client: Client, since_s: float) -> dict[str, dict[str, dict[str, int]]]:
    """For each result table, bucket rows by app_name and count ok/err."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for table in RESULT_TABLES:
        try:
            r = client.request(
                "GET", f"/v1/results/latest?table={table}&limit=5000", timeout=15.0,
            )
        except RuntimeError as e:
            out[table] = {"__error__": {"ok": 0, "err": 0, "_msg": str(e)}}
            continue
        buckets: dict[str, dict[str, int]] = {}
        for row in (r or {}).get("data", []):
            age = _age_seconds(row.get("executed_at"))
            if age is None or age > since_s:
                continue
            app = row.get("app_name") or "?"
            b = buckets.setdefault(app, {"ok": 0, "err": 0})
            if row.get("error_category"):
                b["err"] += 1
            else:
                b["ok"] += 1
        out[table] = buckets
    return out


def compare_to_baseline(
    current: dict[str, dict[str, dict[str, int]]],
    baseline: dict[str, dict[str, dict[str, int]]] | None,
) -> list[str]:
    """Flag per-app regressions vs baseline. Returns list of issue strings."""
    issues: list[str] = []
    if baseline is None:
        return issues
    for table, cur_apps in current.items():
        base_apps = baseline.get(table, {})
        for app, cur in cur_apps.items():
            if app.startswith("__"):
                continue
            base = base_apps.get(app)
            if not base:
                continue  # new app, nothing to compare
            cur_total = cur["ok"] + cur["err"]
            base_total = base["ok"] + base["err"]
            if base_total == 0:
                continue
            cur_err_pct = 100 * cur["err"] / max(1, cur_total)
            base_err_pct = 100 * base["err"] / max(1, base_total)
            if cur_err_pct - base_err_pct > ERR_PCT_REGRESSION_DELTA:
                issues.append(
                    f"{table}.{app}: err_pct {base_err_pct:.0f}% → {cur_err_pct:.0f}% "
                    f"(+{cur_err_pct - base_err_pct:.0f}pp)"
                )
            if cur_total < base_total * (1 - COUNT_DROP_FRACTION):
                issues.append(
                    f"{table}.{app}: recent rows {base_total} → {cur_total} "
                    f"({100 * (1 - cur_total / base_total):.0f}% drop)"
                )
    # Also flag apps that disappeared from current run
    for table, base_apps in baseline.items():
        cur_apps = current.get(table, {})
        for app, base in base_apps.items():
            if app.startswith("__"):
                continue
            base_total = base["ok"] + base["err"]
            if base_total > 0 and app not in cur_apps:
                issues.append(f"{table}.{app}: no fresh rows (baseline had {base_total})")
    return issues


# ── Main ──────────────────────────────────────────────────────────────────

def _load_baseline() -> dict | None:
    if not BASELINE_FILE.exists():
        return None
    try:
        return json.loads(BASELINE_FILE.read_text())
    except Exception:
        return None


def _save_baseline(snapshot: dict) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(snapshot, indent=2, sort_keys=True))


def _fmt_app_table(current: dict[str, dict[str, dict[str, int]]]) -> str:
    lines = []
    for table in RESULT_TABLES:
        apps = current.get(table, {})
        if not apps or (len(apps) == 1 and "__error__" in apps):
            lines.append(f"  {table}: {DIM}(no fresh rows){RESET}")
            continue
        lines.append(f"  {table}:")
        for app in sorted(apps):
            if app == "__error__":
                lines.append(f"    {RED}!! query failed: {apps[app].get('_msg','?')}{RESET}")
                continue
            b = apps[app]
            total = b["ok"] + b["err"]
            pct = 100 * b["err"] / max(1, total)
            flag = RED if pct > 50 else (YELLOW if pct > 20 else "")
            lines.append(
                f"    {flag}{app:30s} ok={b['ok']:4d} err={b['err']:4d} "
                f"err_pct={pct:5.1f}%{RESET if flag else ''}"
            )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", action="store_true",
                   help="Write current state as the new baseline and exit.")
    p.add_argument("--no-baseline", action="store_true",
                   help="Skip baseline comparison even if a baseline exists.")
    p.add_argument("--since", type=float, default=RECENT_WINDOW_SECONDS / 60,
                   help="Minutes to look back for recent results (default 5).")
    p.add_argument("--url", default=DEFAULT_BASE_URL,
                   help=f"Central base URL (default {DEFAULT_BASE_URL}).")
    args = p.parse_args()

    since_s = args.since * 60

    user, password = _read_env()
    client = Client(args.url)
    try:
        client.login(user, password)
    except RuntimeError as e:
        print(f"{RED}Auth failed: {e}{RESET}", file=sys.stderr)
        return 2

    all_issues: list[str] = []
    print(f"{BOLD}MonCTL e2e smoke{RESET}  (url={args.url}  window={args.since:g}min)")
    print()

    # 1. Health endpoint
    ok, detail = check_health(client)
    sym = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"[{sym}] central health: {detail}")
    if not ok:
        all_issues.append(f"central health: {detail}")

    # 2. Collectors
    ok, coll_issues, coll_summary = check_collectors(client)
    sym = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    total = len(coll_summary.get("collectors", {}))
    active = sum(
        1 for c in coll_summary["collectors"].values() if c.get("status") == "ACTIVE"
    )
    print(f"[{sym}] collectors: {active}/{total} ACTIVE")
    for issue in coll_issues:
        print(f"       {RED}!! {issue}{RESET}")
        all_issues.append(f"collector: {issue}")

    # 3. Per-app collection stats
    print()
    print(f"{BOLD}Per-app results (last {args.since:g} min):{RESET}")
    current = collect_app_stats(client, since_s)
    print(_fmt_app_table(current))

    # 4. Regression vs baseline
    baseline = None if args.no_baseline else _load_baseline()
    if args.baseline:
        snapshot = {
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "since_minutes": args.since,
            "apps": current,
        }
        _save_baseline(snapshot)
        print()
        print(f"{GREEN}Baseline written to {BASELINE_FILE.relative_to(REPO_ROOT)}{RESET}")
        return 0

    if baseline is not None:
        base_apps = baseline.get("apps", {})
        regressions = compare_to_baseline(current, base_apps)
        print()
        if regressions:
            print(f"{BOLD}{RED}Regressions vs baseline "
                  f"(captured {baseline.get('captured_at','?')}):{RESET}")
            for r in regressions:
                print(f"  {RED}!! {r}{RESET}")
                all_issues.append(f"regression: {r}")
        else:
            print(f"{GREEN}No regressions vs baseline "
                  f"(captured {baseline.get('captured_at','?')}){RESET}")
    else:
        print()
        print(f"{YELLOW}No baseline found — run with --baseline to establish one.{RESET}")

    print()
    if all_issues:
        print(f"{BOLD}{RED}SMOKE FAILED ({len(all_issues)} issue(s)){RESET}")
        return 1
    print(f"{BOLD}{GREEN}SMOKE OK{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
