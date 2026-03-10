"""Credential management endpoints.

Credentials are stored encrypted at rest (AES-256-GCM).
Values are NEVER returned by the API — only name, type, and description.

To reference a credential in an app assignment config, use:
    "some_field": "$credential:my-credential-name"

Central resolves these references before sending config to the collector.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from monctl_central.credentials.crypto import encrypt_dict
from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import Credential
from monctl_common.utils import utc_now

router = APIRouter()


class CreateCredentialRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "SNMP community string",
                    "value": {
                        "name": "snmp-prod-community",
                        "description": "Production SNMP v2c read community",
                        "credential_type": "snmp_community",
                        "secret": {"community": "mySecretCommunity", "version": "2c"},
                    },
                },
                {
                    "summary": "SSH credentials",
                    "value": {
                        "name": "linux-admin-ssh",
                        "description": "Admin SSH login for Linux hosts",
                        "credential_type": "ssh_password",
                        "secret": {"username": "admin", "password": "s3cr3t!"},
                    },
                },
                {
                    "summary": "API key / token",
                    "value": {
                        "name": "datadog-api-key",
                        "description": "Datadog read-only API key",
                        "credential_type": "api_key",
                        "secret": {"key": "dd-api-abc123xyz"},
                    },
                },
            ]
        }
    }

    name: str = Field(description="Unique reference name used in config: `$credential:<name>`")
    description: str | None = Field(default=None)
    credential_type: str = Field(
        description="Type hint: 'snmp_community', 'ssh_password', 'api_key', 'token', etc."
    )
    secret: dict = Field(
        description=(
            "The secret key-value pairs. Encrypted with AES-256-GCM before storage. "
            "Never returned by the API. "
            "Keys are injected into the app config when the `$credential:name` reference is resolved."
        )
    )


class UpdateCredentialRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Rotate the secret",
                    "value": {
                        "secret": {"community": "newRotatedSecret", "version": "2c"},
                    },
                }
            ]
        }
    }

    description: str | None = None
    credential_type: str | None = None
    secret: dict | None = Field(default=None, description="New secret data (replaces existing)")


def _format_credential(c: Credential) -> dict:
    """Return credential metadata only — never the plaintext secret."""
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "credential_type": c.credential_type,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("")
async def list_credentials(
    credential_type: Optional[str] = Query(default=None, description="Filter by type"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List credentials (metadata only, no secret values)."""
    stmt = select(Credential)
    if credential_type:
        stmt = stmt.where(Credential.credential_type == credential_type)
    stmt = stmt.offset(offset).limit(limit)
    creds = (await db.execute(stmt)).scalars().all()
    return {
        "status": "success",
        "data": [_format_credential(c) for c in creds],
        "meta": {"limit": limit, "offset": offset, "count": len(creds)},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential(
    request: CreateCredentialRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new credential. The secret is encrypted before storage."""
    # Check for duplicate name
    existing = (
        await db.execute(select(Credential).where(Credential.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A credential named '{request.name}' already exists",
        )

    credential = Credential(
        name=request.name,
        description=request.description,
        credential_type=request.credential_type,
        secret_data=encrypt_dict(request.secret),
    )
    db.add(credential)
    await db.flush()
    return {
        "status": "success",
        "data": _format_credential(credential),
    }


@router.get("/{credential_id}")
async def get_credential(
    credential_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get credential metadata by ID including its key composition (no secret values)."""
    from monctl_central.storage.models import CredentialValue, CredentialKey

    cred = await db.get(Credential, uuid.UUID(credential_id))
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    # Fetch credential values with their key definitions
    stmt = (
        select(CredentialValue, CredentialKey)
        .join(CredentialKey, CredentialValue.key_id == CredentialKey.id)
        .where(CredentialValue.credential_id == cred.id)
    )
    rows = (await db.execute(stmt)).all()
    values = [
        {"key_name": row.CredentialKey.name, "is_secret": row.CredentialKey.is_secret}
        for row in rows
    ]

    data = _format_credential(cred)
    data["values"] = values
    return {"status": "success", "data": data}


@router.put("/{credential_id}")
async def update_credential(
    credential_id: str,
    request: UpdateCredentialRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a credential. If secret is provided, it replaces the existing secret."""
    cred = await db.get(Credential, uuid.UUID(credential_id))
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    if request.description is not None:
        cred.description = request.description
    if request.credential_type is not None:
        cred.credential_type = request.credential_type
    if request.secret is not None:
        cred.secret_data = encrypt_dict(request.secret)
    cred.updated_at = utc_now()

    return {"status": "success", "data": _format_credential(cred)}


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a credential."""
    cred = await db.get(Credential, uuid.UUID(credential_id))
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    await db.delete(cred)
