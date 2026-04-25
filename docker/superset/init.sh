#!/usr/bin/env bash
# One-shot Superset initialization:
#   - install clickhouse-connect driver
#   - run metadata DB migrations
#   - create admin user (idempotent)
#   - initialize default roles/permissions
#   - upsert the ClickHouse database connection
#
# Safe to re-run.

set -euo pipefail

echo "[superset-init] installing local requirements (psycopg2-binary, clickhouse-connect)..."
pip install --quiet --no-cache-dir -r /app/docker/requirements-local.txt

echo "[superset-init] running metadata DB migrations..."
superset db upgrade

echo "[superset-init] creating/updating admin user '${SUPERSET_ADMIN_USER}'..."
superset fab create-admin \
  --username "${SUPERSET_ADMIN_USER}" \
  --firstname Admin \
  --lastname User \
  --email "${SUPERSET_ADMIN_EMAIL}" \
  --password "${SUPERSET_ADMIN_PW}" || true

# Force-reset password so .env is authoritative on every run.
superset fab reset-password \
  --username "${SUPERSET_ADMIN_USER}" \
  --password "${SUPERSET_ADMIN_PW}" || true

echo "[superset-init] initializing default roles + permissions..."
superset init

echo "[superset-init] upserting ClickHouse database connection..."
# readonly=2 (NOT 1): blocks INSERT/ALTER/DROP at the protocol level (same as
# readonly=1 for that purpose), but unlike readonly=1 it ALLOWS per-query
# setting changes — required for the SQL_QUERY_MUTATOR's
# `SETTINGS monctl_tenant_scope='...'` clause that drives Layer 3 row
# policies. With readonly=1, CH rejects the setting with code 164 "Cannot
# modify 'monctl_tenant_scope' setting in readonly mode" and every chart
# fails (admins included).
export CH_URI="clickhousedb://${CLICKHOUSE_SUPERSET_USER}:${CLICKHOUSE_SUPERSET_PW}@${CLICKHOUSE_HOST_PRIMARY}:8123/${CLICKHOUSE_DB}?readonly=2"

python <<'PYEOF'
import os
from superset.app import create_app

NAME = "MonCTL ClickHouse"
URI = os.environ["CH_URI"]

app = create_app()
with app.app_context():
    # Import inside the context — models/helpers.py reads app.config at module load.
    from superset import db
    from superset.models.core import Database

    obj = db.session.query(Database).filter_by(database_name=NAME).first()
    if obj is None:
        obj = Database(database_name=NAME)
        db.session.add(obj)
        print(f"[superset-init] creating new DB entry: {NAME}")
    else:
        print(f"[superset-init] updating existing DB entry: {NAME}")
    obj.set_sqlalchemy_uri(URI)
    obj.expose_in_sqllab = True
    obj.allow_ctas = False
    obj.allow_cvas = False
    obj.allow_dml = False
    obj.allow_run_async = False
    obj.allow_file_upload = False
    obj.cache_timeout = 300
    db.session.commit()
    print(f"[superset-init] saved '{NAME}'")

    # -- Seed a custom role "MonCTLViewer" -------------------------------------
    # Gamma can't see datasets unless explicitly granted. Our tenant-scoped
    # users need read on every MonCTL CH dataset (filtered by RLS) but NOT
    # SQL Lab (which bypasses RLS entirely). Start from Gamma, add the
    # dataset-access permission, omit sql_lab.
    from flask_appbuilder.security.sqla.models import Role, PermissionView

    VIEWER = "MonCTLViewer"
    viewer = db.session.query(Role).filter_by(name=VIEWER).one_or_none()
    gamma = db.session.query(Role).filter_by(name="Gamma").one_or_none()
    if viewer is None:
        viewer = Role(name=VIEWER)
        db.session.add(viewer)
        db.session.flush()
        print(f"[superset-init] created role '{VIEWER}'")
    # Start from Gamma's perm list (idempotent: replace wholesale each run).
    viewer_perms = list(gamma.permissions) if gamma else []
    # Add the grant that lets this role read any SqlaTable datasource.
    ds_all = (
        db.session.query(PermissionView)
        .join(PermissionView.permission)
        .join(PermissionView.view_menu)
        .filter(
            PermissionView.permission.has(name="all_datasource_access"),
            PermissionView.view_menu.has(name="all_datasource_access"),
        )
        .first()
    )
    if ds_all and ds_all not in viewer_perms:
        viewer_perms.append(ds_all)
    # Strip any sql_lab-ish perms that Gamma happens to include.
    viewer_perms = [
        p for p in viewer_perms
        if not (p.permission and "sql" in (p.permission.name or "").lower())
    ]
    viewer.permissions = viewer_perms
    db.session.commit()
    print(
        f"[superset-init] '{VIEWER}' has {len(viewer_perms)} permissions "
        "(Gamma + all_datasource_access - sql)"
    )

    # -- Tenant RLS: seed filter + attach to every existing MonCTL CH dataset --
    # The app-level SqlaTable.after_insert listener handles NEW datasets; this
    # loop catches datasets created before RLS was wired up (idempotent).
    from superset.connectors.sqla.models import (
        RLSFilterTables,
        RowLevelSecurityFilter,
        SqlaTable,
    )
    from superset.utils.core import RowLevelSecurityFilterType

    RLS_NAME = "monctl_tenant_scope"
    rls = (
        db.session.query(RowLevelSecurityFilter)
        .filter_by(name=RLS_NAME)
        .one_or_none()
    )
    if rls is None:
        rls = RowLevelSecurityFilter(
            name=RLS_NAME,
            description=(
                "Auto-generated: filters every MonCTL ClickHouse dataset by "
                "the current user's tenant_ids. all_tenants=true (admins) "
                "pass through (1=1)."
            ),
            filter_type=RowLevelSecurityFilterType.BASE.value,
            clause="{{ monctl_tenant_clause() }}",
        )
        db.session.add(rls)
        db.session.flush()
        print(f"[superset-init] created RLS filter '{RLS_NAME}'")

    # Attach to every existing SqlaTable on the MonCTL CH database.
    datasets = db.session.query(SqlaTable).filter_by(database_id=obj.id).all()
    for ds in datasets:
        already = db.session.execute(
            RLSFilterTables.select()
            .where(RLSFilterTables.c.rls_filter_id == rls.id)
            .where(RLSFilterTables.c.table_id == ds.id)
        ).first()
        if not already:
            db.session.execute(
                RLSFilterTables.insert().values(
                    rls_filter_id=rls.id, table_id=ds.id
                )
            )
            print(f"[superset-init]   attached RLS to dataset id={ds.id} name={ds.table_name!r}")
    db.session.commit()
    print(f"[superset-init] RLS scan complete ({len(datasets)} datasets checked)")
PYEOF

echo "[superset-init] done."
