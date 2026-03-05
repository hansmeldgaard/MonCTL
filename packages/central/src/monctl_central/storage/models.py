"""SQLAlchemy ORM models for MonCTL central server."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class CollectorCluster(Base):
    __tablename__ = "collector_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    replication_factor: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    peer_port: Mapped[int] = mapped_column(Integer, nullable=False, default=9901)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    collectors: Mapped[list["Collector"]] = relationship(back_populates="cluster")


class Collector(Base):
    __tablename__ = "collectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    ip_addresses: Mapped[dict | None] = mapped_column(JSONB)
    os_info: Mapped[dict | None] = mapped_column(JSONB)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_clusters.id"), nullable=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_groups.id", ondelete="SET NULL"), nullable=True
    )
    peer_address: Mapped[str | None] = mapped_column(String(255))

    cluster: Mapped[CollectorCluster | None] = relationship(back_populates="collectors")
    group: Mapped["CollectorGroup | None"] = relationship(back_populates="collectors", foreign_keys=[group_id])
    assignments: Mapped[list["AppAssignment"]] = relationship(back_populates="collector")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="collector")


class CollectorGroup(Base):
    __tablename__ = "collector_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    label_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    collectors: Mapped[list["Collector"]] = relationship(back_populates="group", foreign_keys="Collector.group_id")
    devices: Mapped[list["Device"]] = relationship(back_populates="collector_group", foreign_keys="Device.collector_group_id")


class App(Base):
    __tablename__ = "apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    app_type: Mapped[str] = mapped_column(String(20), nullable=False)
    config_schema: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    versions: Mapped[list["AppVersion"]] = relationship(back_populates="app", cascade="all, delete-orphan")


class AppVersion(Base):
    __tablename__ = "app_versions"
    __table_args__ = (UniqueConstraint("app_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    archive_path: Mapped[str | None] = mapped_column(String(500))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    # Collector API fields — set when uploading poll app source code
    source_code: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    entry_class: Mapped[str | None] = mapped_column(String(200))

    app: Mapped[App] = relationship(back_populates="versions")


class DeviceType(Base):
    """User-defined device type catalogue (host, network, api, database, …)."""
    __tablename__ = "device_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class Device(Base):
    """A monitored device/target (server, router, API endpoint, etc.)."""
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, default="host")
    collector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collectors.id"), nullable=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    collector_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_groups.id", ondelete="SET NULL"), nullable=True
    )
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    tenant: Mapped["Tenant | None"] = relationship(foreign_keys=[tenant_id])
    collector_group: Mapped["CollectorGroup | None"] = relationship(back_populates="devices", foreign_keys=[collector_group_id])
    assignments: Mapped[list["AppAssignment"]] = relationship(back_populates="device")


class Credential(Base):
    """An encrypted credential (SNMP community, SSH password, API key, etc.)."""
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_data: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256-GCM encrypted JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AppAssignment(Base):
    __tablename__ = "app_assignments"
    __table_args__ = (
        UniqueConstraint("app_id", "collector_id", "config", name="uq_app_collector_config"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id"), nullable=False
    )
    app_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_versions.id"), nullable=False
    )
    collector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collectors.id"), nullable=True
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_clusters.id"), nullable=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_value: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_limits: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{"timeout_seconds": 30, "memory_mb": 256}'
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Optional role for structured monitoring checks: "availability" | "latency" | None
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    collector: Mapped[Collector | None] = relationship(back_populates="assignments")
    device: Mapped["Device | None"] = relationship(back_populates="assignments")
    app: Mapped[App] = relationship()
    app_version: Mapped[AppVersion] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_type: Mapped[str] = mapped_column(String(20), nullable=False)
    collector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collectors.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='["*"]')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    collector: Mapped[Collector | None] = relationship(back_populates="api_keys")


class CheckResultRecord(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    collector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    performance_data: Mapped[dict | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    execution_time: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("idx_check_results_assignment_time", "assignment_id", executed_at.desc()),
        Index("idx_check_results_collector_time", "collector_id", executed_at.desc()),
        Index("idx_check_results_state", "state", postgresql_where=(state > 0)),
    )


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("idx_events_collector_time", "collector_id", occurred_at.desc()),
        Index("idx_events_severity", "severity", occurred_at.desc()),
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    notification_channels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    states: Mapped[list["AlertState"]] = relationship(back_populates="rule")


class AlertState(Base):
    __tablename__ = "alert_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    annotations: Mapped[dict | None] = mapped_column(JSONB)

    rule: Mapped[AlertRule] = relationship(back_populates="states")


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    one_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_clusters.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tenant(Base):
    """Tenant for multi-tenancy device isolation."""
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    user_assignments: Mapped[list["UserTenant"]] = relationship(back_populates="tenant")


class User(Base):
    """A user account for web UI authentication."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    # Legacy single-tenant FK (kept for backward compat, not used for access control)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    # If True, user can see all devices regardless of tenant (like an admin but non-privileged)
    all_tenants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    tenant_assignments: Mapped[list["UserTenant"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserTenant(Base):
    """Many-to-many: which tenants a user is allowed to see."""
    __tablename__ = "user_tenants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped["User"] = relationship(back_populates="tenant_assignments")
    tenant: Mapped["Tenant"] = relationship(back_populates="user_assignments")


class SnmpOid(Base):
    """A catalog entry for an SNMP OID that can be selected for device monitoring."""
    __tablename__ = "snmp_oids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    oid: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
