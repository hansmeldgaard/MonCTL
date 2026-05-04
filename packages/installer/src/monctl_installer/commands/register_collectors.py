"""``monctl_ctl register-collectors`` — mint per-host collector API keys.

Wave 2 finisher (M-INST-011 / S-COL-002 / S-X-002 / S-CEN-002 stage). After
``monctl_ctl deploy`` brings the cluster up, this subcommand:

1. Reads the inventory + secrets to find collector hosts and admin creds.
2. Authenticates to central as admin via ``POST /v1/auth/login``.
3. For each host with the ``collector`` role:
   a. Mints a per-host key via
      ``POST /v1/collectors/by-hostname/{hostname}/api-keys``.
   b. SSHes to the host and rewrites
      ``MONCTL_COLLECTOR_API_KEY`` in
      ``/opt/monctl/collector/.env`` to the new value.
   c. Restarts the collector compose stack so the new key takes effect.

The previous shared-secret deploy is preserved as a fallback — an
operator can still run ``monctl_ctl deploy`` without
``register-collectors``, in which case all hosts share
``MONCTL_COLLECTOR_API_KEY`` from secrets.env. After this subcommand
runs, the per-host keys take precedence and the shared secret becomes
the bootstrap-only fallback path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.inventory.schema import Host, Inventory
from monctl_installer.remote.ssh import SSHError, SSHRunner
from monctl_installer.secrets.store import load_secrets


COLLECTOR_ENV_PATH = "/opt/monctl/collector/.env"


@dataclass(frozen=True)
class RegisterOutcome:
    host: str
    status: Literal["registered", "skipped", "failed"]
    detail: str
    collector_id: str | None = None


class RegisterError(RuntimeError):
    """Raised on a precondition that prevents starting any work
    (missing admin creds, no central host, etc.)."""


def register_collectors(
    inventory_path: Path,
    *,
    central_url: str | None = None,
    revoke_existing: bool = False,
    runner: SSHRunner | None = None,
    http_client: httpx.Client | None = None,
) -> list[RegisterOutcome]:
    """Mint per-host collector API keys + write to each host .env."""
    inv = load_inventory(inventory_path)
    plan_cluster(inv)  # validate; cheaper to fail before any HTTP call
    secrets_path = Path(inv.secrets.file)
    if not secrets_path.is_absolute():
        secrets_path = inventory_path.parent / secrets_path
    secret_values = load_secrets(secrets_path)

    admin_user = secret_values.get("MONCTL_ADMIN_USERNAME") or "admin"
    admin_pass = secret_values.get("MONCTL_ADMIN_PASSWORD")
    if not admin_pass:
        raise RegisterError(
            "MONCTL_ADMIN_PASSWORD missing from secrets.env — "
            "can't authenticate to central"
        )

    base_url = central_url or _derive_central_url(inv)

    owns_runner = runner is None
    if runner is None:
        runner = SSHRunner()
    owns_http = http_client is None
    if http_client is None:
        # Self-signed cert during bootstrap is the documented default
        # (TLSConfig.verify defaults False for `mode=self-signed`); the
        # operator can run with their own central CA after install.
        http_client = httpx.Client(
            verify=False,  # noqa: S501 — bootstrap path, see TLSConfig.effective_verify
            timeout=30.0,
        )

    try:
        _login(http_client, base_url, admin_user, admin_pass)
        outcomes: list[RegisterOutcome] = []
        for host in inv.hosts:
            if "collector" not in host.roles:
                continue
            outcomes.append(
                _register_host(
                    http_client, base_url, host, runner, revoke_existing
                )
            )
        return outcomes
    finally:
        if owns_runner:
            runner.close()
        if owns_http:
            http_client.close()


# ── internals ──────────────────────────────────────────────────────────────


def _login(
    client: httpx.Client, base_url: str, user: str, password: str
) -> None:
    """POST /v1/auth/login. JWT lives in HTTP-only cookies the client
    auto-attaches on subsequent requests.

    Per memory ``feedback_httpx_cookies_assignment``, httpx ≥0.28 silently
    drops ``client.cookies = resp.cookies`` — but here we don't assign at
    all, since the client's cookie jar absorbs ``Set-Cookie`` on the
    response automatically.
    """
    resp = client.post(
        f"{base_url}/v1/auth/login",
        json={"username": user, "password": password},
    )
    resp.raise_for_status()
    cookie_names = list(client.cookies.keys())
    if "access_token" not in cookie_names:
        raise RegisterError(
            "central login returned no access_token cookie — "
            f"cookies seen: {cookie_names!r}"
        )


def _register_host(
    client: httpx.Client,
    base_url: str,
    host: Host,
    runner: SSHRunner,
    revoke_existing: bool,
) -> RegisterOutcome:
    """Mint a key for one host + write it to the host's collector .env."""
    try:
        resp = client.post(
            f"{base_url}/v1/collectors/by-hostname/{host.name}/api-keys",
            json={"revoke_existing": revoke_existing},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return RegisterOutcome(
            host.name, "failed", f"key-mint API call failed: {exc}"
        )

    body: dict[str, Any] = resp.json()
    api_key = body.get("api_key", "")
    collector_id = body.get("collector_id")
    if not api_key:
        return RegisterOutcome(
            host.name, "failed",
            f"key-mint response missing api_key: {body!r}",
        )

    # Read the current .env, substitute the line in Python (avoids any
    # shell-quoting risk on the API key string), put it back, restart.
    try:
        cat = runner.run(host, f"cat {COLLECTOR_ENV_PATH}")
        if not cat.ok:
            return RegisterOutcome(
                host.name, "failed",
                f"cannot read {COLLECTOR_ENV_PATH}: rc={cat.exit_code} "
                f"stderr={cat.stderr!r}",
            )
        new_env = _substitute_api_key(cat.stdout, api_key)
        runner.put(host, new_env, COLLECTOR_ENV_PATH, mode=0o600)
        restart = runner.run(
            host, "cd /opt/monctl/collector && docker compose up -d"
        )
        if not restart.ok:
            return RegisterOutcome(
                host.name, "failed",
                f"collector restart failed: rc={restart.exit_code} "
                f"stderr={restart.stderr!r}",
            )
    except SSHError as exc:
        return RegisterOutcome(host.name, "failed", str(exc))

    return RegisterOutcome(
        host.name, "registered",
        f"id={collector_id}",
        collector_id=collector_id,
    )


def _substitute_api_key(env_content: str, new_key: str) -> str:
    """Replace ``MONCTL_COLLECTOR_API_KEY=`` line in-place; append if absent.

    Pure-string substitution — no shell, no regex, so the API key value
    can contain any printable character without quoting concerns.
    """
    lines = env_content.splitlines()
    found = False
    for i, line in enumerate(lines):
        # Match `MONCTL_COLLECTOR_API_KEY=` even with leading whitespace,
        # but not commented-out lines.
        stripped = line.lstrip()
        if stripped.startswith("MONCTL_COLLECTOR_API_KEY="):
            lines[i] = f"MONCTL_COLLECTOR_API_KEY={new_key}"
            found = True
            break
    if not found:
        lines.append(f"MONCTL_COLLECTOR_API_KEY={new_key}")
    # Preserve trailing newline if input had one
    suffix = "\n" if env_content.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _derive_central_url(inv: Inventory) -> str:
    """Use the cluster VIP if set; otherwise the first central host's IP."""
    if inv.cluster.vip:
        return f"https://{inv.cluster.vip}:8443"
    central_hosts = [h for h in inv.hosts if "central" in h.roles]
    if not central_hosts:
        raise RegisterError(
            "no central host found in inventory — set cluster.vip or "
            "add a host with `central` in roles"
        )
    return f"https://{central_hosts[0].address}:8443"
