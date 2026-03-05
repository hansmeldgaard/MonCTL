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
