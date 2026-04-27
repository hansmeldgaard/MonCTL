# Eligibility OID Testing & Smart App Assignment

MonCTL needs to put the right monitoring apps on each device automatically — manually picking apps for hundreds of devices doesn't scale. The Eligibility subsystem solves this by combining three pieces of metadata: a **vendor sysObjectID prefix** on each app, an optional list of **eligibility OIDs** to probe over SNMP, and an **auto-assign pack list** on each device type. After SNMP discovery classifies a device, central evaluates these rules to decide which apps belong on the device — no operator action required.

This doc covers the data model, the two execution modes (instant vs probe), how the nightly scan keeps things in sync, and how to operate the feature day-to-day.

---

## The three knobs

### 1. `App.vendor_oid_prefix` — coarse vendor filter

Set on each app, e.g. `1.3.6.1.4.1.9` (Cisco), `1.3.6.1.4.1.2636` (Juniper). When an app has a vendor prefix, only devices whose discovered `sys_object_id` starts with that prefix can become eligible. This is the cheap, **instant** filter that runs entirely in PostgreSQL.

### 2. `AppVersion.eligibility_oids` — fine-grained capability check

Optional list of OID checks attached to the latest version of an app. Each entry has the shape:

```json
{ "oid": "1.3.6.1.4.1.9.9.13.1.1.0", "check": "exists" }
{ "oid": "1.3.6.1.4.1.9.9.13.1.3.1.0", "check": "equals", "value": "ok" }
```

Two `check` modes:

| `check`  | Eligible when                                                                 |
| -------- | ----------------------------------------------------------------------------- |
| `exists` | The OID returns a non-null value (i.e. not `noSuchObject` / `noSuchInstance`) |
| `equals` | The returned value equals `value`                                             |

A device must pass **all** OIDs in the list to be marked eligible. If `eligibility_oids` is empty, the vendor prefix is the only check (instant mode).

### 3. `DeviceType.auto_assign_packs` — what to install when a type is matched

A list of `pack_uid` strings on each `DeviceType` (configured in **Device Types**). When discovery matches a device to a device type that has `auto_assign_packs`, central walks the apps in those packs and:

- Skips apps the device is already assigned to.
- For apps with `vendor_oid_prefix` only — instant assign.
- For apps with `eligibility_oids` — defers a Phase-2 SNMP probe before deciding.

If any app needs Phase-2 probing, central sets a Redis flag and the collector re-runs `snmp_discovery` with the OID list injected as `_eligibility_oids` job parameters; results come back as `_eligibility_results` in the discovery payload and are evaluated in `process_discovery_result`.

---

## Two execution modes

Both are exposed under each app's **Eligibility** tab.

### Instant mode (`Find Eligible`)

`POST /v1/apps/{app_id}/test-eligibility` with `mode=instant` (default). Filters `Device.metadata_->>'sys_object_id'` against `App.vendor_oid_prefix` and writes a completed `eligibility_runs` row with one `eligibility_results` row per device. Runs in milliseconds — vendor prefix is a string match in PG.

Use when: you just want a list of devices the app _could_ run on without poking them over the network.

### Probe mode (`Probe OIDs`)

`POST /v1/apps/{app_id}/test-eligibility` with `mode=probe`. For each candidate device, central:

1. Sets Redis keys for the eligibility OIDs (`set_eligibility_oids_for_device`) and the run association (`set_eligibility_run_for_device`).
2. Sets the device's discovery flag with TTL=600 s (`set_discovery_flag`).
3. Returns immediately with `run_id`, `flagged`, status `running`.

The collector picks up the discovery flag on its next poll, runs `snmp_discovery` with the OID list, and returns results. `process_discovery_result` step 8 evaluates `_eligibility_results` against `eligibility_oids` and writes the per-device result. The scheduler's `_finalize_eligibility_runs` task closes the run when all devices have reported (or after a 10-minute timeout) — see `packages/central/src/monctl_central/scheduler/tasks.py:1705`.

Use when: vendor prefix matches but the device might lack the specific MIB / table the app needs. Cisco IOS, IOS-XE, IOS-XR, NX-OS and small-business switches all share the `1.3.6.1.4.1.9` prefix but differ wildly in MIB support — eligibility OIDs catch that.

### Bulk auto-assign

After a run completes, the per-device results table has checkboxes plus an **Auto-Assign Selected** button. Hits `POST /v1/apps/{app_id}/auto-assign-eligible?run_id=…` with optional `device_ids` body filter. Creates `AppAssignment` rows pointing at the latest version, `enabled=true`, 60 s interval. Skips devices already assigned.

---

## Pack export/import

All three knobs round-trip through pack JSON, so a vendor pack ships with eligibility built-in:

- `App.vendor_oid_prefix` → top-level field on the app entry (`packs/service.py:218`)
- `AppVersion.eligibility_oids` → on the version entry (`packs/service.py:229`)
- `DeviceType.auto_assign_packs` → on the device-type entry (`packs/service.py:332`)

