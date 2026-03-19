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
    String,
    Text,
    UniqueConstraint,
    text,
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
    reported_peer_states: Mapped[dict | None] = mapped_column(JSONB)
    load_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    effective_load: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    total_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    worker_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deadline_miss_rate: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    load_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    rejected_reason: Mapped[str | None] = mapped_column(Text)

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
    target_table: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="availability_latency"
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    versions: Mapped[list["AppVersion"]] = relationship(back_populates="app", cascade="all, delete-orphan")
    connector_bindings: Mapped[list["AppConnectorBinding"]] = relationship(
        back_populates="app", cascade="all, delete-orphan"
    )


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
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    display_template: Mapped[dict | None] = mapped_column(JSONB)

    app: Mapped[App] = relationship(back_populates="versions")


class DeviceType(Base):
    """User-defined device type catalogue (host, network, api, database, …)."""
    __tablename__ = "device_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    default_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    credentials: Mapped[dict] = mapped_column(
        "credentials", JSONB, nullable=False, server_default="{}"
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
    default_credential: Mapped["Credential | None"] = relationship(foreign_keys=[default_credential_id])
    assignments: Mapped[list["AppAssignment"]] = relationship(back_populates="device")


class Credential(Base):
    """An encrypted credential (SNMP community, SSH password, API key, etc.)."""
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credential_templates.id", ondelete="SET NULL"), nullable=True
    )
    secret_data: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256-GCM encrypted JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CredentialKey(Base):
    """Reusable credential field definitions (username, password, community, etc.)."""
    __tablename__ = "credential_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    key_type: Mapped[str] = mapped_column(String(16), nullable=False, default="plain")
    enum_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    @property
    def is_secret(self) -> bool:
        return self.key_type == "secret"


