"""FastAPI dependency injection providers."""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import sqlalchemy
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from monctl_central.config import settings
from monctl_common.utils import hash_api_key

# Database engine and session factory (initialized on startup)
_engine = None
_session_factory = None

# ClickHouse client singleton
_ch_client = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_clickhouse():
    """Return the ClickHouse client singleton."""
    global _ch_client
    if _ch_client is None:
        from monctl_central.storage.clickhouse import ClickHouseClient

        hosts = [h.strip() for h in settings.clickhouse_hosts.split(",") if h.strip()]
        _ch_client = ClickHouseClient(
            hosts=hosts,
            port=settings.clickhouse_port,
            database=settings.clickhouse_database,
            cluster_name=settings.clickhouse_cluster,
            async_insert=settings.clickhouse_async_insert,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
        )
    return _ch_client


# ---------------------------------------------------------------------------
# API Key auth (existing — used by collectors and management CLI/Postman)
# ---------------------------------------------------------------------------

_http_bearer = HTTPBearer(auto_error=True)
_http_bearer_optional = HTTPBearer(auto_error=False)


async def get_api_key(credentials: HTTPAuthorizationCredentials = Depends(_http_bearer)) -> dict:
    """Validate the Bearer token and return the API key record.

    Returns a dict with: key_type, collector_id, scopes, auth_type.
    """
    return await _validate_api_key(credentials.credentials)


async def _validate_api_key(token: str) -> dict:
    """Shared logic for API key validation with Redis caching."""
    token_hash = hash_api_key(token)

    # Check Redis cache first
    from monctl_central.cache import get_cached_api_key, set_cached_api_key

    cached = await get_cached_api_key(token_hash)
    if cached is not None:
        return cached

    from sqlalchemy import select, update
    from monctl_central.storage.models import ApiKey
    from monctl_common.utils import utc_now

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(ApiKey).where(ApiKey.key_hash == token_hash)
        result = await session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        if api_key.expires_at is not None:
            if api_key.expires_at < utc_now():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key has expired",
                )

        # Update last_used_at (batched via cache — only hits DB on cache miss)
        await session.execute(
            update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=utc_now())
        )
        await session.commit()

        result_dict = {
            "key_type": api_key.key_type,
            "collector_id": str(api_key.collector_id) if api_key.collector_id else None,
            "scopes": api_key.scopes,
            "auth_type": "api_key",
            "tenant_ids": None,  # Management API keys see everything
        }

        # Cache the result
        await set_cached_api_key(token_hash, result_dict)

        return result_dict


async def require_collector_key(api_key: dict = Depends(get_api_key)) -> dict:
    """Require a collector API key."""
    if api_key["key_type"] != "collector":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Collector API key required",
        )
    return api_key


async def require_management_key(api_key: dict = Depends(get_api_key)) -> dict:
    """Require a management API key."""
    if api_key["key_type"] != "management":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Management API key required",
        )
    return api_key


# ---------------------------------------------------------------------------
# JWT cookie auth (new — used by web UI)
# ---------------------------------------------------------------------------

