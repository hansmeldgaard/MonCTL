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
    template_id: str | None = Field(
        default=None, description="UUID of the credential template to use"
    )
    credential_type: str | None = Field(
        default=None,
        description="Type hint: 'snmp_community', 'ssh_password', etc. Ignored if template_id is set.",
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
        "template_id": str(c.template_id) if c.template_id else None,
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

    template_id = None
    credential_type = request.credential_type or "custom"
    secret_to_store = request.secret

    if request.template_id:
        from monctl_central.storage.models import CredentialTemplate, CredentialKey

        template = await db.get(CredentialTemplate, uuid.UUID(request.template_id))
        if template is None:
            raise HTTPException(status_code=400, detail="Credential template not found")

        template_id = template.id
        credential_type = template.name

        # Load credential key definitions for enum validation
        key_names = {f["key_name"] for f in template.fields}
        key_rows = (await db.execute(
            select(CredentialKey).where(CredentialKey.name.in_(key_names))
        )).scalars().all()
        keys_by_name = {k.name: k for k in key_rows}

        # Validate required fields + enum values
        for field in template.fields:
            key_name = field["key_name"]
            value = request.secret.get(key_name)

            if field.get("required") and value is None and field.get("default_value") is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required field: {key_name}",
                )

            if value is not None:
                key_def = keys_by_name.get(key_name)
                if key_def and key_def.key_type == "enum" and key_def.enum_values:
                    if value not in key_def.enum_values:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid value for '{key_name}': '{value}'. "
                                   f"Must be one of: {', '.join(key_def.enum_values)}",
                        )

        # Merge defaults for missing optional fields
        merged = {}
        for field in template.fields:
            key = field["key_name"]
            if key in request.secret:
                merged[key] = request.secret[key]
            elif field.get("default_value") is not None:
                merged[key] = field["default_value"]
        for k, v in request.secret.items():
            if k not in merged:
                merged[k] = v
        secret_to_store = merged

    credential = Credential(
        name=request.name,
        description=request.description,
        credential_type=credential_type,
        template_id=template_id,
        secret_data=encrypt_dict(secret_to_store),
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
    from monctl_central.credentials.crypto import decrypt_dict
    from monctl_central.storage.models import CredentialKey

    cred = await db.get(Credential, uuid.UUID(credential_id))
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    # Derive key names from encrypted secret_data
    # Non-secret values are returned; secret values are masked
    values = []
    if cred.secret_data:
        try:
            secret_dict = decrypt_dict(cred.secret_data)
            key_names = list(secret_dict.keys())
            # Look up key definitions to determine is_secret
            key_rows = (await db.execute(
                select(CredentialKey).where(CredentialKey.name.in_(key_names))
            )).scalars().all()
            keys_by_name = {k.name: k for k in key_rows}
            values = [
                {
                    "key_name": name,
                    "is_secret": keys_by_name[name].is_secret if name in keys_by_name else False,
                    "value": None if (name in keys_by_name and keys_by_name[name].is_secret) else secret_dict[name],
                }
                for name in key_names
            ]
        except Exception:
            pass  # If decryption fails, return empty values

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
        # Merge with existing secret data so unchanged fields are preserved
        from monctl_central.credentials.crypto import decrypt_dict as _decrypt
        existing = {}
        if cred.secret_data:
            try:
                existing = _decrypt(cred.secret_data)
            except Exception:
                pass
        existing.update(request.secret)
        cred.secret_data = encrypt_dict(existing)
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
