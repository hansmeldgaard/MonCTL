"""Top-level API router that mounts all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from monctl_central.collectors.router import router as collectors_router
from monctl_central.collector_groups.router import router as collector_groups_router
from monctl_central.ingestion.router import router as ingestion_router
from monctl_central.apps.router import router as apps_router
from monctl_central.alerting.router import router as alerting_router
from monctl_central.results.router import router as results_router
from monctl_central.devices.router import router as devices_router
from monctl_central.device_types.router import router as device_types_router
from monctl_central.credentials.router import router as credentials_router
from monctl_central.tenants.router import router as tenants_router
from monctl_central.users.router import router as users_router
from monctl_central.auth.router import router as auth_router
from monctl_central.snmp_oids.router import router as snmp_oids_router
from monctl_central.registration_tokens.router import router as registration_tokens_router
from monctl_central.credential_keys.router import router as credential_keys_router
from monctl_central.label_keys.router import router as label_keys_router
from monctl_central.settings.router import router as settings_router
from monctl_central.tls.router import router as tls_router
from monctl_central.templates.router import router as templates_router
from monctl_central.credential_templates.router import router as credential_templates_router
from monctl_central.system.router import router as system_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(ingestion_router, tags=["ingestion"])
api_router.include_router(collectors_router, prefix="/collectors", tags=["collectors"])
api_router.include_router(collector_groups_router, prefix="/collector-groups", tags=["collector-groups"])
api_router.include_router(apps_router, prefix="/apps", tags=["apps"])
api_router.include_router(alerting_router, prefix="/alerts", tags=["alerting"])
api_router.include_router(results_router, prefix="/results", tags=["results"])
api_router.include_router(devices_router, prefix="/devices", tags=["devices"])
api_router.include_router(device_types_router, prefix="/device-types", tags=["device-types"])
api_router.include_router(credentials_router, prefix="/credentials", tags=["credentials"])
api_router.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(snmp_oids_router, prefix="/snmp-oids", tags=["snmp-oids"])
api_router.include_router(registration_tokens_router, prefix="/registration-tokens", tags=["registration-tokens"])
api_router.include_router(credential_keys_router, prefix="/credential-keys", tags=["credential-keys"])
api_router.include_router(label_keys_router, prefix="/label-keys", tags=["label-keys"])
api_router.include_router(credential_templates_router, prefix="/credential-templates", tags=["credentials"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(tls_router, prefix="/settings/tls", tags=["tls"])
api_router.include_router(templates_router, prefix="/templates", tags=["templates"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
