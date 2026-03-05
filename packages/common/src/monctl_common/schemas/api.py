"""API envelope schemas for consistent response formatting."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """Pagination metadata included in list responses."""

    page: int = Field(ge=1, description="Current page number")
    per_page: int = Field(ge=1, le=1000, description="Items per page")
    total: int = Field(ge=0, description="Total number of items")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response envelope."""

    status: str = "success"
    data: T
    meta: PaginationMeta | None = None


class ErrorDetail(BaseModel):
    """Structured error detail."""

    code: str = Field(description="Machine-readable error code (e.g., 'COLLECTOR_NOT_FOUND')")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional error context")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    status: str = "error"
    error: ErrorDetail