async def _get_user_from_cookie(request: Request, db: AsyncSession) -> dict | None:
    """Extract and validate the JWT access token from the cookie.

    Loads tenant restrictions from the user_tenants table.
    Returns None if no cookie or invalid token (does not raise).
    """
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from sqlalchemy import select
        from monctl_central.auth.service import decode_token
        from monctl_central.storage.models import User, UserTenant

        payload = decode_token(token)
        if payload.get("type") != "access":
            return None

        user_id = payload["sub"]
        role = payload["role"]

        # Admins always see everything
        if role == "admin":
            tenant_ids = None
        else:
            # Load user record for all_tenants flag
            user = await db.get(User, uuid.UUID(user_id))
            if user is None or not user.is_active:
                return None

            if user.all_tenants:
                tenant_ids = None
            else:
                # Load tenant assignments
                rows = (await db.execute(
                    select(UserTenant.tenant_id).where(
                        UserTenant.user_id == uuid.UUID(user_id)
                    )
                )).scalars().all()
                tenant_ids = [str(tid) for tid in rows]

        return {
            "user_id": user_id,
            "username": payload["username"],
            "role": role,
            "auth_type": "user",
            "tenant_ids": tenant_ids,
            "role_id": str(user.role_id) if (role != "admin" and user and user.role_id) else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dual auth: accepts EITHER JWT cookie OR Bearer API key
# ---------------------------------------------------------------------------

async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer_optional),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept JWT cookie OR management Bearer API key.

    Returns a dict with auth_type ('user' or 'api_key') plus relevant metadata,
    including tenant_ids (None = unrestricted, [] = see nothing, [ids] = specific).
    """
    # 1. Try JWT cookie first
    user = await _get_user_from_cookie(request, db)
    if user:
        return user

    # 2. Try Bearer API key
    if credentials:
        try:
            api_key = await _validate_api_key(credentials.credentials)
            if api_key["key_type"] == "management":
                return api_key
        except HTTPException:
            pass  # Fall through to the 401 below

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (JWT cookie or management API key)",
    )


async def require_admin(auth: dict = Depends(require_auth)) -> dict:
    """Require admin role."""
    if auth.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return auth


async def _load_user_permissions(db: AsyncSession, user_id: str) -> set[str]:
    """Load permissions for a user as a set of 'resource:action' strings."""
    from monctl_central.cache import _redis

    cache_key = f"user_perms:{user_id}"
    if _redis:
        cached = await _redis.get(cache_key)
        if cached is not None:
            import json
            return set(json.loads(cached))

    from sqlalchemy import select
    from monctl_central.storage.models import User, RolePermission

    user = await db.get(User, uuid.UUID(user_id))
    if user is None or user.role_id is None:
        return set()

    rows = (await db.execute(
        select(RolePermission.resource, RolePermission.action).where(
            RolePermission.role_id == user.role_id
        )
    )).all()

    perms = {f"{r.resource}:{r.action}" for r in rows}

    if _redis:
        import json
        await _redis.set(cache_key, json.dumps(list(perms)), ex=300)

    return perms


def require_permission(resource: str, action: str):
    """FastAPI dependency factory: require that the user has a specific permission.

    Admins always pass. Non-admin users must have the permission in their role.
    """
    async def _check(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer_optional),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        auth = await require_auth(request, credentials, db)

        # Admins and API keys bypass permission checks
        if auth.get("role") == "admin" or auth.get("auth_type") == "api_key":
            return auth

        perms = await _load_user_permissions(db, auth["user_id"])
        if f"{resource}:{action}" not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {resource}:{action}",
            )

        auth["permissions"] = perms
        return auth

    return _check


async def require_collector_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer_optional),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Auth for the /api/v1/ collector endpoints.

    Accepts (in priority order):
      1. Shared secret:  Authorization: Bearer <MONCTL_COLLECTOR_API_KEY env var>
      2. Management API key (from DB, as per require_auth)
      3. JWT cookie (admin session)

    Configure on central: MONCTL_COLLECTOR_API_KEY=<some secret>
    Configure on collector: CENTRAL_API_KEY=<same secret>
    """
    import os

    shared_secret = os.environ.get("MONCTL_COLLECTOR_API_KEY", "")

    if credentials and shared_secret and credentials.credentials == shared_secret:
        return {"auth_type": "collector_shared_secret", "tenant_ids": None}

    # Fall back to regular auth (JWT cookie or management API key)
    return await require_auth(request, credentials, db)


# ---------------------------------------------------------------------------
# Tenant filtering helpers
# ---------------------------------------------------------------------------

def apply_tenant_filter(stmt, auth: dict, device_tenant_col):
    """Apply tenant restriction to a SQLAlchemy statement.

    - tenant_ids = None  → unrestricted (admin / all_tenants / api_key)
    - tenant_ids = []    → see nothing (user has no tenant assignments)
    - tenant_ids = [ids] → filter to those tenant IDs only
    """
    tenant_ids = auth.get("tenant_ids")
    if tenant_ids is None:
        return stmt  # unrestricted
    if len(tenant_ids) == 0:
        return stmt.where(sqlalchemy.false())  # see nothing
    uuids = [uuid.UUID(t) for t in tenant_ids]
    return stmt.where(device_tenant_col.in_(uuids))


def check_tenant_access(auth: dict, device_tenant_id) -> bool:
    """Check if auth context allows access to a device with the given tenant_id.

    Returns True if allowed, False otherwise.
    """
    tenant_ids = auth.get("tenant_ids")
    if tenant_ids is None:
        return True  # unrestricted
    if len(tenant_ids) == 0:
        return False  # see nothing
    if device_tenant_id is None:
        return False  # device has no tenant, restricted users can't see it
    return str(device_tenant_id) in tenant_ids