When a pack is updated, existing apps/versions/device-types keep their values unless the import payload sets them explicitly. The "skip" resolution mode never overwrites operator-edited eligibility config.

---

## Nightly scan

Central runs `_run_eligibility_scan` once per day (configurable via the `eligibility_scan_time` SystemSetting, default `02:00` UTC — manage it under **Settings → Automations**). For each enabled device with a matched device type that has `auto_assign_packs`, the scan checks if any candidate app is unassigned. If so, it sets the discovery flag with a 1-hour TTL and clears any stale Phase-2 flag — the next discovery cycle handles the actual assignment.

This catches:

- New devices added after their device type was already configured.
- New apps published into a pack that's already in `auto_assign_packs`.
- Devices that previously failed an eligibility probe and may now pass (firmware upgrade, license change).

---

## Operator runbook

### Configure eligibility for a new app

1. **Apps → pick the app → Versions tab → edit the latest version.**
2. Set `vendor_oid_prefix` if the app is vendor-specific (most SNMP apps are).
3. Add `eligibility_oids` for any MIB-specific capability checks. Use scalar OIDs (ending in `.0`) where possible — table OIDs require a row index that probes can't supply.
4. Save. The app's row in **Apps** now shows the vendor chip and "N OIDs" badge in the Eligibility column.

### Wire a device type to auto-assign packs

1. **Device Types → edit the device type → Auto-assign Packs.**
2. Pick one or more packs. The list comes from `usePacks()` and shows the pack name + UID.
3. Save. Discovery for any device matching this type's `sys_object_id_pattern` will now auto-evaluate the listed packs.

### Test before rollout

1. **Apps → app detail → Eligibility tab.**
2. **Find Eligible** — confirms the vendor filter catches the right devices.
3. **Probe OIDs** — confirms the OID checks classify each device correctly. Wait ~60-120 s.
4. Spot-check the per-device row (eligible / ineligible / error + `oid_results` JSON).
5. **Auto-Assign Selected** for the candidates you want to start polling.

### Tune the scan time

**Settings → Automations → Nightly Eligibility Scan**. HH:MM in 24-hour UTC. Pick something during low collector load — same window you'd use for any cron-like workload.

---

## Troubleshooting

### A run is stuck in `running`

`_finalize_eligibility_runs` finalises any run older than 10 minutes regardless of report count (`tasks.py:1731-1733`). If a run has been `running` for more than 12 minutes, check:

- Is the central scheduler healthy? (`/system-health` → scheduler subsystem)
- Did `_finalize_eligibility_runs` raise? Search central logs for `finalize_eligibility_runs_error`.

### Device shows `eligible=2` (error)

Means `snmp_discovery` returned an `_eligibility_error` for that device. Most common causes:

- Credentials missing for SNMP on the device's collector group.
- SNMP timeout — device unreachable or behind a firewall.
- Pack containing `snmp_discovery` not synced to the collector yet.

The `reason` column on the run row carries the truncated error string.

### Probe never starts

Verify `snmp_discovery` is the **latest** version published in the DB (apps run from the DB version, not from `apps/*.py` on disk). Bump via **Apps → snmp_discovery → Versions** if needed. The version must include the eligibility-probing branch added in v1.2.0.

### Auto-assign skipped a device

The endpoint skips devices that:

- Already have an assignment for this app.
- Have no `collector_group_id` (orphan devices).

Both cases increment `skipped` in the response. The frontend shows this in the Auto-Assign toast.

---

## Storage layout

| Table                                   | Where      | Notes                                                                                                                                     |
| --------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `apps.vendor_oid_prefix`                | PostgreSQL | `String(128)`, nullable.                                                                                                                  |
| `app_versions.eligibility_oids`         | PostgreSQL | JSONB list of `{oid, check, value?}`.                                                                                                     |
| `device_types.auto_assign_packs`        | PostgreSQL | JSONB list of `pack_uid` strings.                                                                                                         |
| `eligibility_runs`                      | ClickHouse | `ReplacingMergeTree` on `(run_id)`. Read with `FINAL`. 90-day TTL on `started_at`.                                                        |
| `eligibility_results`                   | ClickHouse | `MergeTree`. Per-device probe results. 90-day TTL. Forwarder may insert duplicates — query with `argMax(col, probed_at)` per `device_id`. |
| `system_settings.eligibility_scan_time` | PostgreSQL | HH:MM UTC.                                                                                                                                |

Useful diagnostic queries:

```sql
-- Recent runs
SELECT run_id, app_name, status, total_devices, eligible, ineligible, unreachable, started_at
  FROM eligibility_runs FINAL
 ORDER BY started_at DESC LIMIT 20;

-- Per-device latest result for a run (dedupe across centrals)
SELECT device_id, device_name, argMax(eligible, probed_at) AS eligible,
       argMax(reason, probed_at) AS reason
  FROM eligibility_results
 WHERE run_id = '<uuid>'
 GROUP BY device_id, device_name;
```
