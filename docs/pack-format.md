# Pack Format Reference

A monitoring pack is a single JSON file that bundles apps, connectors,
device templates, and supporting catalogues into one importable unit.
This is the file format for those JSON files — one document per pack,
self-contained, importable by central without external dependencies.

This is the reference for **pack authors**. App authors should start with
[`app-development-guide.md`](app-development-guide.md) and only come
here when they need to ship the app inside a pack.

## At a glance

```json
{
  "monctl_pack": "1.0",
  "pack_uid": "my-pack",
  "name": "My Pack",
  "version": "1.0.0",
  "description": "...",
  "author": "...",
  "changelog": "v1.0.0 — initial release",
  "exported_at": null,
  "contents": {
    "apps": [...],
    "connectors": [...],
    "credential_templates": [...],
    "snmp_oids": [...],
    "device_templates": [...],
    "device_categories": [...],
    "device_types": [...],
    "label_keys": [...]
  }
}
```

A pack's filename has no version suffix — the JSON's own `version` field
is the source of truth (`packs/snmp-core.json`, not `snmp-core-3.0.0.json`).
Built-in packs live under `packs/` and central auto-imports them on every
startup; uploaded packs go through `POST /v1/packs/import`.

## Top-level fields

| Field         | Type             | Required | Notes                                                                                                                                |
| ------------- | ---------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `monctl_pack` | string           | yes      | Schema version — currently always `"1.0"`. Bumped only on incompatible format changes.                                               |
| `pack_uid`    | string           | yes      | Stable identifier across versions (e.g. `"snmp-core"`). The unique key central matches on; never change for an existing pack.        |
| `name`        | string           | yes      | Human-readable display name. Shown in the UI and logs.                                                                               |
| `version`     | semver           | yes      | This pack's version. **Must be ≥ the highest `version` of any nested app or connector** — `scripts/validate_packs.py` enforces this. |
| `description` | string           | yes      | One- or two-sentence summary.                                                                                                        |
| `author`      | string           | yes      | Free-form attribution.                                                                                                               |
| `changelog`   | string           | yes      | What changed in this version. Surfaces in the import UI; first-line summary used in audit log.                                       |
| `exported_at` | ISO 8601 \| null | yes      | Timestamp from `export_pack` — leave `null` for hand-authored packs.                                                                 |
| `contents`    | object           | yes      | The actual payload — see below. Empty `contents: {}` is valid (rare, but lets a pack ship just metadata).                            |

### Contents sections

Every section under `contents` is **optional and additive** — a pack can
ship any subset. The 8 valid keys map to specific central tables. The
import order is fixed (see "Skip resolution and import order" below);
unknown keys are ignored with a warning.

| Section                | Imports as                                                                 | Identity field | Purpose                                                                                      |
| ---------------------- | -------------------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------- |
| `apps`                 | `App` + `AppVersion` (+ nested `threshold_variables`, `alert_definitions`) | `name`         | The poller code shipped to collectors.                                                       |
| `connectors`           | `Connector` + `ConnectorVersion`                                           | `name`         | Reusable transport modules (SNMP, SSH, etc.) bound to apps via aliases.                      |
| `credential_templates` | `CredentialTemplate`                                                       | `name`         | Schemas for credential field shapes (e.g. SNMPv3 username/auth/priv).                        |
| `snmp_oids`            | `SnmpOid`                                                                  | `name`         | The OID catalogue the eligibility-probe / discovery UI reads.                                |
| `device_templates`     | `Template`                                                                 | `name`         | Per-app config defaults applied through the device-category / device-type binding hierarchy. |
| `device_categories`    | `DeviceCategory`                                                           | `name`         | Broad device groupings (`network`, `host`, `firewall`, …).                                   |
| `device_types`         | `DeviceType`                                                               | `name`         | Specific models with `sys_object_id_pattern` for SNMP discovery.                             |
| `label_keys`           | `LabelKey`                                                                 | `key`          | Predefined label keys + values for tagging (`env`, `site`, `role`, …).                       |

The full mapping is `ENTITY_MAP` in
`packages/central/src/monctl_central/packs/service.py:38-47`.

## Section reference

### `apps`

