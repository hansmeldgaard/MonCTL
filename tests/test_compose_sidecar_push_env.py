"""Regression: docker-stats sidecar compose must wire the push env vars.

PR #140 (2026-04-22) restored three env-var lines to
``docker/docker-compose.docker-stats.yml`` that were silently dropped
during the PR #73 squash-merge. Without them the central sidecars
restart with push mode disabled and ``host_metrics_history`` stops
receiving central rows — System Health → Host metrics shows only
workers and the regression is invisible until somebody opens the
chart.

This test pins the contract: every push-mode env var the sidecar code
reads at startup MUST be passed through the central docker-stats
compose's ``environment:`` block. If a future squash-merge or refactor
silently drops one again, this test fails before deploy.

See feedback_squash_merge_drops_dev_fixes in CLAUDE.md and the
"squash-merge can silently drop dev-branch compose / config edits"
pitfall.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = REPO_ROOT / "docker" / "docker-compose.docker-stats.yml"

# The sidecar reads these at startup. Dropping any one disables push mode
# silently — the sidecar still answers /health, just stops POSTing.
REQUIRED_PUSH_VARS = (
    "MONCTL_PUSH_URL",
    "MONCTL_PUSH_API_KEY",
    "MONCTL_PUSH_VERIFY_SSL",
)


@pytest.fixture(scope="module")
def compose_text() -> str:
    assert COMPOSE.exists(), f"missing {COMPOSE}"
    return COMPOSE.read_text(encoding="utf-8")


@pytest.mark.parametrize("var", REQUIRED_PUSH_VARS)
def test_central_docker_stats_compose_passes_push_var(
    compose_text: str, var: str,
) -> None:
    # Substring match is enough — Docker Compose env mapping is
    # `KEY: ${KEY:-default}`. If the line is gone, this fails.
    assert var in compose_text, (
        f"docker/docker-compose.docker-stats.yml is missing {var}. "
        "PR #140 restored these after the PR #73 squash-merge dropped "
        "them. Without them the central sidecar restarts with push "
        "disabled and host_metrics_history stops receiving central rows."
    )


def test_central_docker_stats_compose_keeps_host_label(
    compose_text: str,
) -> None:
    # Belt-and-braces: MONCTL_HOST_LABEL was the one variable that
    # survived the squash-merge — if it ever disappears the chart can't
    # tell the four central rows apart.
    assert "MONCTL_HOST_LABEL" in compose_text
