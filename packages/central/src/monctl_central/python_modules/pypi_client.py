"""PyPI JSON API client for importing packages from the public registry."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

PYPI_BASE_URL = "https://pypi.org"


async def fetch_package_info(
    package_name: str,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    """Fetch package metadata from PyPI JSON API.

    Returns the full JSON response from https://pypi.org/pypi/{package}/json.
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    url = f"{PYPI_BASE_URL}/pypi/{package_name}/json"
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
    async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def fetch_version_info(
    package_name: str,
    version: str,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    """Fetch metadata for a specific package version.

    Returns the JSON response from https://pypi.org/pypi/{package}/{version}/json.
    """
    url = f"{PYPI_BASE_URL}/pypi/{package_name}/{version}/json"
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
    async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def download_wheel(
    url: str,
    proxy_url: str | None = None,
) -> bytes:
    """Download a wheel file from the given URL.

    Returns the raw bytes of the .whl file.
    """
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
    async with httpx.AsyncClient(transport=transport, timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def search_pypi(
    query: str,
    proxy_url: str | None = None,
) -> list[dict[str, Any]]:
    """Search PyPI for packages matching a query.

    Uses the PyPI JSON API to search (fetches the package and returns info if found).
    PyPI doesn't have a true search API in JSON, so we try to fetch the package directly.
    Returns a list of package info dicts (0 or 1 items).
    """
    try:
        info = await fetch_package_info(query, proxy_url=proxy_url)
        pkg_info = info.get("info", {})
        return [{
            "name": pkg_info.get("name", query),
            "latest_version": pkg_info.get("version", ""),
            "summary": pkg_info.get("summary", ""),
            "registered": False,
        }]
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return []
        raise
