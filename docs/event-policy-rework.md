# Event Policy Rework — Design Doc

**Status:** draft, not yet approved
**Author:** initial sketch by Claude on 2026-04-10
**Tracks:** progress.md item #6

## Why

The current event policy system is a narrow 1:1 binding from `AlertDefinition` to `EventPolicy` with just two promotion modes (`consecutive` / `cumulative`) and a single "auto-clear on resolve" toggle. That was fine for the first production deployment but is too thin for what operators actually need:

- **Grouping** — a switch flapping an interface, losing OSPF adjacency, and triggering BGP timeouts should surface as _one_ incident, not three events the oncall has to correlate by hand.
- **Severity ladders** — a warning that's been firing for an hour should promote itself to critical, not require a second separate policy that duplicates the same condition.
- **Suppression / cooldown** — a genuine threshold oscillation (interface RTT 48↔52 ms on a 50 ms threshold) should not produce a new event every cycle. Events should represent _incidents_, not _samples_.
- **Scope overrides** — a policy should be applicable to "all devices except the lab" or "only devices with label `env=prod`" without creating a separate definition.
- **Dependency / parent-child** — if a device is unreachable, the interface-down and SNMP-timeout events coming off it are noise. They should be suppressed under the parent device-down event and auto-cleared when the parent clears.
- **Edit + history + dry-run** — UI today only has Create/Delete. Users want to tweak a threshold without rebuilding the rule from scratch, and they want to see what a change _would have done_ before enabling it.

The bug fixes in the preceding PR (engine auto-clear, orphan cleanup, mode validator) close the acute pain points but don't address any of the above. Those require a data-model change.

## Current state (post-fix PR)

```
AlertDefinition ──(1:N)── EventPolicy ──(tracks via)── ActiveEvent
                                                            │
                                                            ▼
                                                     ClickHouse events
```

- `EventPolicy` is a single row: `mode`, `fire_count_threshold`, `window_size`, `event_severity`, `auto_clear_on_resolve`, `message_template`.
- One policy promotes firings from one alert definition, uniformly across all entities of that definition.
- `ActiveEvent` (PG) tracks one row per `(policy_id, entity_key)` and carries the `clickhouse_event_id` used to UPDATE-in-place on auto-clear (fixed in the preceding PR).
- Events in CH are `ReplicatedMergeTree`, append-only, mutated via `ALTER TABLE … UPDATE` for state flips.

## Proposed data model

```
IncidentRule                          # what the user configures
 ├── match: AlertDefinition           # which alert(s) feed this rule
 ├── scope: ScopeFilter (labels)      # which subset of entities
 ├── trigger: TriggerSpec             # consecutive / cumulative / sustained
 ├── severity_ladder: [Step]          # warn@5m → crit@15m → emergency@30m
 ├── suppression: SuppressionSpec     # cooldown, dedup window, flap guard
 ├── correlation_group: str | null    # e.g. "device:{device_id}"
 ├── depends_on: IncidentRule[]       # parent-child (child suppressed when parent active)
 ├── message_template: str
 └── enabled: bool

Incident                              # what actually exists in the system
 ├── id: UUID
 ├── rule_id → IncidentRule
 ├── correlation_key: str             # from rule.correlation_group
 ├── entity_key: str                  # assignment/interface/component
 ├── parent_incident_id: UUID | null  # set when suppressed under a parent
 ├── severity: str                    # current ladder step
 ├── severity_reached_at: datetime    # last step transition
 ├── opened_at, last_fired_at, cleared_at
 ├── fire_count, flap_count
 └── labels: dict                     # for templating and filtering
```

Key shifts:

