# Documentation Findings — Review #2 (2026-04-30)

## Summary

22 findings: 2 HIGH / 8 MED / 8 LOW / 4 INFO

The major doc events since Review #1 (public README rewrite, gossip removal, Superset guide, eligibility doc, customer install docs) all landed cleanly. The biggest gaps are: (1) `app_create.md` lives at the repo root and is unlinked from any onboarding doc, so the "App Data Cache" content shipped in #151 is effectively orphaned; (2) CLAUDE.md's Package Structure section advertises pack filenames that no longer exist (`snmp-core-v1.0.0.json`) and undercounts shipped packs by 6; (3) several Known-pitfalls entries promoted in Review #1 are stale (PAT scope) or were never added even though new memory entries from 2026-04-22 onward record sharp-edge bugs (httpx cookies, alert_def expression removal, `monctlctl` naming, per-row LIMIT). Customer-facing INSTALL.md / TROUBLESHOOTING.md / UPGRADE.md are accurate. Superset guide is tight and matches the live OAuth + init.sh + readonly=2 code. CLAUDE.md still describes a 4-host central layout — fine for the dev/prod box but the public README correctly abstracts to "N nodes", so no contradiction. There is no central env-var reference document anywhere in the repo.

---

## Findings

### D-X-001 — `app_create.md` is orphaned at repo root
- **Severity**: HIGH
- **File**: `app_create.md` (referenced by no doc)
- **Description**: The MonCTL App Development Guide (607 lines, 24 KB) — the canonical doc on how to write a `BasePoller` and the only place the "App Data Cache" cross-app/delta patterns shipped in PR #151 live — sits at the repo root with zero inbound links. README.md, CLAUDE.md, INSTALL.md, and `docs/action-development-guide.md` all fail to mention it. A new pack author following README → docs/ → docs/superset.md will never find it.
- **Fix sketch**: Move `app_create.md` to `docs/app-development-guide.md` (matches the sibling `action-development-guide.md` naming) and link it from README.md "Repository layout" section and CLAUDE.md "App & Pack System" section.

### D-X-002 — No central env-var reference; new operator must grep code
- **Severity**: HIGH
- **File**: (no file — gap)
- **Description**: New env vars introduced since Review #1 are scattered: `MONCTL_PEER_TOKEN` (only in `docs/review/2026-04-19/TODO.md`), `MONCTL_NODE_NAME` and `MONCTL_PATRONI_NODES` / `MONCTL_ETCD_NODES` / `MONCTL_REDIS_SENTINEL_HOSTS` (only in CLAUDE.md), `MONCTL_INSECURE_TLS` (only in `tls-audit.md` and a code comment in `action-development-guide.md`), `MONCTL_TENANT_ID` and the Layer-3 ClickHouse settings (only in memory). `INSTALL.md` does not reference any of them.
- **Fix sketch**: Add `docs/env-reference.md` (or extend INSTALL.md with an "Environment variables" section) that lists every `MONCTL_*` settings.py field with: required/optional, default, example, where it's set (compose env / secrets.env / runtime).

