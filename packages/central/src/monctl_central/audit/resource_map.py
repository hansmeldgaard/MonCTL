"""Map SQLAlchemy __tablename__ values to audit resource types.

The audit SQLAlchemy event listener uses this mapping to decide which
table changes are worth auditing. Tables not listed here are skipped
(whitelist, not blacklist — we don't want to audit internal bookkeeping
tables like job queues or cache state).
"""

from __future__ import annotations

# tablename → resource_type label (used in the audit UI filters)
TABLE_TO_RESOURCE: dict[str, str] = {
    # Core assets
    "devices": "device",
    "device_categories": "device_category",
    "device_types": "device_type",
    "apps": "app",
    "app_versions": "app_version",
    "app_assignments": "assignment",
    "credentials": "credential",
    "credential_keys": "credential_key",
    "credential_templates": "credential_template",
    "connectors": "connector",
    "connector_versions": "connector_version",
    # Users / access control
    "users": "user",
    "user_tenants": "user_tenant",
    "roles": "role",
    "role_permissions": "role_permission",
    "tenants": "tenant",
    # Alerting / events / automations
    "alert_definitions": "alert_definition",
    "threshold_variables": "threshold_variable",
    "threshold_overrides": "threshold_override",
    "event_policies": "event_policy",
    "actions": "action",
    "automations": "automation",
    "automation_steps": "automation_step",
    # Templates / packs / modules
    "monitoring_templates": "template",
    "template_bindings": "template_binding",
    "packs": "pack",
    "python_modules": "python_module",
    # Collectors / infrastructure
    "collectors": "collector",
    "collector_groups": "collector_group",
    "collector_clusters": "collector_cluster",
    "docker_hosts": "docker_host",
    # Settings
    "system_settings": "system_setting",
    "data_retention_overrides": "data_retention_override",
    # Dashboards
    "analytics_dashboards": "analytics_dashboard",
    "analytics_widgets": "analytics_widget",
    # Discovery
    "discovery_rules": "discovery_rule",
    # Upgrade jobs (central-initiated)
    "upgrade_packages": "upgrade_package",
    "upgrade_jobs": "upgrade_job",
}


def resource_type_for(tablename: str) -> str | None:
    """Return the audit resource_type for a SQLAlchemy tablename, or None to skip."""
    return TABLE_TO_RESOURCE.get(tablename)
