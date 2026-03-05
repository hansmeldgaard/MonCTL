"""MonCTL shared schemas."""

from __future__ import annotations

from monctl_common.schemas.api import ErrorDetail, ErrorResponse, PaginationMeta, SuccessResponse
from monctl_common.schemas.config import AppAssignmentConfig, CollectorConfig, ScheduleConfig
from monctl_common.schemas.metrics import CheckResult, Event, IngestPayload, Metric

__all__ = [
    "AppAssignmentConfig",
    "CheckResult",
    "CollectorConfig",
    "ErrorDetail",
    "ErrorResponse",
    "Event",
    "IngestPayload",
    "Metric",
    "PaginationMeta",
    "ScheduleConfig",
    "SuccessResponse",
]