### D-CLA-003 — CLAUDE.md package structure pack filenames are stale
- **Severity**: MED
- **File**: `CLAUDE.md:39-41`
- **Description**: CLAUDE.md says:
  ```
  packs/
  ├── snmp-core-v1.0.0.json      # snmp_check, snmp_interface_poller, snmp_discovery, snmp_uptime
  └── basic-checks-v1.0.0.json   # ping_check, port_check, http_check
  ```
  Actual files in `packs/`: `basic-checks.json`, `cisco-juniper-device-types.json`, `cisco-monitoring.json`, `docker-container-stats.json`, `entity-mib-inventory.json`, `juniper-monitoring.json`, `linux-server.json`, `snmp-core.json`. Filenames have no version suffix; 6 vendor packs are missing from the list (PR #146 bundled them).
- **Fix sketch**: Replace the explicit list with a one-line "8 vendor-grouped packs (snmp-core, basic-checks, cisco-monitoring, juniper-monitoring, linux-server, entity-mib-inventory, docker-container-stats, cisco-juniper-device-types) auto-imported on startup". Drop the version suffix.

### D-CLA-004 — CLAUDE.md "Known pitfalls" missing 6 entries from new memory
- **Severity**: MED
- **File**: `CLAUDE.md:322-348`
- **Description**: F-X-011 from Review #1 promoted evergreen memory entries to CLAUDE.md, but pitfalls discovered since 2026-04-22 are not represented:
  - `feedback_httpx_cookies_assignment` — silent no-op on httpx 0.28+
  - `feedback_alert_def_expression_removed` — `AlertDefinition.expression` removed in PR #38; use `severity_tiers` JSONB
  - `feedback_per_row_multiplier_hits_limit` — history endpoints with N rows/sample need server-side `toStartOfInterval` bucketing
  - `feedback_squash_merge_drops_dev_fixes` — squash-merge can silently drop dev-branch compose/config edits
  - `feedback_cli_naming` — no glued suffixes like `monctlctl`; prefer `monctl_ctl`
  - `feedback_check_for_existing_helpers_first` — grep for `_caller_*` / `_require_*` helpers before adding enforcement logic
- **Fix sketch**: Append six paragraphs in the same one-paragraph-per-pitfall style.

### D-CLA-005 — CLAUDE.md PAT-workflow-scope pitfall is now wrong
- **Severity**: MED
- **File**: `CLAUDE.md:348`
- **Description**: The pitfall states "Pushes that touch `.github/workflows/*.yml` are rejected... split the change if non-empty." Memory `feedback_pat_workflow_scope` was updated 2026-04-21 to "PAT HAS workflow scope as of 2026-04-21; don't preemptively split — just try the push." CLAUDE.md still has the stale advice and contradicts current memory.
- **Fix sketch**: Either delete the pitfall entirely, or rewrite to: "PAT now has `workflow` scope (since 2026-04-21). Don't preemptively split workflow edits into a separate commit — push first, only split if the push is actually rejected."

### D-CLA-006 — CLAUDE.md "deploy script (preferred)" misleads customer-facing readers
- **Severity**: MED
- **File**: `CLAUDE.md:240-251`
- **Description**: CLAUDE.md presents `./deploy.sh` as the preferred build/deploy path. That's correct for the dev-box workflow, but `monctl_ctl deploy` is now the canonical install path for end users. The doc is the public "onboarding doc that the AI agent reads" (per README:119) and a customer reading it will think `deploy.sh` is the supported path.
- **Fix sketch**: Add a one-line preface to "Building & Deploying": "`./deploy.sh` is the maintainer dev-cluster workflow against `10.145.210.41-44`/`.31-.34`. Customers and external operators should use `monctl_ctl deploy` — see INSTALL.md."

### D-CLA-007 — CLAUDE.md Tech Stack omits Python 3.12 collector + Redis Sentinel
- **Severity**: LOW
- **File**: `CLAUDE.md:18-28`
- **Description**: README lists "Cache: Redis with Sentinel" and "Collector: Python 3.12, gRPC (peer comms), SQLite (local buffer)". CLAUDE.md says only "Cache: Redis" and the SQLite note is in a different section.
- **Fix sketch**: Sync the two bullet lists. Add "(Sentinel HA)" to the Redis line in CLAUDE.md.

### D-INST-008 — INSTALL.md says monctl-installer is on PyPI but it isn't yet
- **Severity**: LOW
- **File**: `INSTALL.md:27-33`
- **Description**: Step 2 reads `pipx install monctl-installer` followed by a parenthetical "Until the package is published to PyPI, install from the GitHub release wheel". The first command will fail today.
- **Fix sketch**: Invert the order — put the GitHub-release-wheel command as the primary, and demote the PyPI command to a future-state note.

### D-INST-009 — `monctl_ctl --version` returns 0.1.0 against an INSTALL.md that talks about v1.0.0
- **Severity**: LOW
- **File**: `INSTALL.md:33,124`; `packages/installer/pyproject.toml:3`
- **Description**: INSTALL.md repeatedly references `v1.0.0`, but `pyproject.toml` declares `version = "0.1.0"`. Customer running `monctl_ctl --version` will see `0.1.0`.
- **Fix sketch**: Either bump installer pyproject to `1.0.0` or update INSTALL.md to use the current `0.1.0` everywhere.

### D-INST-010 — INSTALL.md "add-host" claims docker_stats supported; planner schema confirms but no test
- **Severity**: LOW
- **File**: `INSTALL.md:127`; `packages/installer/src/monctl_installer/inventory/schema.py:18`
- **Description**: INSTALL says `add-host` accepts only leaf roles `collector` and `docker_stats`. The schema lists both as valid roles, but the planner does not document or enforce "leaf-ness" anywhere, and there is no test.
- **Fix sketch**: Either drop the leaf claim from INSTALL or add a topology validation that rejects non-leaf roles in add-host with a test.

### D-CEN-011 — CLAUDE.md auth section silent on OAuth/Bearer/SSO surface
- **Severity**: LOW
- **File**: `CLAUDE.md:215-222`
- **Description**: Authentication section lists Web UI / Management API / Collector API / Dependencies but does not mention the OAuth2 provider at `/v1/oauth/*` (added in PR #152) used by Superset, nor the user `superset_access` tier orthogonal to `role`.
- **Fix sketch**: Add a fourth bullet: "**OAuth2 provider** (Superset SSO): `/v1/oauth/{authorize,token,userinfo}` with HS256-signed JWTs. Configured via `MONCTL_OAUTH_CLIENT_ID/SECRET/REDIRECT_URIS`. See `docs/superset.md`."

### D-CEN-012 — CLAUDE.md package structure missing eligibility, oauth provider, e2e tests
- **Severity**: LOW
- **File**: `CLAUDE.md:43-109`
- **Description**: Package Structure section enumerates ~25 sub-routers but omits: eligibility endpoints (live in `apps/router.py`), OAuth2 provider (`auth/oauth.py`), e2e harness at `docker-compose.test.yml`, and `installer/` (mentioned in README repo layout but not in CLAUDE.md package structure).
- **Fix sketch**: Add `installer/` to the top-level package list. Add a sub-bullet under `auth/` for `oauth.py`. Note that eligibility piggybacks on the apps router.

### D-COL-013 — collector-deployment-guide.md describes legacy `./deploy.sh` workflow
- **Severity**: MED
- **File**: `docs/collector-deployment-guide.md:152-180`
- **Description**: This guide is the only customer-facing doc on standing up a collector. It walks through `./deploy.sh collector` (maintainer-only workflow against worker1-4) and includes hardcoded prod IPs (`10.145.210.40` for central VIP, `worker1`/`worker2`). New customers using `monctl_ctl deploy` will be confused.
- **Fix sketch**: Either retire this doc and fold the surviving content (host prereqs, ports, NTP, SSH user) into INSTALL.md as a "Collector node prereqs" section, or rewrite §4 "Deployment" to use `monctl_ctl deploy` and remove the prod IPs.

### D-COL-014 — collector-deployment-guide.md `verify_ssl=false` example with no MONCTL_INSECURE_TLS reference
- **Severity**: LOW
- **File**: `docs/collector-deployment-guide.md:138-148`
- **Description**: `.env` example shows `VERIFY_SSL=false` as the recommended setting for self-signed certs. Per `tls-audit.md` and the F-X-010 closed finding, every `verify=False` should be gated behind `MONCTL_INSECURE_TLS=1` with a safe default.
- **Fix sketch**: Replace `VERIFY_SSL=false` with the env-var-gated form. Add a note: "set this only for development clusters with self-signed certs; production should use a real CA bundle."

### D-SUP-015 — superset.md operator runbook references `/bi/logout/` but doesn't note logout returns to MonCTL
- **Severity**: LOW
- **File**: `docs/superset.md:137`
- **Description**: "Tell them to sign out of Superset (`/bi/logout/`)" is correct on the path but doesn't tell the operator what they'll see.
- **Fix sketch**: Add a sentence: "After `/bi/logout/`, the user is redirected to MonCTL's `/login`. They re-authenticate to MonCTL, then click into the Superset tab to start a fresh session with the new tier."

### D-SUP-016 — superset.md "Where things live" missing the dev-only `/opt/superset` path explanation
- **Severity**: INFO
- **File**: `docs/superset.md:144-150`
- **Description**: §"Initial Superset deploy" mentions "for the dev cluster on `10.145.210.10`, the same compose lives at `/opt/superset/docker-compose.yml`". Customers reading this guide on a fresh cluster will wonder why their compose isn't there.
- **Fix sketch**: Make the "dev cluster" sentence parenthetical and tag it explicitly: "(maintainer note: the dev box at 10.145.210.10 also keeps a hand-managed copy at `/opt/superset/`; customer installs always go through `monctl_ctl deploy`)."

### D-X-017 — `docs/event-policy-rework.md` is a draft design doc, not labelled as superseded
- **Severity**: MED
- **File**: `docs/event-policy-rework.md:1-3`
- **Description**: Header says `Status: draft, not yet approved` and `Author: initial sketch by Claude on 2026-04-10`. Per memory `project_event_policy_rework`, the rework was completed (14 PRs, #20-#33) and the alerting model was rewritten again in PR #38 (severity_tiers). The doc still describes a parallel-track `IncidentRule`/`Incident` data model that was largely scrapped.
- **Fix sketch**: Either delete the file or add a banner at top: "**Historical design doc — superseded by PRs #20-#38 (event policy rework) and PR #38 (tiered severity model). Kept for context only. See `CLAUDE.md` Alerting section for current behaviour.**"

### D-X-018 — No pack JSON schema reference for pack authors
- **Severity**: MED
- **File**: (no file — gap)
- **Description**: 8 packs ship in `packs/`. CLAUDE.md describes packs in 2 sentences. `app_create.md` covers app authoring but not pack structure. A pack author has nothing to read except existing JSON files.
- **Fix sketch**: Add `docs/pack-format.md` with: top-level fields (`pack_uid`, `version`, `name`, `changelog`), apps array (with `vendor_oid_prefix`, `versions[]` including `eligibility_oids`, `source_code`), connectors array, device_types array, templates array. Worked example using `basic-checks.json`.

### D-X-019 — No connector / BasePoller lifecycle diagram
- **Severity**: MED
- **File**: (no file — gap)
- **Description**: CLAUDE.md "Connector System" describes the connector contract in prose, and `app_create.md` covers BasePoller subclassing, but there is no visual / call-graph showing the polling-engine lifecycle: `engine.py` instantiates `Poller`, calls `connector.connect()`, awaits `Poller.poll()`, captures `PollResult`, calls `connector.close()`, runs `gc.collect() + malloc_trim(0)`. A new app author has to read the engine source.
- **Fix sketch**: Add a "Lifecycle" section to `app_create.md` with a numbered list of the 6-7 steps the engine performs per job. Explicitly call out "your `poll()` should never call `connector.connect()`".

### D-CEN-020 — OpenAPI summary/description fields not consistently set on new endpoints
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/auth/oauth.py:193`; `apps/router.py:2628`
- **Description**: New OAuth and eligibility routers both have docstrings, but `@router.get("/oauth/authorize")` doesn't set explicit `summary=` or `tags=`. The audit / installer surfaces have similar issues.
- **Fix sketch**: Add `tags=["OAuth2"]` to `auth/oauth.py` router, `tags=["Eligibility"]` to the eligibility endpoints. Audit the rest of `/v1/*` for missing tags. Long-term: agree on a tag taxonomy and document it in CLAUDE.md API Conventions.

### D-X-021 — No disaster-recovery runbook (Patroni split-brain, ClickHouse replica wipe)
- **Severity**: MED
- **File**: (no file — gap)
- **Description**: Memory carries hard-won DR knowledge (`project_clickhouse_replica_wipe`, `project_redis_sentinel`, etc.) but the operator-facing docs don't have a "central1 lost", "Patroni split-brain", "ClickHouse replica wiped" runbook. TROUBLESHOOTING.md covers symptoms but stops short of recovery procedures. A 3 a.m. incident operator has nothing to follow.
- **Fix sketch**: Add `docs/disaster-recovery.md` with three runbooks: (1) central node lost, (2) Patroni split-brain (etcd reset procedure, `pg_basebackup` from leader), (3) CH replica wiped. Each runbook ends with a "verify" step (`monctl_ctl status`).

### D-CLA-022 — CLAUDE.md missing the alembic-rebase + sibling-PR-deploy workflow
- **Severity**: INFO
- **File**: `CLAUDE.md:346`
- **Description**: The Alembic migrations pitfall is present, but the related `feedback_deploy_requires_all_pending_fixes` memory ("Deploying from a branch cut off main silently rolls back any unmerged sibling PR — list pending PRs before ./deploy.sh") is not.
- **Fix sketch**: Add a sibling pitfall: "**Sibling-PR rollback** — Deploying from a branch cut off main silently rolls back any unmerged sibling PR's central source. Before `./deploy.sh central`, run `gh pr list --state open --label deployed` and confirm none of the open PRs are already running in prod. If they are, rebase your branch onto main first."