- **`IncidentRule` replaces `EventPolicy`**. Multiple rules can bind to one alert definition. The same rule can fan out across multiple alert definitions (correlation).
- **`Incident` replaces the single "active event" row in CH**. Each incident is a persistent object with a lifecycle: `opened → escalated → cleared → archived`. Oscillations _update_ the incident instead of creating siblings.
- **`correlation_group`** is a string template (`"device:{device_id}"`, `"link:{device_id}:{if_index}"`). Two firings that produce the same key within the rule's dedup window merge into one incident.
- **`depends_on`** is explicit and directional. When a parent incident opens, every child incident it dominates gets `parent_incident_id` set and is suppressed from notifications. When the parent clears, children unsuppress — if their underlying condition is still firing, they promote normally; if not, they're cleared with `auto-cleared-by-parent` reason.

## Engine flow (new)

```
For each AlertEntity in firing state:
  1. Resolve which IncidentRules match (alert def + scope filter)
  2. For each matching rule:
     a. Compute correlation_key from rule template
     b. Look up existing Incident by (rule_id, correlation_key, entity_key)
     c. If exists:
        - Apply suppression rules (flap guard, cooldown)
        - If suppression passes: update last_fired_at, recompute severity
          via ladder (time since opened → current step)
        - If ladder advanced: notify, append to history
     d. If not exists:
        - Check depends_on: is any parent rule currently firing for this entity?
          If yes → open as child (suppressed, parent_incident_id set)
        - Otherwise → open at the rule's first ladder step
     e. Cleanup children: any incidents whose parent just cleared get
        reassessed.

For each AlertEntity in resolved state:
  Any matching incident: check min-active-time; close if above threshold,
  otherwise mark "pending clear" (flap guard: will re-open if it comes back
  within the guard window without touching the incident id).
```

## UI changes

**Rules list** (replaces current Policies tab):

- Same columns as today plus Scope, Severity Ladder, Correlation, Depends.
- Row actions: edit / clone / disable / delete / **dry-run**.
- Dry-run: evaluates the rule against the last 24h of alert_log data and shows "this would have opened N incidents, escalated M, correlated K". No side effects.

**Rule editor** (new):

- Visual builder with sections matching the data model.
- Severity ladder as a step chart (time on x-axis, severity on y-axis).
- Correlation group preview shows which entities would group together given current alert_log.
- Dependency picker searches existing rules.

**Incidents tab** (replaces current Events Active/Cleared tabs):

- One row per incident, with history timeline on expand.
- Parent/child relationships rendered as tree indent.
- Suppressed children collapsed by default.

## Migration

1. Add new tables (`incident_rules`, `incidents`, `incident_history`) alongside the existing `event_policies` / `events`.
2. Shim: on startup, convert every existing `EventPolicy` into a single-step `IncidentRule` with empty scope and no ladder. No functionality change for existing users.
3. Run the new engine in **shadow mode** for one week: it writes incidents but old event_policy engine still writes events. UI reads events. Operators compare.
4. Flip: new engine becomes primary. Old event_policy code stays for one release as fallback. UI reads incidents.
5. Deprecate: next release removes old engine + event_policies table. `events` table kept for historical queries (read-only) with a DB view that maps incident lifecycle events onto the old schema for back-compat dashboards.

## Open questions

1. **Who owns incident state — PG or CH?** PG is ACID and suits mutation-heavy per-incident updates; CH is better for historical queries. Current proposal: PG for live incidents (`incidents` table), CH for historical history/audit (`incident_history` append-only). Trade-off is a two-store read for the incidents tab.
2. **Are correlation keys just string templates, or a DSL?** String templates are enough for the 80% case (`"device:{device_id}"`, `"link:{device_id}:{if_index}"`). A DSL would let users express "same rack" or "same BGP peer group" but needs a schema for entity metadata we don't have today.
3. **~~How do severity ladders interact with mode="cumulative"?~~** **RESOLVED** (phase 2a): cumulative only controls when an incident _opens_; the ladder runs on wall-clock time after opening. Same behavior for consecutive mode.
4. **Dependency scope.** Are dependencies defined per rule (rule A depends on rule B) or per entity (incident-A-on-device-X depends on incident-B-on-device-X)? Per-entity is more powerful but needs an entity-equivalence function.
5. **Flap guard window defaults.** What's a reasonable default? Proposal: 3× the alert definition's evaluation interval, clamped to [30s, 5min].
6. **Integration with automations.** Today the automation engine fires on new events. With incidents, it should fire on _incident state transitions_ (open, ladder step, clear), not every fire. Does the automation engine need per-transition filters, or do automations get rewritten to subscribe to specific transitions?