class CredentialTemplate(Base):
    """A template defining which credential keys belong to a credential type."""
    __tablename__ = "credential_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CredentialType(Base):
    """Managed list of credential types (snmpv3, ssh_password, api_key, etc.)."""
    __tablename__ = "credential_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CredentialValue(Base):
    """A key-value pair belonging to a credential."""
    __tablename__ = "credential_values"
    __table_args__ = (UniqueConstraint("credential_id", "key_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False
    )
    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credential_keys.id"), nullable=False
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)

    credential: Mapped["Credential"] = relationship()
    key: Mapped["CredentialKey"] = relationship()


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
    use_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
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
    credential: Mapped["Credential | None"] = relationship(foreign_keys=[credential_id])
    connector_bindings: Mapped[list["AssignmentConnectorBinding"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    credential_overrides: Mapped[list["AssignmentCredentialOverride"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    collector: Mapped[Collector | None] = relationship(back_populates="api_keys")
    user: Mapped["User | None"] = relationship(back_populates="api_keys", foreign_keys=[user_id])


# CheckResultRecord and EventRecord have been moved to ClickHouse.
# See storage/clickhouse.py for the ClickHouse schema.


class AppAlertDefinition(Base):
    """Alert definition attached to an app version."""
    __tablename__ = "app_alert_definitions"
    __table_args__ = (
        UniqueConstraint("app_version_id", "name", name="uq_alert_def_version_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    app_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    window: Mapped[str] = mapped_column(String(20), nullable=False, server_default="5m")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    message_template: Mapped[str | None] = mapped_column(Text)
    notification_channels: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    pack_origin: Mapped[str | None] = mapped_column(String(255))
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    app: Mapped["App"] = relationship()
    app_version: Mapped["AppVersion"] = relationship()
    instances: Mapped[list["AlertInstance"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class AlertInstance(Base):
    """Per-assignment instance of an alert definition. Tracks firing state."""
    __tablename__ = "alert_instances"
    __table_args__ = (
        UniqueConstraint("definition_id", "assignment_id", name="uq_instance_def_assignment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_alert_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_assignments.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ok")
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fire_history: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_created: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    entity_labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    definition: Mapped["AppAlertDefinition"] = relationship(back_populates="instances")
    assignment: Mapped["AppAssignment"] = relationship()


class ThresholdOverride(Base):
    """Per-device override for an alert definition's expression thresholds."""
    __tablename__ = "threshold_overrides"
    __table_args__ = (
        UniqueConstraint("definition_id", "device_id", "entity_key", name="uq_override_def_device_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_alert_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    overrides: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(8), unique=True, index=True)
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
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
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
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")
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

    assigned_role: Mapped["Role | None"] = relationship()
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", foreign_keys="ApiKey.user_id", cascade="all, delete-orphan"
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


class Role(Base):
    """A named role with a set of permissions."""
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """A single permission entry (resource + action) belonging to a role."""
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "resource", "action", name="uq_role_resource_action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)

    role: Mapped["Role"] = relationship(back_populates="permissions")


class SnmpOid(Base):
    """A catalog entry for an SNMP OID that can be selected for device monitoring."""
    __tablename__ = "snmp_oids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    oid: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class SystemSetting(Base):
    """Key-value system settings (e.g., retention policies)."""
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class TlsCertificate(Base):
    """TLS certificate for HTTPS termination."""
    __tablename__ = "tls_certificates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_pem_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_self_signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    subject_cn: Mapped[str] = mapped_column(String(255), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class InterfaceMetadata(Base):
    """Stable interface identity + cached metadata.
    PK (id) = interface_id. Lookup key = (device_id, if_name)."""
    __tablename__ = "interface_metadata"
    __table_args__ = (UniqueConstraint("device_id", "if_name", name="uq_device_if_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    if_name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_if_index: Mapped[int] = mapped_column(Integer, nullable=False)
    if_descr: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    if_alias: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    if_speed_mbps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    polling_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    alerting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    poll_metrics: Mapped[str] = mapped_column(String(50), nullable=False, server_default="all")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class LabelKey(Base):
    """Registry of allowed label keys for consistency across entities."""
    __tablename__ = "label_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(7))
    show_description: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    predefined_values: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Template(Base):
    """Reusable monitoring template for bulk device configuration."""
    __tablename__ = "templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class PythonModule(Base):
    """Registry of approved Python packages."""
    __tablename__ = "python_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(String(500))
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    versions: Mapped[list["PythonModuleVersion"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )


class PythonModuleVersion(Base):
    """A specific version of a registered Python module."""
    __tablename__ = "python_module_versions"
    __table_args__ = (UniqueConstraint("module_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("python_modules.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    dependencies: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    python_requires: Mapped[str | None] = mapped_column(String(100))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    module: Mapped["PythonModule"] = relationship(back_populates="versions")
    wheel_files: Mapped[list["WheelFile"]] = relationship(
        back_populates="module_version", cascade="all, delete-orphan"
    )


class WheelFile(Base):
    """Stored .whl file for distribution to collectors via PEP 503."""
    __tablename__ = "wheel_files"
    __table_args__ = (UniqueConstraint("filename"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("python_module_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    python_tag: Mapped[str] = mapped_column(String(50), nullable=False)
    abi_tag: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_tag: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    module_version: Mapped["PythonModuleVersion"] = relationship(back_populates="wheel_files")


class Connector(Base):
    """A reusable connector (SNMP, SSH, HTTP, etc.) that can be bound to assignments."""
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requirements: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    versions: Mapped[list["ConnectorVersion"]] = relationship(
        back_populates="connector", cascade="all, delete-orphan"
    )


class ConnectorVersion(Base):
    """A specific version of a connector with source code."""
    __tablename__ = "connector_versions"
    __table_args__ = (UniqueConstraint("connector_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entry_class: Mapped[str] = mapped_column(String(64), nullable=False, default="Connector")
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    connector: Mapped["Connector"] = relationship(back_populates="versions")


class EventPolicy(Base):
    """Defines when an alert should be promoted to an event."""
    __tablename__ = "event_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_alert_definitions.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="consecutive")
    fire_count_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    event_severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_clear_on_resolve: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    definition: Mapped["AppAlertDefinition"] = relationship()


class AssignmentConnectorBinding(Base):
    """Binds a connector (with optional credential) to an app assignment."""
    __tablename__ = "assignment_connector_bindings"
    __table_args__ = (UniqueConstraint("assignment_id", "alias"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_assignments.id", ondelete="CASCADE"), nullable=False
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="RESTRICT"), nullable=False
    )
    connector_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="RESTRICT"), nullable=False
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    use_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    assignment: Mapped["AppAssignment"] = relationship(back_populates="connector_bindings")


class AppConnectorBinding(Base):
    """Declares a connector requirement for an app.

    An app can require multiple connectors (e.g., SNMP + SSH).
    Each binding has an alias that the app uses to reference the connector
    in its code via context.connectors[alias].
    """
    __tablename__ = "app_connector_bindings"
    __table_args__ = (
        UniqueConstraint("app_id", "alias", name="uq_app_connector_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="RESTRICT"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    use_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    connector_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="SET NULL"), nullable=True
    )
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    app: Mapped["App"] = relationship(back_populates="connector_bindings")
    connector: Mapped["Connector"] = relationship()
    connector_version: Mapped["ConnectorVersion | None"] = relationship()


class AssignmentCredentialOverride(Base):
    """Per-assignment credential override for a specific connector alias."""
    __tablename__ = "assignment_credential_overrides"
    __table_args__ = (
        UniqueConstraint("assignment_id", "alias", name="uq_assignment_cred_override_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_assignments.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False
    )

    assignment: Mapped["AppAssignment"] = relationship(back_populates="credential_overrides")


class Pack(Base):
    """A monitoring pack — a bundle of configuration entities."""
    __tablename__ = "packs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    current_version: Mapped[str] = mapped_column(String(32), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    versions: Mapped[list["PackVersion"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan"
    )


class PackVersion(Base):
    """A specific version of an installed pack."""
    __tablename__ = "pack_versions"
    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_pack_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    changelog: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    pack: Mapped["Pack"] = relationship(back_populates="versions")


class AppCache(Base):
    """Shared cache for app data replicated across collector groups.

    Scoped by collector_group_id + app_id + device_id + cache_key.
    Collectors push/pull entries via the collector API.
    """
    __tablename__ = "app_cache"
    __table_args__ = (
        UniqueConstraint(
            "collector_group_id", "app_id", "device_id", "cache_key",
            name="uq_app_cache_entry",
        ),
        Index("ix_app_cache_group_updated", "collector_group_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collector_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collector_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("apps.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    cache_key: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
