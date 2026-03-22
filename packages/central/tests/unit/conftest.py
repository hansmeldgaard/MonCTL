"""Unit test fixtures — SQLite in-memory, no external services."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB

from monctl_central.storage.models import Base
from monctl_central.auth.service import hash_password

# ── JSONB → JSON shim for SQLite ──────────────────────────────────────────────
# SQLAlchemy's JSONB type doesn't have a SQLite implementation.
# We register a before-create hook that swaps JSONB columns to JSON.

def _patch_jsonb_for_sqlite():
    """Make JSONB render as JSON on SQLite dialect."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, '_original_visit_JSON'):
        SQLiteTypeCompiler._original_visit_JSON = SQLiteTypeCompiler.visit_JSON  # type: ignore
    SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore

_patch_jsonb_for_sqlite()


@pytest.fixture
async def sqlite_engine():
    """Create an in-memory SQLite engine with PG compatibility shims."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_functions(dbapi_conn, connection_record):
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
        import datetime
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
        )

    async with engine.begin() as conn:
        import sqlalchemy as sa
        # Patch PG-specific server_defaults for SQLite compatibility
        for table in Base.metadata.tables.values():
            for col in table.columns:
                sd = col.server_default
                if sd is None:
                    continue
                sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
                if "now()" in sd_text:
                    # Replace PG now() with SQLite CURRENT_TIMESTAMP
                    col.server_default = sa.schema.DefaultClause(
                        sa.text("CURRENT_TIMESTAMP")
                    )
                elif "gen_random_uuid" in sd_text:
                    # Remove — Python-side default=uuid.uuid4 handles it
                    col.server_default = None
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(sqlite_engine) -> AsyncSession:
    """Provide a transactional session that rolls back after each test."""
    session_factory = async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seeded_session(db_session: AsyncSession) -> AsyncSession:
    """Session with seed data: admin user, default device types."""
    from monctl_central.storage.models import User, DeviceType

    admin = User(
        username="admin",
        password_hash=hash_password("changeme"),
        role="admin",
        display_name="Test Admin",
    )
    db_session.add(admin)

    for name, desc, cat in [
        ("host", "Generic server", "server"),
        ("network", "Network device", "network"),
    ]:
        db_session.add(DeviceType(name=name, description=desc, category=cat))

    await db_session.flush()
    return db_session


@pytest.fixture
def mock_clickhouse() -> MagicMock:
    """Mock ClickHouseClient — all CH calls return empty results."""
    mock = MagicMock()
    mock.query = AsyncMock(return_value=[])
    mock.query_latest = AsyncMock(return_value=[])
    mock.query_history = AsyncMock(return_value=[])
    mock.insert = AsyncMock(return_value=None)
    mock.execute = AsyncMock(return_value=None)
    mock.ensure_tables = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    mock.exists = AsyncMock(return_value=0)
    return mock


@pytest.fixture
async def client(
    db_session: AsyncSession,
    seeded_session: AsyncSession,
    mock_clickhouse: MagicMock,
    mock_redis: AsyncMock,
) -> AsyncClient:
    """AsyncClient wired to the FastAPI app with dependency overrides.

    Uses the SQLite session and mocked CH/Redis.
    Creates a test app with a no-op lifespan to avoid DB connection attempts.
    """
    from fastapi import FastAPI
    from monctl_central.main import app as real_app
    from monctl_central.dependencies import get_db, get_clickhouse
    from monctl_central import cache

    async def _override_db():
        yield seeded_session

    real_app.dependency_overrides[get_db] = _override_db
    real_app.dependency_overrides[get_clickhouse] = lambda: mock_clickhouse

    # Patch Redis global
    original_redis = cache._redis
    cache._redis = mock_redis

    # Override lifespan to avoid startup DB connections
    original_router_lifespan = real_app.router.lifespan_context

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    real_app.router.lifespan_context = _noop_lifespan

    transport = ASGITransport(app=real_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    real_app.dependency_overrides.clear()
    real_app.router.lifespan_context = original_router_lifespan
    cache._redis = original_redis


@pytest.fixture
async def auth_client(client: AsyncClient, admin_credentials: dict) -> AsyncClient:
    """Client with a valid admin JWT cookie attached."""
    resp = await client.post("/v1/auth/login", json=admin_credentials)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    client.cookies = resp.cookies
    return client
