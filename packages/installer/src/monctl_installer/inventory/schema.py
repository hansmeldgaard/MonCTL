"""Pydantic schema for inventory.yaml.

One declarative document describes the entire MonCTL cluster: hosts, role
assignments per host, and global sizing knobs. The planner in planner.py
turns this into a fully-resolved deployment plan.
"""
from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal[
    "postgres",
    "etcd",
    "redis",
    "clickhouse",
    "clickhouse_keeper",
    "central",
    "haproxy",
    "collector",
    "docker_stats",
    "superset",
]

ALL_ROLES: tuple[Role, ...] = (
    "postgres",
    "etcd",
    "redis",
    "clickhouse",
    "clickhouse_keeper",
    "central",
    "haproxy",
    "collector",
    "docker_stats",
    "superset",
)


class TLSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self-signed", "provided"] = "self-signed"
    cert_path: Path | None = None
    san_ips: list[str] = Field(default_factory=list)
    # Whether collectors verify central's TLS cert. Self-signed (the
    # bootstrap default) leaves this off so first contact succeeds; once
    # the operator distributes their own CA bundle they should flip this
    # to true. (S-INST-003)
    verify: bool | None = None

    @model_validator(mode="after")
    def _require_cert_when_provided(self) -> TLSConfig:
        if self.mode == "provided" and self.cert_path is None:
            raise ValueError("tls.cert_path required when tls.mode=provided")
        return self

    @property
    def effective_verify(self) -> bool:
        """Resolve ``verify`` against the cert mode.

        Default: ``False`` for self-signed, ``True`` for provided. Operators
        can override either way via the explicit ``verify`` field.
        """
        if self.verify is not None:
            return self.verify
        return self.mode == "provided"


class ClusterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    domain: str | None = None
    vip: str | None = None
    vip_interface: str | None = None
    tls: TLSConfig = Field(default_factory=TLSConfig)

    @field_validator("vip")
    @classmethod
    def _valid_ip(cls, v: str | None) -> str | None:
        if v is not None:
            ip_address(v)
        return v


class SSHConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = "monctl"
    port: int = 22
    key: Path | None = None


class Host(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    ssh: SSHConfig = Field(default_factory=SSHConfig)
    roles: list[Role] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("address")
    @classmethod
    def _valid_ip(cls, v: str) -> str:
        ip_address(v)
        return v

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"host name must be alphanumeric (+ - _): {v!r}")
        return v

    def has_role(self, role: Role) -> bool:
        return role in self.roles


class PostgresSizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "standalone", "ha"] = "auto"


class ClickHouseSizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shards: int = Field(default=1, ge=1, le=24)
    replicas: int = Field(default=1, ge=1, le=3)
    keeper: Literal["embedded", "dedicated"] = "embedded"


class RedisSizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "single", "sentinel"] = "auto"


class CentralSizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tls_behind_haproxy: bool = True


class Sizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    postgres: PostgresSizing = Field(default_factory=PostgresSizing)
    clickhouse: ClickHouseSizing = Field(default_factory=ClickHouseSizing)
    redis: RedisSizing = Field(default_factory=RedisSizing)
    central: CentralSizing = Field(default_factory=CentralSizing)


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto_generate", "provided"] = "auto_generate"
    file: Path = Path("./secrets.env")


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    cluster: ClusterConfig
    hosts: list[Host]
    sizing: Sizing = Field(default_factory=Sizing)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    @field_validator("version")
    @classmethod
    def _supported_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unsupported inventory version: {v} (supported: 1)")
        return v

    @model_validator(mode="after")
    def _non_empty_hosts(self) -> Inventory:
        if not self.hosts:
            raise ValueError("at least one host required")
        if len({h.name for h in self.hosts}) != len(self.hosts):
            raise ValueError("host names must be unique")
        if len({h.address for h in self.hosts}) != len(self.hosts):
            raise ValueError("host addresses must be unique")
        # Superset is single-host only — HA Superset is out of scope.
        # See docs/superset.md ("Initial Superset deploy" → single host).
        if len(self.hosts_with("superset")) > 1:
            raise ValueError("at most one host may carry the 'superset' role")
        return self

    def hosts_with(self, role: Role) -> list[Host]:
        return [h for h in self.hosts if h.has_role(role)]