```json
{
  "name": "snmp_check",
  "description": "Built-in SNMP check (v1/v2c/v3)",
  "app_type": "builtin",
  "target_table": "availability_latency",
  "vendor_oid_prefix": null,
  "config_schema": {
    "type": "object",
    "properties": {
      "oid": {
        "type": "string",
        "title": "OID",
        "default": "1.3.6.1.2.1.1.3.0"
      }
    }
  },
  "connector_bindings": [
    { "connector_name": "snmp", "connector_type": "snmp" }
  ],
  "versions": [
    {
      "version": "2.1.1",
      "source_code": "...full Python source...",
      "requirements": [],
      "entry_class": "Poller",
      "is_latest": true,
      "display_template": null,
      "eligibility_oids": [],
      "volatile_keys": []
    }
  ],
  "threshold_variables": [
    {
      "name": "snmp_rtt_warn_ms",
      "default_value": 100.0,
      "display_name": "SNMP RTT Warning",
      "unit": "ms",
      "description": "..."
    }
  ],
  "alert_definitions": [
    {
      "name": "SNMP Latency",
      "severity_tiers": [
        {
          "severity": "healthy",
          "expression": "rtt_ms < snmp_rtt_warn_ms",
          "fire_count": 1
        },
        {
          "severity": "warning",
          "expression": "rtt_ms > snmp_rtt_warn_ms",
          "fire_count": 1
        },
        {
          "severity": "critical",
          "expression": "rtt_ms > snmp_rtt_crit_ms",
          "fire_count": 1
        }
      ],
      "window": "5m",
      "enabled": true,
      "description": "..."
    }
  ]
}
```