## Phase 2a — Severity ladder (shipped)

Wall-clock severity promotion after `opened_at`. Shipped as a minimal,
shadow-mode addition to `IncidentEngine`:

- New per-rule field: `incident_rules.severity_ladder` (JSONB, nullable, already allocated in phase 1).
- Format: a list of `{after_seconds: int, severity: str}` objects.
- Validation (enforced in `incidents/engine.py::_validate_ladder`):
  - Non-empty list; each entry has integer `after_seconds >= 0` and a severity in `{info, warning, critical, emergency}` (`recovery` is a state, not a ladder step).
  - First entry must have `after_seconds == 0` (defines the opening severity).
  - `after_seconds` strictly ascending.
  - Severities monotonically non-decreasing in priority — a ladder only escalates.
  - Malformed ladders log at WARNING and the engine falls back to `rule.severity`.
- Example:
  ```json
  [
    { "after_seconds": 0, "severity": "warning" },
    { "after_seconds": 900, "severity": "critical" },
    { "after_seconds": 3600, "severity": "emergency" }
  ]
  ```
- Engine behavior:
  - On open: `severity = ladder[0].severity` if ladder present, else `rule.severity`. Always sets `severity_reached_at = opened_at`.
  - On update: walks ladder, finds highest step whose `after_seconds` has been reached, promotes if that step's severity has higher priority than the current. Logs `incident_escalated`.
  - Never demotes — `_apply_ladder` guards with severity priority.
- Cumulative interaction (open question #3 resolved): `mode` still gates _opening_ (same `_meets_threshold` logic as phase 1). Once an incident is open, the ladder runs on wall-clock time after `opened_at` regardless of mode.
- No API/UI surface yet. Ladders are set via SQL for phase 2a shadow verification:
  ```sql
  UPDATE incident_rules
  SET severity_ladder = '[{"after_seconds":0,"severity":"warning"},{"after_seconds":60,"severity":"critical"}]'::jsonb
  WHERE id = '...';
  ```
  Mirror sync (`sync_incident_rules_from_event_policies`) deliberately does not touch `severity_ladder`, `scope_filter`, etc., so ladders set on mirror rules are preserved across syncs.

## Out of scope (for the rework PR)

- Label-based routing to different notification channels — that's a notification-layer concern.
- Runbook linking — can be added as a per-rule URL field but doesn't require engine changes.
- ML-based anomaly suppression. Hard no for v1; revisit if baselining becomes a requirement.

## Preceding bug fixes landed as a separate PR

The architectural work above assumes the acute bugs are already fixed. Those fixes (in chronological order) are:

- Event engine stores a consistent `clickhouse_event_id` (was a random uuid that matched nothing in CH).
- Auto-clear UPDATES the original CH row instead of inserting a separate "resolve" event that left the active row untouched. Prevents the prod symptom: up to 29 `state="active"` rows on the same device/policy.
- Scheduler cleanup task sweeps `active_events` whose assignment has been deleted and flips their CH rows to `cleared`.
- `CreateEventPolicyRequest.check_mode` + `UpdateEventPolicyRequest.check_mode` validators accept `{"consecutive", "cumulative"}` — previously they accepted `{"consecutive", "sliding_window"}`, rejecting every cumulative policy with a 422 even though the frontend and engine both used `"cumulative"`.
- Edit + enable/disable action added to the existing Policies list UI (reuses the create dialog in edit mode).

Those fixes alone are a measurable improvement; the rework in this doc builds on that stable foundation rather than replacing broken machinery mid-flight.
