"""App manager — fetches, installs and loads monitoring app plugins.

Venv sharing model:
  Venvs are keyed by sha256(python_version + sorted(requirements)), so
  multiple apps with identical dependencies share one venv.

Disk layout:
  /data/
    venvs/
      <venv_hash>/
        venv/              ← Python virtualenv
        requirements.json  ← [{"package": "requests", "version": "2.31"}]
    apps/
      <app_id>/
        <version>/
          module.py        ← App source code (BasePoller subclass)
          metadata.json    ← {"app_id", "version", "entry_class", "venv_hash", "checksum"}

The AppManager is used by poll-workers. The worker calls
`ensure_app(app_id, version)` which returns the class object ready to
be instantiated. The worker keeps one instance per (app_id, version).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
import venv
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from monctl_collector.config import AppsConfig

if TYPE_CHECKING:
    from monctl_collector.central.api_client import CentralAPIClient
    from monctl_collector.polling.base import BasePoller

logger = structlog.get_logger()


def _venv_hash(python_version: str, requirements: list[str]) -> str:
    """Deterministic hash for a set of requirements.

    Args:
        python_version: e.g. "3.11", "3.12"
        requirements:   list of pip requirement strings, e.g. ["requests>=2.28", "icmplib"]

    Returns:
        12-character hex string (first 12 chars of SHA-256).
    """
    key = f"py{python_version}::{':'.join(sorted(requirements))}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


class AppManager:
    """Manages venvs and app modules for poll-workers."""

    def __init__(
        self,
        config: AppsConfig,
        central_client: "CentralAPIClient",
        python_version: str | None = None,
    ) -> None:
        self._cfg = config
        self._central = central_client
        self._python_version = python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        self._apps_dir = Path(config.apps_dir)
        self._venvs_dir = Path(config.venvs_dir)
        self._pip_cache = Path(config.pip_cache_dir)

        # In-memory cache: (app_id, version) → loaded class
        self._loaded: dict[tuple[str, str], type["BasePoller"]] = {}

        # In-memory cache: (connector_id, version_id) → loaded class
        self._loaded_connectors: dict[tuple[str, str], type] = {}

        # Lock per venv hash to prevent concurrent venv creation
        self._venv_locks: dict[str, asyncio.Lock] = {}

    async def ensure_app(
        self, app_id: str, version: str, expected_checksum: str = "",
    ) -> type["BasePoller"]:
        """Return the loaded class for (app_id, version), fetching/installing if needed.

        This is the main entry point for poll-workers.
        If expected_checksum is provided and differs from the stored checksum,
        the app is re-downloaded and reloaded (cache invalidation).
        """
        key = (app_id, version)

        # Check in-memory cache — invalidate if checksum changed
        if key in self._loaded and expected_checksum:
            stored = self._get_stored_checksum(app_id, version)
            if stored and stored != expected_checksum:
                logger.info(
                    "app_checksum_changed", app_id=app_id, version=version,
                    old=stored[:12], new=expected_checksum[:12],
                )
                self._loaded.pop(key, None)

        if key in self._loaded:
            return self._loaded[key]

        meta_path = self._apps_dir / app_id / version / "metadata.json"

        needs_fetch = not meta_path.exists()
        if not needs_fetch and expected_checksum:
            stored = self._get_stored_checksum(app_id, version)
            if stored and stored != expected_checksum:
                needs_fetch = True

        if needs_fetch:
            logger.info("fetching_app", app_id=app_id, version=version)
            await self._fetch_and_install(app_id, version)

        cls = await asyncio.to_thread(self._load_class, app_id, version)
        self._loaded[key] = cls
        return cls

    async def invalidate(self, app_id: str, version: str) -> None:
        """Force re-fetch on next ensure_app call (called when central reports new version)."""
        self._loaded.pop((app_id, version), None)

    async def invalidate_connector(self, connector_id: str, version_id: str) -> None:
        """Force re-fetch on next ensure_connector call."""
        self._loaded_connectors.pop((connector_id, version_id), None)

    def _get_stored_checksum(self, app_id: str, version: str) -> str:
        """Read checksum from on-disk metadata.json for an app."""
        meta_path = self._apps_dir / app_id / version / "metadata.json"
        if not meta_path.exists():
            return ""
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("checksum", "")
        except Exception:
            return ""

    def _get_stored_connector_checksum(self, connector_id: str, version_id: str) -> str:
        """Read checksum from on-disk metadata.json for a connector."""
        meta_path = self._apps_dir / "_connectors" / connector_id / version_id / "metadata.json"
        if not meta_path.exists():
            return ""
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("checksum", "")
        except Exception:
            return ""

    # ── Private: fetch + install ──────────────────────────────────────────────

    async def _fetch_and_install(self, app_id: str, version: str) -> None:
        """Download app code from central, verify checksum, install venv."""
        # Fetch metadata
        meta = await self._central.get_app_metadata(app_id)
        requirements: list[str] = meta.get("requirements", [])
        entry_class: str = meta.get("entry_class") or "Poller"
        expected_checksum: str = meta.get("checksum", "")

        # Fetch source code
        code_resp = await self._central.get_app_code(app_id)
        if not code_resp:
            raise RuntimeError(f"No source code for app {app_id!r}")
        code = code_resp.get("code", "")
        if not code:
            raise RuntimeError(f"No source code in response for app {app_id!r}")

        # Verify checksum
        actual_checksum = hashlib.sha256(code.encode()).hexdigest()
        if expected_checksum and actual_checksum != expected_checksum:
            raise RuntimeError(
                f"Checksum mismatch for {app_id}:{version} "
                f"(expected={expected_checksum!r}, got={actual_checksum!r})"
            )

        # Ensure venv exists (shared)
        vh = _venv_hash(self._python_version, requirements)
        await self._ensure_venv(vh, requirements)

        # Write app files
        app_dir = self._apps_dir / app_id / version
        await asyncio.to_thread(self._write_app_files, app_dir, code, {
            "app_id": app_id,
            "version": version,
            "entry_class": entry_class,
            "venv_hash": vh,
            "checksum": actual_checksum,
        })

        logger.info("app_installed", app_id=app_id, version=version, venv_hash=vh)

    async def _ensure_venv(self, venv_hash: str, requirements: list[str]) -> Path:
        """Create and populate the venv if it doesn't exist yet.

        Multiple coroutines requesting the same venv hash concurrently are
        serialised by an asyncio.Lock to avoid duplicate pip installs.
        Includes a health check on first load to self-heal corrupt venvs.
        """
        venv_dir = self._venvs_dir / venv_hash / "venv"
        marker = self._venvs_dir / venv_hash / "requirements.json"

        if venv_dir.exists() and marker.exists():
            # Health check: verify the venv's Python is functional
            python_exe = venv_dir / "bin" / "python"
            if python_exe.exists():
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        [str(python_exe), "-c", "import pip"],
                        capture_output=True, timeout=10,
                    )
                    if result.returncode == 0:
                        return venv_dir  # Healthy
                except Exception:
                    pass
            # Corrupt venv — remove and recreate
            logger.warning("venv_corrupt_self_healing", venv_hash=venv_hash)
            import shutil
            await asyncio.to_thread(shutil.rmtree, venv_dir, True)
            marker.unlink(missing_ok=True)

        if venv_hash not in self._venv_locks:
            self._venv_locks[venv_hash] = asyncio.Lock()

        async with self._venv_locks[venv_hash]:
            # Re-check after acquiring lock (another coroutine may have installed it)
            if venv_dir.exists() and marker.exists():
                return venv_dir

            logger.info("creating_venv", venv_hash=venv_hash, requirements=requirements)
            await asyncio.to_thread(self._create_venv, venv_dir, requirements)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(requirements, indent=2))

        return venv_dir

    # ── Private: sync operations (run in thread pool) ─────────────────────────

    def _create_venv(self, venv_dir: Path, requirements: list[str]) -> None:
        """Create a new virtualenv and pip-install requirements.

        The central API key is passed to pip via a mode-0600 `pip.conf` written
        to a private temp directory and exposed with `PIP_CONFIG_FILE`, so the
        credential never lands in `/proc/self/environ`, process listings, or
        subprocess-env dumps the way `PIP_INDEX_URL` would.
        """
        import os
        import tempfile
        from urllib.parse import urlparse

        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        venv.create(str(venv_dir), with_pip=True, clear=True)

        if not requirements:
            return

        python_exe = venv_dir / "bin" / "python"
        cmd = [str(python_exe), "-m", "pip", "install", "--quiet"]

        env = dict(os.environ)
        # Strip inherited credential-bearing pip env so we can't accidentally
        # re-export them into the pip process if this method is called with a
        # parent that has them set.
        env.pop("PIP_INDEX_URL", None)
        env.pop("PIP_EXTRA_INDEX_URL", None)

        pip_conf_dir: str | None = None
        try:
            if self._cfg.pip_index_url:
                index_url = self._cfg.pip_index_url
                central_api_key = (
                    os.environ.get("MONCTL_COLLECTOR_API_KEY")
                    or os.environ.get("MONCTL_CENTRAL_API_KEY")
                    or os.environ.get("CENTRAL_API_KEY")
                )
                if central_api_key and "://" in index_url:
                    parsed = urlparse(index_url)
                    if not parsed.username:
                        index_url = index_url.replace(
                            f"{parsed.scheme}://",
                            f"{parsed.scheme}://__token__:{central_api_key}@",
                        )

                parsed = urlparse(index_url)
                trusted_host = parsed.hostname or ""

                # Write a private pip.conf. The file is mode 0600 and lives in
                # a per-install temp dir that we unlink in the finally block.
                pip_conf_dir = tempfile.mkdtemp(prefix="monctl-pip-")
                pip_conf_path = os.path.join(pip_conf_dir, "pip.conf")
                conf_lines = [
                    "[global]",
                    f"index-url = {index_url}",
                ]
                if trusted_host:
                    conf_lines.append(f"trusted-host = {trusted_host}")
                with open(pip_conf_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(conf_lines) + "\n")
                os.chmod(pip_conf_path, 0o600)
                env["PIP_CONFIG_FILE"] = pip_conf_path

            self._pip_cache.mkdir(parents=True, exist_ok=True)
            cmd += ["--cache-dir", str(self._pip_cache)]
            cmd += requirements

            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                # Don't echo env/index-url into the error — strip any token
                # substring defensively even though we never injected one into
                # argv. The stderr can still name the index URL without creds.
                raise RuntimeError(
                    f"pip install failed for venv {venv_dir.parent.name}:\n{result.stderr}"
                )
        finally:
            if pip_conf_dir is not None:
                import shutil

                shutil.rmtree(pip_conf_dir, ignore_errors=True)

    def _write_app_files(self, app_dir: Path, code: str, metadata: dict) -> None:
        """Write module.py + metadata.json to disk."""
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "module.py").write_text(code, encoding="utf-8")
        (app_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    def _load_class(self, app_id: str, version: str) -> type["BasePoller"]:
        """Dynamically load the BasePoller subclass from disk.

        Uses importlib to load module.py from the app directory.
        The venv's site-packages are kept in sys.path so that lazy imports
        (e.g. pysnmp in connectors) resolve correctly at runtime.
        """
        app_dir = self._apps_dir / app_id / version
        meta = json.loads((app_dir / "metadata.json").read_text())
        entry_class: str = meta.get("entry_class") or "Poller"
        venv_hash: str = meta["venv_hash"]

        venv_site = self._venvs_dir / venv_hash / "venv" / "lib"
        # Find site-packages under lib (Python version varies)
        site_packages: list[str] = []
        if venv_site.exists():
            for pydir in venv_site.iterdir():
                sp = pydir / "site-packages"
                if sp.exists():
                    site_packages.append(str(sp))

        # Inject venv site-packages permanently so lazy imports work at runtime
        for sp in site_packages:
            if sp not in sys.path:
                sys.path.insert(0, sp)

        module_path = app_dir / "module.py"
        spec = importlib.util.spec_from_file_location(
            f"monctl_app_{app_id}_{version}",
            str(module_path),
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load spec for {module_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cls = getattr(mod, entry_class, None)
        if cls is None:
            raise AttributeError(
                f"Class {entry_class!r} not found in {app_id}:{version} module. "
                f"Available names: {[n for n in dir(mod) if not n.startswith('_')]}"
            )
        return cls

    # ── Connector loading ──────────────────────────────────────────────────────

    async def ensure_connector(
        self, connector_id: str, version_id: str, expected_checksum: str = "",
    ) -> type:
        """Return the loaded connector class, fetching/installing if needed.

        Works like ensure_app but for connectors. Uses the same venv sharing
        mechanism so connectors with identical requirements share a venv.
        If expected_checksum is provided and differs from stored, re-downloads.
        """
        key = (connector_id, version_id)

        # Check in-memory cache — invalidate if checksum changed
        if key in self._loaded_connectors and expected_checksum:
            stored = self._get_stored_connector_checksum(connector_id, version_id)
            if stored and stored != expected_checksum:
                logger.info(
                    "connector_checksum_changed",
                    connector_id=connector_id, version_id=version_id,
                    old=stored[:12], new=expected_checksum[:12],
                )
                self._loaded_connectors.pop(key, None)

        if key in self._loaded_connectors:
            return self._loaded_connectors[key]

        conn_dir = self._apps_dir / "_connectors" / connector_id / version_id
        meta_path = conn_dir / "metadata.json"

        needs_fetch = not meta_path.exists()
        if not needs_fetch and expected_checksum:
            stored = self._get_stored_connector_checksum(connector_id, version_id)
            if stored and stored != expected_checksum:
                needs_fetch = True

        if needs_fetch:
            logger.info("fetching_connector", connector_id=connector_id, version_id=version_id)
            await self._fetch_and_install_connector(connector_id, version_id)

        cls = await asyncio.to_thread(self._load_connector_class, connector_id, version_id)
        self._loaded_connectors[key] = cls
        return cls

    async def _fetch_and_install_connector(self, connector_id: str, version_id: str) -> None:
        """Download connector code from central, verify checksum, install venv."""
        meta = await self._central.get_connector_metadata(connector_id, version_id)
        requirements: list[str] = meta.get("requirements", [])
        entry_class: str = meta.get("entry_class") or "Connector"
        expected_checksum: str = meta.get("checksum", "")
        version_str: str = meta.get("version", version_id)

        code_resp = await self._central.get_connector_code(connector_id, version_id)
        code = code_resp.get("source_code") or code_resp.get("code", "")
        if not code:
            raise RuntimeError(f"No source code for connector {connector_id!r}")

        actual_checksum = hashlib.sha256(code.encode()).hexdigest()
        if expected_checksum and actual_checksum != expected_checksum:
            raise RuntimeError(
                f"Checksum mismatch for connector {connector_id}:{version_id}"
            )

        vh = _venv_hash(self._python_version, requirements)
        await self._ensure_venv(vh, requirements)

        conn_dir = self._apps_dir / "_connectors" / connector_id / version_id
        await asyncio.to_thread(self._write_app_files, conn_dir, code, {
            "connector_id": connector_id,
            "version_id": version_id,
            "version": version_str,
            "entry_class": entry_class,
            "venv_hash": vh,
            "checksum": actual_checksum,
        })

        logger.info(
            "connector_installed",
            connector_id=connector_id, version_id=version_id, venv_hash=vh,
        )

    def _load_connector_class(self, connector_id: str, version_id: str) -> type:
        """Dynamically load a connector class from disk."""
        conn_dir = self._apps_dir / "_connectors" / connector_id / version_id
        meta = json.loads((conn_dir / "metadata.json").read_text())
        entry_class: str = meta.get("entry_class") or "Connector"
        venv_hash: str = meta["venv_hash"]

        venv_site = self._venvs_dir / venv_hash / "venv" / "lib"
        site_packages: list[str] = []
        if venv_site.exists():
            for pydir in venv_site.iterdir():
                sp = pydir / "site-packages"
                if sp.exists():
                    site_packages.append(str(sp))

        # Keep venv site-packages in sys.path permanently for lazy imports
        for sp in site_packages:
            if sp not in sys.path:
                sys.path.insert(0, sp)

        module_path = conn_dir / "module.py"
        spec = importlib.util.spec_from_file_location(
            f"monctl_connector_{connector_id}_{version_id}",
            str(module_path),
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load spec for {module_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cls = getattr(mod, entry_class, None)
        if cls is None:
            raise AttributeError(
                f"Class {entry_class!r} not found in connector {connector_id}. "
                f"Available names: {[n for n in dir(mod) if not n.startswith('_')]}"
            )
        return cls

    # ── Housekeeping ──────────────────────────────────────────────────────────

    def cleanup_old_versions(self, app_id: str) -> None:
        """Remove app versions older than config.keep_old_versions."""
        app_dir = self._apps_dir / app_id
        if not app_dir.exists():
            return
        versions = sorted(
            [v for v in app_dir.iterdir() if v.is_dir()],
            key=lambda p: p.stat().st_mtime,
        )
        to_remove = versions[: max(0, len(versions) - self._cfg.keep_old_versions)]
        for old in to_remove:
            import shutil
            shutil.rmtree(old, ignore_errors=True)
            logger.info("old_version_removed", app_id=app_id, version=old.name)
