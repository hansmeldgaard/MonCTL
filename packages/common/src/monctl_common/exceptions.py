"""Shared domain exceptions."""


from __future__ import annotations

class MonctlError(Exception):
    """Base exception for all MonCTL errors."""


class AuthenticationError(MonctlError):
    """Invalid or missing authentication credentials."""


class AuthorizationError(MonctlError):
    """Insufficient permissions for the requested action."""


class CollectorNotFoundError(MonctlError):
    """Collector with the given ID does not exist."""


class AppNotFoundError(MonctlError):
    """App with the given ID does not exist."""


class AssignmentNotFoundError(MonctlError):
    """Assignment with the given ID does not exist."""


class ClusterNotFoundError(MonctlError):
    """Cluster with the given ID does not exist."""


class ConfigVersionConflictError(MonctlError):
    """Config version mismatch (stale update)."""


class IngestionError(MonctlError):
    """Error during data ingestion."""


class AppExecutionError(MonctlError):
    """Error during app execution on a collector."""


class BufferFullError(MonctlError):
    """Local buffer is full and cannot accept more data."""


class CentralUnreachableError(MonctlError):
    """Cannot reach the central server."""
