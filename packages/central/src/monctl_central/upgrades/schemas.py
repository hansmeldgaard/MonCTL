"""Pydantic schemas for upgrade management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StartUpgradeRequest(BaseModel):
    upgrade_package_id: str = Field(min_length=1)
    scope: str = Field(pattern="^(central|collectors|all)$")
    strategy: str = Field(default="rolling", pattern="^(rolling|all_at_once)$")


class DownloadOsUpdatesRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=2000)


class DownloadOsPackagesRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=2000)


class InstallOsOnNodeRequest(BaseModel):
    node_hostname: str = Field(min_length=1, max_length=200)
    package_names: list[str] = Field(min_length=1, max_length=2000)


class StartOsInstallJobRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=2000)
    scope: str = Field(pattern="^(central|collectors|all|nodes)$")
    target_nodes: list[str] | None = None
    strategy: str = Field(default="rolling", pattern="^(rolling|test_first)$")
    restart_policy: str = Field(default="none", pattern="^(none|rolling)$")


class CollectorUpgradeReport(BaseModel):
    collector_id: str = Field(default="")
    upgrade_type: str = Field(default="monctl")
    target_version: str = Field(default="")
    status: str = Field(pattern="^(completed|failed)$")
    output_log: str | None = None
    error_message: str | None = None
