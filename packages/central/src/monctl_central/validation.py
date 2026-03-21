"""Validation error helpers for structured field-level API responses."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_exception_handler(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    """Convert Pydantic validation errors to structured field-level response."""
    field_errors: dict[str, list[str]] = {}
    for error in exc.errors():
        loc = error.get("loc", ())
        field_path = ".".join(str(part) for part in loc if part != "body")
        if not field_path:
            field_path = "_root"
        msg = error.get("msg", "Invalid value")
        field_errors.setdefault(field_path, []).append(msg)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation failed",
                "details": {"fields": field_errors},
            },
        },
    )


def raise_field_error(field: str, message: str, status_code: int = 400) -> None:
    """Raise an HTTPException with structured field-level error detail."""
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": "VALIDATION_ERROR",
            "message": message,
            "details": {"fields": {field: [message]}},
        },
    )
