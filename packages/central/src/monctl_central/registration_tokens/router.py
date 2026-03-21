"""Registration token management endpoints."""

from __future__ import annotations

import hashlib
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_admin
from monctl_central.storage.models import RegistrationToken

router = APIRouter()

# Characters for short registration codes (uppercase + digits, no ambiguous chars)
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _generate_short_code(length: int = 6) -> str:
    """Generate a short, easy-to-type registration code like 'A3X9K2'."""
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(length))


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human-readable token name")
    one_time: bool = Field(default=False, description="Token can only be used once")
    cluster_id: str | None = Field(default=None, description="Restrict to a specific cluster")
    expires_at: str | None = Field(default=None, description="ISO 8601 expiry timestamp")

    @field_validator("cluster_id")
    @classmethod
    def check_cluster_id(cls, v: str | None) -> str | None:
        if v is not None:
            validate_uuid(v, "cluster_id")
        return v

    @field_validator("expires_at")
    @classmethod
    def check_expires_at(cls, v: str | None) -> str | None:
        if v is not None:
            from datetime import datetime
            try:
                datetime.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError("expires_at must be a valid ISO 8601 timestamp")
        return v


def _fmt(t: RegistrationToken) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "short_code": t.short_code,
        "one_time": t.one_time,
        "used": t.used,
        "cluster_id": str(t.cluster_id) if t.cluster_id else None,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("")
async def list_registration_tokens(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all registration tokens (never exposes the hash)."""
    rows = (
        await db.execute(select(RegistrationToken).order_by(RegistrationToken.created_at.desc()))
    ).scalars().all()
    return {"status": "success", "data": [_fmt(t) for t in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_registration_token(
    request: CreateTokenRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Create a registration token. Returns a short registration code."""
    from datetime import datetime

    # Generate both a long token (for backward compat) and a short code
    raw_token = f"monctl_rt_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Generate unique short code (retry on collision)
    for _ in range(10):
        code = _generate_short_code()
        existing = await db.execute(
            select(RegistrationToken).where(RegistrationToken.short_code == code)
        )
        if existing.scalar_one_or_none() is None:
            break
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate unique registration code",
        )

    expires = None
    if request.expires_at:
        expires = datetime.fromisoformat(request.expires_at)

    token = RegistrationToken(
        name=request.name,
        token_hash=token_hash,
        short_code=code,
        one_time=request.one_time,
        cluster_id=uuid.UUID(request.cluster_id) if request.cluster_id else None,
        expires_at=expires,
    )
    db.add(token)
    await db.flush()

    result = _fmt(token)
    result["token"] = raw_token  # Legacy — still returned for backward compat
    return {"status": "success", "data": result}


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration_token(
    token_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete/revoke a registration token."""
    token = await db.get(RegistrationToken, uuid.UUID(token_id))
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    await db.delete(token)
