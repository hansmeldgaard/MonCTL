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
    LargeBinary,
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
    log_level_filter: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="INFO", default="INFO"
    )

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

    weight_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    weight_snapshot_topology: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

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
    vendor_oid_prefix: Mapped[str | None] = mapped_column(String(128), nullable=True)

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
    volatile_keys: Mapped[list | None] = mapped_column(JSONB, server_default="[]")
    eligibility_oids: Mapped[list | None] = mapped_column(JSONB)

    app: Mapped[App] = relationship(back_populates="versions")


class DeviceCategory(Base):
    """Device category catalogue (cisco-router, juniper-switch, host, network, …)."""
    __tablename__ = "device_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    icon: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="Icon identifier, e.g. 'router', 'switch', 'server', 'firewall', 'printer', 'cloud'"
    )
    icon_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="Custom icon image (PNG/SVG, max 256KB)")
    icon_mime_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="MIME type of custom icon")
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    template_bindings: Mapped[list["DeviceCategoryTemplateBinding"]] = relationship(
        back_populates="device_category", cascade="all, delete-orphan"
    )


class DeviceType(Base):
    """Specific device model/type with SNMP sysObjectID pattern for auto-discovery."""
    __tablename__ = "device_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sys_object_id_pattern: Mapped[str] = mapped_column(
        String(256), nullable=False, unique=True,
        comment="sysObjectID prefix to match, e.g. '1.3.6.1.4.1.2636.1.1.1.2.143' for Juniper MX204"
    )
    device_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_categories.id", ondelete="CASCADE"), nullable=False
    )
    vendor: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(255))
    os_family: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
        comment="Higher = preferred when multiple rules match. Longest prefix wins first, then priority."
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    auto_assign_packs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    device_category: Mapped["DeviceCategory"] = relationship(foreign_keys=[device_category_id])
    template_bindings: Mapped[list["DeviceTypeTemplateBinding"]] = relationship(
        back_populates="device_type", cascade="all, delete-orphan"
    )


class Device(Base):
    """A monitored device/target (server, router, API endpoint, etc.)."""
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    device_category: Mapped[str] = mapped_column(String(64), nullable=False, default="host")
    collector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collectors.id"), nullable=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    collector_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collector_groups.id", ondelete="SET NULL"), nullable=True
    )
    device_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    credentials: Mapped[dict] = mapped_column(
        "credentials", JSONB, nullable=False, server_default="{}"
    )
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    retention_overrides: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    interface_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    tenant: Mapped["Tenant | None"] = relationship(foreign_keys=[tenant_id])
    collector_group: Mapped["CollectorGroup | None"] = relationship(back_populates="devices", foreign_keys=[collector_group_id])
    device_type: Mapped["DeviceType | None"] = relationship(foreign_keys=[device_type_id])
    assignments: Mapped[list["AppAssignment"]] = relationship(back_populates="device", cascade="all, delete-orphan")


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
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
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
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True
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
    avg_execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)
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


