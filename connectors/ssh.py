"""Built-in SSH connector for MonCTL."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SshConnector:
    """SSH connector that executes commands on a remote host."""

    def __init__(self, settings: dict[str, Any], credential: dict[str, Any] | None = None):
        self.settings = settings
        self.credential = credential or {}
        self.username = self.credential.get("username", "root")
        self.password = self.credential.get("password")
        self.private_key = self.credential.get("private_key")
        self.port = int(self.settings.get("port", 22))
        self.timeout = int(self.settings.get("timeout", 10))
        self._conn = None

    async def connect(self, host: str) -> None:
        """Open an SSH connection to the given host."""
        import asyncssh

        kwargs: dict[str, Any] = {
            "host": host,
            "port": self.port,
            "username": self.username,
            "known_hosts": None,
            "login_timeout": self.timeout,
        }
        if self.private_key:
            kwargs["client_keys"] = [asyncssh.import_private_key(self.private_key)]
        elif self.password:
            kwargs["password"] = self.password

        self._conn = await asyncssh.connect(**kwargs)
        logger.debug("ssh_connected", host=host, port=self.port, user=self.username)

    async def run(self, command: str) -> dict[str, Any]:
        """Execute a command and return stdout, stderr, and exit_status."""
        if self._conn is None:
            raise RuntimeError("Not connected — call connect() first")
        result = await self._conn.run(command, timeout=self.timeout)
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_status": result.exit_status,
        }

    async def close(self) -> None:
        """Close the SSH connection."""
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
