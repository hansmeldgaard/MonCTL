"""Shared constants for MonCTL."""

from __future__ import annotations

from enum import IntEnum


class CheckState(IntEnum):
    """State of a monitoring check result."""

    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


class CollectorStatus(str):
    """Status of a collector as tracked by central."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    DEAD = "DEAD"


class PeerState(str):
    """Membership state of a peer in a collector cluster."""

    ALIVE = "ALIVE"
    SUSPECT = "SUSPECT"
    DEAD = "DEAD"


# API key prefixes
COLLECTOR_KEY_PREFIX = "monctl_c_"
MANAGEMENT_KEY_PREFIX = "monctl_m_"
USER_KEY_PREFIX = "monctl_u_"

# Default intervals (seconds)
DEFAULT_HEARTBEAT_INTERVAL = 30
DEFAULT_PUSH_INTERVAL = 10
DEFAULT_GOSSIP_INTERVAL = 3
DEFAULT_SUSPECT_TIMEOUT = 15
DEFAULT_APP_TIMEOUT = 30
DEFAULT_APP_MEMORY_MB = 256

# Default ports
DEFAULT_CENTRAL_PORT = 8443
DEFAULT_PEER_PORT = 9901

# Ingestion defaults
DEFAULT_BATCH_SIZE = 1000
DEFAULT_FLUSH_INTERVAL = 5.0
DEFAULT_MAX_QUEUE_SIZE = 50000

# Buffer defaults
DEFAULT_BUFFER_MAX_SIZE_MB = 500
DEFAULT_MAX_RETRIES = 10