| Field                 | Type           | Required | Notes                                                                                                                                                                                                                                                                                                                                         |
| --------------------- | -------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                | string         | yes      | Unique within a central. Snake_case by convention.                                                                                                                                                                                                                                                                                            |
| `description`         | string         | yes      | One-sentence summary.                                                                                                                                                                                                                                                                                                                         |
| `app_type`            | string         | yes      | `"builtin"`, `"script"` (for python source apps) — informational.                                                                                                                                                                                                                                                                             |
| `target_table`        | string         | yes      | Where results land in ClickHouse: `availability_latency`, `performance`, `interface`, `config`. Drives downstream queries — must match what your `PollResult` actually emits.                                                                                                                                                                 |
| `vendor_oid_prefix`   | string \| null | no       | Triggers vendor-prefix eligibility (eligible only on devices whose `sysObjectID` starts with this). `null` = applies to any device.                                                                                                                                                                                                           |
| `config_schema`       | object \| null | no       | JSON Schema used by the Add-Assignment dialog. `boolean` and `enum` types render as checkbox / select; numeric ranges drive validation.                                                                                                                                                                                                       |
| `connector_bindings`  | array          | no       | Slots the assignment must fill — one entry per `connector_type` the poller calls into via `context.connectors[type]`. The engine pre-creates the slot at app upload; operators pick a concrete connector per slot at assignment time.                                                                                                         |
| `versions`            | array          | yes      | One or more `AppVersion` rows (see below). At least one entry must have `is_latest: true`.                                                                                                                                                                                                                                                    |
| `threshold_variables` | array          | no       | Tunable threshold values referenced by name from `alert_definitions[].severity_tiers[].expression`. `default_value` seeds the DB row; per-device / per-entity overrides ride on top.                                                                                                                                                          |
| `alert_definitions`   | array          | no       | Tiered alert defs (PR #38 model). Engine evaluates every tier per cycle and picks the highest matching severity. The optional `healthy` tier acts as a positive-clear signal — see CLAUDE.md "Alerting & Thresholds". `threshold_defaults` is auto-derived on export from referenced threshold variables; you don't need to write it by hand. |

#### `apps[].versions[]`

| Field              | Type           | Required | Notes                                                                                                                                                                      |
| ------------------ | -------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version`          | semver         | yes      | The app version. Pack `version` must be ≥ the max of these.                                                                                                                |
| `source_code`      | string         | yes      | Full Python source — including imports — that compiles to a `BasePoller` subclass. The pack validator `compile()`s this, so a syntax error fails the build.                |
| `requirements`     | array          | yes      | PyPI requirements for the app's venv. Plain pip-style strings (`["pysnmp>=7.0"]`). Empty `[]` is valid.                                                                    |
| `entry_class`      | string         | yes      | Class name in `source_code` to instantiate — almost always `"Poller"`.                                                                                                     |
| `is_latest`        | bool           | yes      | Exactly one version per app should have this `true`. The collector pulls the latest by default; assignments can pin to a specific version.                                 |
| `display_template` | object \| null | no       | UI rendering hints for assignment detail pages.                                                                                                                            |
| `eligibility_oids` | array          | yes      | OIDs the discovery probe checks before declaring this app eligible on a device. Empty `[]` = no probe (eligibility comes from `vendor_oid_prefix` or device-type binding). |
| `volatile_keys`    | array          | yes      | `config_data` keys the result-ingest pipeline should treat as volatile (won't trigger config-history change events).                                                       |

### `connectors`

```json
{
  "name": "snmp",
  "description": "SNMP transport (v1/v2c/v3) using pysnmp",
  "connector_type": "snmp",
  "requirements": [],
  "versions": [
    {
      "version": "1.4.4",
      "source_code": "...",
      "requirements": ["pysnmp>=7.0"],
      "entry_class": "SNMPConnector",
      "is_latest": true
    }
  ]
}
```

Same shape as `apps[].versions[]` minus the app-only fields. `connector_type`
is the alias key apps look up via `context.connectors[connector_type]`.

> **Connector rewrites — preserve every credential-key name.**
> Built-in connectors are read by every pack. Before bumping a connector
> version, enumerate every prod credential template's `fields[].name`
> and keep `get(canonical) or get(legacy, default)` fallbacks for all
> of them. See the matching pitfall in CLAUDE.md.

### `credential_templates`

```json
{
  "name": "snmpv3-auth-priv",
  "description": "SNMPv3 with authentication + privacy",
  "fields": [
    { "name": "username", "type": "string", "required": true },
    {
      "name": "auth_proto",
      "type": "enum",
      "values": ["MD5", "SHA1", "SHA256", "SHA384", "SHA512"]
    },
    { "name": "auth_pass", "type": "secret", "required": true },
    {
      "name": "priv_proto",
      "type": "enum",
      "values": ["DES", "AES128", "AES192", "AES256"]
    },
    { "name": "priv_pass", "type": "secret", "required": true }
  ]
}
```

`fields` is a free-form list of field descriptors the credential UI
renders. The connector reads them at poll time via
`credential.get(field_name)`.

### `snmp_oids`

```json
{
  "name": "ifTable.ifInOctets",
  "oid": "1.3.6.1.2.1.2.2.1.10",
  "description": "Octets received on the interface (32-bit counter)"
}
```

The catalogue the eligibility-probe / OID-explorer / app-author UIs read.
Adding an OID here doesn't poll anything — it's just metadata.

### `device_templates`

```json
{
  "name": "linux-server-defaults",
  "description": "Standard Linux server polling preset",
  "config": {
    "linux_cpu": { "interval": 60 },
    "linux_disk": { "interval": 300, "exclude_mounts": ["/boot", "/snap"] }
  }
}
```

Templates ship per-app config defaults that get applied through the
device-category / device-type binding hierarchy (`templates/resolver.py`,
two-level merge: category → type overlays).

### `device_categories`

```json
{
  "name": "network",
  "description": "Network device — router/switch/firewall",
  "category": "network",
  "icon": "router"
}
```

### `device_types`

```json
{
  "name": "cisco-ios-xe-router",
  "sys_object_id_pattern": "1.3.6.1.4.1.9.1",
  "device_category_name": "network",
  "vendor": "Cisco",
  "model": "IOS-XE",
  "os_family": "ios-xe",
  "description": "Cisco IOS XE router family",
  "priority": 50,
  "auto_assign_packs": ["cisco-monitoring"]
}
```

Device types resolve through `sys_object_id_pattern` (longest prefix wins
within the same `priority`). `device_category_name` is the back-reference
to `device_categories[].name`. `auto_assign_packs` opts a device into
specific packs at discovery time without operator action.

### `label_keys`

```json
{
  "key": "env",
  "description": "Miljø",
  "color": null,
  "show_description": true,
  "predefined_values": ["production", "staging", "development", "test"]
}
```

Predefined label keys appear in the device-edit UI as dropdowns;
operators can still type free-form values unless you make this a
strict-enum elsewhere.

## Skip resolution and import order

Central imports sections in this order (`PACK_IMPORT_ORDER` in
`packs/service.py:535-546`):

1. `label_keys`
2. `device_categories`
3. `device_types` (needs categories)
4. `credential_templates`
5. `snmp_oids`
6. `connectors`
7. `apps` (needs connectors for slot resolution)
8. `device_templates` (needs apps to resolve `config[app_name]`)

Within each section, imports use **skip resolution** — central never
overwrites an entity that already exists with the same name unless
`pack_origin` matches the importing pack's `pack_uid`. This means:

- A pack that ships `snmp_check` v2.1.1 alongside an existing local
  edit at v2.1.0 will **not** clobber the local version. The operator
  must explicitly choose to upgrade.
- Re-importing the same pack after a content edit only writes
  versions that are strictly newer than the installed `is_latest`.
- N-1 nodes in a 4-central HA cluster losing the unique-violation race
  on first-time pack import is **expected and benign** — they emit
  `pack_import_lost_race_benign` at debug level. See CLAUDE.md "Pack
  first-import race is benign on HA".

## Versioning

Three versions stack inside one pack:

1. **Pack version** (`version`) — what operators install. Semver.
2. **App / connector versions** (`contents.apps[].versions[].version`,
   `contents.connectors[].versions[].version`) — the actual code shipped
   to collectors.
3. **Schema version** (`monctl_pack`) — pack-format compatibility.
   Always `"1.0"` today.

Pack version must be ≥ the highest app/connector version inside
(`scripts/validate_packs.py` rule 1) so an operator scanning `packs/`
can trust the pack's own version as a summary of what's inside.

## Validation

Run before submitting a pack:

```bash
python scripts/validate_packs.py packs/my-pack.json
```

Checks:

1. Pack `version` ≥ max nested app/connector version.
2. Every `source_code` compiles via stdlib `compile()`.
3. No obvious secret literals in `source_code` or `config_schema.default`.
4. `required_connectors` (the legacy alias for `connector_bindings`) is a
   list of strings if present.

CI runs the same script on every PR via `.github/workflows/tests.yml`'s
`validate-packs` job; a pytest wrapper at
`tests/central/test_pack_validation.py` runs it inside the regular
test suite.

## Worked example

The shortest non-trivial pack is `packs/basic-checks.json` — a single
section (`apps`) with three apps, each with one version, threshold
variables, and tiered alert definitions. Open it as a starting
template; a stripped-down skeleton looks like:

```json
{
  "monctl_pack": "1.0",
  "pack_uid": "my-uptime-pack",
  "name": "Uptime Checks",
  "version": "1.0.0",
  "description": "ICMP + HTTP uptime checks",
  "author": "Acme Inc.",
  "changelog": "v1.0.0 — initial release",
  "exported_at": null,
  "contents": {
    "apps": [
      {
        "name": "icmp_uptime",
        "description": "ICMP ping reachability",
        "app_type": "script",
        "target_table": "availability_latency",
        "vendor_oid_prefix": null,
        "config_schema": {
          "type": "object",
          "properties": {
            "timeout": {
              "type": "integer",
              "title": "Timeout (s)",
              "default": 5,
              "minimum": 1,
              "maximum": 30
            }
          }
        },
        "connector_bindings": [],
        "versions": [
          {
            "version": "1.0.0",
            "source_code": "from monctl_collector.polling.base import BasePoller\nfrom monctl_collector.jobs.models import PollContext, PollResult\nimport time\n\nclass Poller(BasePoller):\n    async def poll(self, context: PollContext) -> PollResult:\n        start = time.time()\n        # ... your check logic ...\n        return PollResult(\n            job_id=context.job.job_id,\n            device_id=context.job.device_id,\n            collector_node=context.node_id,\n            timestamp=time.time(),\n            metrics=[{\"name\": \"reachable\", \"value\": 1.0}],\n            config_data=None,\n            status=\"ok\",\n            reachable=True,\n            error_message=None,\n            execution_time_ms=int((time.time() - start) * 1000),\n        )\n",
            "requirements": [],
            "entry_class": "Poller",
            "is_latest": true,
            "display_template": null,
            "eligibility_oids": [],
            "volatile_keys": []
          }
        ]
      }
    ]
  }
}
```

The full per-app structure (config schemas, threshold variables, tiered
alert definitions) is in `packs/basic-checks.json` and `packs/snmp-core.json`.
For the Python authoring side, see [`app-development-guide.md`](app-development-guide.md).
