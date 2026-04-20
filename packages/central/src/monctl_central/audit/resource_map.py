"""Map SQLAlchemy __tablename__ values to audit resource types.

The audit SQLAlchemy event listener uses this mapping to decide which
table changes are worth auditing. Tables not listed here are skipped
(whitelist, not blacklist — we don't want to audit internal bookkeeping
tables like job queues or cache state).
"""

from __future__ import annotations

# tablename → resource_type label (used in the audit UI filters).
#
# KEEP IN SYNC with `tests/unit/test_audit_resource_map_coverage.py`
# (F-CEN-050): that test enumerates every SQLAlchemy model and fails
# if its table is neither listed here nor explicitly opted out of
# auditing. Add new mutating tables here; add genuinely-bookkeeping
# tables to the opt-out list with a short reason.
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
    "credential_types": "credential_type",
    "credential_values": "credential_value",
    "connectors": "connector",
    "connector_versions": "connector_version",
    # Users / access control
    "users": "user",
    "user_tenants": "user_tenant",
    "roles": "role",
    "role_permissions": "role_permission",
    "tenants": "tenant",
    # Alerting / incidents / automations
    "alert_definitions": "alert_definition",
    "threshold_variables": "threshold_variable",
    "threshold_overrides": "threshold_override",
    "incident_rules": "incident_rule",
    "actions": "action",
    "automations": "automation",
    "automation_steps": "automation_step",
    # Templates / packs / modules
    "templates": "template",
    "device_category_template_bindings": "template_binding",
    "device_type_template_bindings": "template_binding",
    "packs": "pack",
    "python_modules": "python_module",
    "snmp_oids": "snmp_oid",
    "label_keys": "label_key",
    # Collectors / infrastructure
    "collectors": "collector",
    "collector_groups": "collector_group",
    "collector_clusters": "collector_cluster",
    # Settings / security
    "system_settings": "system_setting",
    "data_retention_overrides": "data_retention_override",
    "tls_certificates": "tls_certificate",
    # Dashboards
    "analytics_dashboards": "analytics_dashboard",
    "analytics_widgets": "analytics_widget",
    # Upgrade jobs (central-initiated — remote execution, worth auditing)
    "upgrade_packages": "upgrade_package",
    "upgrade_jobs": "upgrade_job",
    "os_install_jobs": "os_install_job",
    "os_install_audit": "os_install_audit",
}


def resource_type_for(tablename: str) -> str | None:
    """Return the audit resource_type for a SQLAlchemy tablename, or None to skip."""
    return TABLE_TO_RESOURCE.get(tablename)
