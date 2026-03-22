"""Root conftest — shared fixtures and markers for all test layers."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Auto-select markers based on CLI flags."""
    if not config.option.markexpr:
        config.option.markexpr = "unit and not pg_only"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests based on their directory."""
    for item in items:
        test_path = str(item.fspath)
        if "/unit/" in test_path:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in test_path:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in test_path:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def admin_credentials() -> dict:
    """Default admin credentials for test environment."""
    return {
        "username": os.environ.get("MONCTL_TEST_ADMIN_USER", "admin"),
        "password": os.environ.get("MONCTL_TEST_ADMIN_PASS", "changeme"),
    }