class AlertDefinition(Base):
    """Alert definition attached to an app."""
    __tablename__ = "alert_definitions"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_alert_def_app_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    window: Mapped[str] = mapped_column(String(20), nullable=False, server_default="5m")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    message_template: Mapped[str | None] = mapped_column(Text)
    pack_origin: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    app: Mapped["App"] = relationship()
    entities: Mapped[list["AlertEntity"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class AlertEntity(Base):
    """Per-assignment entity of an alert definition. Tracks firing state."""
    __tablename__ = "alert_entities"
    __table_args__ = (
        UniqueConstraint("definition_id", "assignment_id", name="uq_instance_def_assignment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_definitions.id", ondelete="CASCADE"),
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
    started_firing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    entity_labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    metric_values: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    threshold_values: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    definition: Mapped["AlertDefinition"] = relationship(back_populates="entities")
    assignment: Mapped["AppAssignment"] = relationship()


class ThresholdVariable(Base):
    """Named threshold parameter on an app with a default value."""
    __tablename__ = "threshold_variables"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_threshold_var_app_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    default_value: Mapped[float] = mapped_column(Float, nullable=False)
    app_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    app: Mapped["App"] = relationship()


class ThresholdOverride(Base):
    """Per-device or per-entity override for a threshold variable."""
    __tablename__ = "threshold_overrides"
    __table_args__ = (
        UniqueConstraint("variable_id", "device_id", "entity_key", name="uq_threshold_override_var_device_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    variable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threshold_variables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    variable: Mapped["ThresholdVariable"] = relationship()


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
    table_page_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50", default=50)
    table_scroll_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="paginated", default="paginated")
    idle_timeout_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Per-user idle timeout override. NULL = use system default.",
    )
    iface_status_filter: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="all",
        comment="Default interface status filter: all | up | down | unmonitored",
    )
    iface_traffic_unit: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="auto",
        comment="Default traffic unit: auto | bps | kbps | mbps | pct",
    )
    iface_chart_metric: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="traffic",
        comment="Default chart metric: traffic | errors | discards",
    )
    iface_time_range: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="24h",
        comment="Default interface time range: 1h | 6h | 24h | 7d | 30d",
    )
    default_page: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="/", default="/",
        comment="Default landing page route for this user",
    )
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
    rules_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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

    category_bindings: Mapped[list["DeviceCategoryTemplateBinding"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )
    type_bindings: Mapped[list["DeviceTypeTemplateBinding"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class DeviceCategoryTemplateBinding(Base):
    """Links templates to device categories (many-to-many with priority)."""
    __tablename__ = "device_category_template_bindings"
    __table_args__ = (
        UniqueConstraint("device_category_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_categories.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
        comment="Higher priority templates override lower ones within same level"
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    device_category: Mapped["DeviceCategory"] = relationship(back_populates="template_bindings")
    template: Mapped["Template"] = relationship(back_populates="category_bindings")


class DeviceTypeTemplateBinding(Base):
    """Links templates to device types (many-to-many with priority)."""
    __tablename__ = "device_type_template_bindings"
    __table_args__ = (
        UniqueConstraint("device_type_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_types.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
        comment="Higher priority templates override lower ones within same level"
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    device_type: Mapped["DeviceType"] = relationship(back_populates="template_bindings")
    template: Mapped["Template"] = relationship(back_populates="type_bindings")


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
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
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


class IncidentRule(Base):
    """Operator-configured rule for promoting alerts to incidents.

    After phase deprecation (see docs/event-policy-rework.md) this is
    the only rule model in the system. Pre-existing rows with
    `source='mirror'` (auto-synced from the legacy EventPolicy table)
    were bulk-flipped to `source='native'` in alembic revision
    zq7r8s9t0u1v; the mirror-sync task and the `source_policy_id` FK
    were removed at the same time. New rules default to `'native'`.
    """
    __tablename__ = "incident_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="consecutive")
    fire_count_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_clear_on_resolve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Phase 2 configuration columns.
    scope_filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    severity_ladder: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    correlation_group: Mapped[str | None] = mapped_column(String(500), nullable=True)
    depends_on: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    flap_guard_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Companion-alert clear (phase follow-up after event-policy deprecation).
    # List of AlertDefinition UUIDs (as strings in JSONB) whose healthy
    # (resolved) state for the same entity should clear this incident.
    # `clear_companion_mode` decides how multiple companions combine:
    # "any" = clear if ANY companion is healthy, "all" = clear only when
    # every listed companion is healthy. Scoped by entity_key so the
    # clear only applies to the matching device/assignment.
    clear_on_companion_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    clear_companion_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="any"
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Retained for historical tagging: 'mirror' = pre-deprecation
    # auto-synced row (now editable as native), 'native' = operator-
    # authored. Defaults to 'native' for any new row created after
    # zq7r8s9t0u1v.
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="native")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    definition: Mapped["AlertDefinition"] = relationship()


class Incident(Base):
    """Persistent incident object tracked by the IncidentEngine (phase 1 shadow).

    Lifecycle in phase 1: open → cleared. Phase 2 adds acknowledged, suppressed.
    """
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_rules.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Phase 2 columns
    correlation_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
    )
    severity_reached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    rule: Mapped["IncidentRule"] = relationship()


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


class DataRetentionOverride(Base):
    """Per-device, per-app retention override for a specific ClickHouse data type."""
    __tablename__ = "data_retention_overrides"
    __table_args__ = (
        UniqueConstraint("device_id", "app_id", "data_type", name="uq_retention_device_app_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    data_type: Mapped[str] = mapped_column(String(30), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class SystemVersion(Base):
    """Tracks installed software versions per node."""
    __tablename__ = "system_versions"
    __table_args__ = (UniqueConstraint("node_hostname", name="uq_system_version_hostname"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    node_ip: Mapped[str] = mapped_column(String(50), nullable=False)
    monctl_version: Mapped[str | None] = mapped_column(String(50))
    docker_image_id: Mapped[str | None] = mapped_column(String(100))
    os_version: Mapped[str | None] = mapped_column(String(200))
    kernel_version: Mapped[str | None] = mapped_column(String(100))
    python_version: Mapped[str | None] = mapped_column(String(50))
    reboot_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class UpgradePackage(Base):
    """A MonCTL upgrade bundle stored on central."""
    __tablename__ = "upgrade_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    package_type: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    contains_central: Mapped[bool] = mapped_column(Boolean, server_default="false")
    contains_collector: Mapped[bool] = mapped_column(Boolean, server_default="false")
    uploaded_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class UpgradeJob(Base):
    """An orchestrated upgrade execution."""
    __tablename__ = "upgrade_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upgrade_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upgrade_packages.id"), nullable=False)
    target_version: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'pending'")
    started_by: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    steps: Mapped[list["UpgradeJobStep"]] = relationship(back_populates="job", cascade="all, delete-orphan", order_by="UpgradeJobStep.step_order")


class UpgradeJobStep(Base):
    """Individual step in an upgrade job (one per node)."""
    __tablename__ = "upgrade_job_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upgrade_jobs.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    node_ip: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'pending'")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_log: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    job: Mapped["UpgradeJob"] = relationship(back_populates="steps")


class OsUpdatePackage(Base):
    """Cached OS package (.deb) available for distribution."""
    __tablename__ = "os_update_packages"
    __table_args__ = (UniqueConstraint("package_name", "version", "architecture"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    architecture: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'amd64'")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), server_default="'normal'")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    is_downloaded: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class OsAvailableUpdate(Base):
    """An available OS package update detected on a node."""
    __tablename__ = "os_available_updates"
    __table_args__ = (
        UniqueConstraint("node_hostname", "package_name", name="uq_os_update_node_pkg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    package_name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_version: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    new_version: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'normal'")
    is_downloaded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_installed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class OsInstallJob(Base):
    """A multi-node OS package installation job."""
    __tablename__ = "os_install_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_names: Mapped[list] = mapped_column(JSONB, nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    target_nodes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'rolling'")
    restart_policy: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'none'")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'pending'")
    started_by: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    steps: Mapped[list["OsInstallJobStep"]] = relationship(
        back_populates="job", order_by="OsInstallJobStep.step_order",
        cascade="all, delete-orphan",
    )


class OsInstallJobStep(Base):
    """A single step in an OS install job (install, reboot, or health_check)."""
    __tablename__ = "os_install_job_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("os_install_jobs.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    node_ip: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'pending'")
    is_test_node: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_log: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    job: Mapped["OsInstallJob"] = relationship(back_populates="steps")


class NodePackage(Base):
    """Installed OS packages per node (full inventory from dpkg-query)."""
    __tablename__ = "node_packages"
    __table_args__ = (
        UniqueConstraint("node_hostname", "package_name", name="uq_node_pkg"),
        Index("ix_node_packages_package_name", "package_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    package_name: Mapped[str] = mapped_column(String(200), nullable=False)
    installed_version: Mapped[str] = mapped_column(String(100), nullable=False)
    architecture: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'amd64'")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class OsInstallAudit(Base):
    """Permanent audit log of OS package installations."""
    __tablename__ = "os_install_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_hostname: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_role: Mapped[str] = mapped_column(String(50), nullable=False)
    package_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False, server_default="'install'")
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    installed_by: Mapped[str] = mapped_column(String(200), nullable=False, server_default="'system'")
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class AuditLoginEvent(Base):
    """Authentication audit log — login/logout/refresh/password events."""
    __tablename__ = "audit_login_events"
    __table_args__ = (
        Index("ix_audit_login_events_timestamp", "timestamp"),
        Index("ix_audit_login_events_user_ts", "user_id", "timestamp"),
        Index("ix_audit_login_events_type_ts", "event_type", "timestamp"),
        Index("ix_audit_login_events_ip_ts", "ip_address", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # user_id is nullable: failed logins can have unknown users
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False, server_default="''")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'cookie'")
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )


class AnalyticsDashboard(Base):
    """A user-created analytics dashboard with SQL-based widgets."""
    __tablename__ = "analytics_dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    variables: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    owner: Mapped["User | None"] = relationship()
    widgets: Mapped[list["AnalyticsWidget"]] = relationship(
        back_populates="dashboard", cascade="all, delete-orphan"
    )


class AnalyticsWidget(Base):
    """A single widget (chart / table / stat) on an analytics dashboard."""
    __tablename__ = "analytics_widgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics_dashboards.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    layout: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    dashboard: Mapped["AnalyticsDashboard"] = relationship(back_populates="widgets")


class Action(Base):
    """A reusable Python script that can execute on a collector or on central."""
    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'collector'")
    source_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    credential_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    credential: Mapped["Credential | None"] = relationship("Credential", foreign_keys=[credential_id])


class Automation(Base):
    """An orchestration that chains one or more actions, triggered by events or cron."""
    __tablename__ = "automations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # After phase cut-over step 2 (see docs/event-policy-rework.md), the
    # only supported trigger types are `"incident"` and `"cron"`. The
    # legacy `"event"` path is gone — existing rows were bulk-migrated
    # to `"incident"` in alembic revision zp6q7r8s9t0u.
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    incident_rule_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    incident_state_trigger: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cron_device_label_filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cron_device_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Unified device scope (works for both event and cron triggers)
    device_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    device_label_filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    steps: Mapped[list["AutomationStep"]] = relationship(
        "AutomationStep", back_populates="automation",
        cascade="all, delete-orphan", order_by="AutomationStep.step_order"
    )


class AutomationStep(Base):
    """A single step in an automation chain, linking to an action."""
    __tablename__ = "automation_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actions.id", ondelete="RESTRICT"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    credential_type_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timeout_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    automation: Mapped["Automation"] = relationship("Automation", back_populates="steps")
    action: Mapped["Action"] = relationship("Action")
