/**
 * Runtime schemas for the highest-traffic API responses.
 *
 * Why: types/api.ts is hand-maintained, which means backend renames silently
 * break the UI on prod (F-X-005). Schemas here run on every response via
 * `apiGetSafe()`, log drift to the console, and still return the payload so
 * the UI keeps rendering. Think "insurance telemetry" rather than "hard
 * gate" — the first-line defence is still strong TypeScript typing.
 *
 * Keep these in sync with types/api.ts. Only the fields the UI actually
 * reads are listed; unknown fields are tolerated (`.passthrough()` via
 * default `.object()` behaviour).
 *
 * Schema names intentionally mirror the TS interface names with a `Schema`
 * suffix so `grep DeviceSchema` lands at the definition.
 */

import { z } from "zod";

// ── Generic envelope ────────────────────────────────────────

const metaSchema = z
  .object({
    limit: z.number().optional(),
    offset: z.number().optional(),
    count: z.number().optional(),
    total: z.number().optional(),
    tier: z.string().optional(),
  })
  .optional();

export function envelopeSchema<T extends z.ZodTypeAny>(payload: T) {
  return z.object({
    status: z.string(),
    data: payload,
    meta: metaSchema,
  });
}

// ── Device (list + detail) ───────────────────────────────────

const deviceCredentialValueSchema = z.object({
  id: z.string(),
  name: z.string(),
  credential_type: z.string(),
});

export const DeviceSchema = z.object({
  id: z.string(),
  name: z.string(),
  address: z.string(),
  device_category: z.string(),
  device_type_id: z.string().nullable(),
  device_type_name: z.string().nullable(),
  tenant_id: z.string().nullable(),
  tenant_name: z.string().nullable(),
  collector_group_id: z.string().nullable(),
  collector_group_name: z.string().nullable(),
  labels: z.record(z.string()),
  is_enabled: z.boolean(),
  credentials: z.record(deviceCredentialValueSchema),
});

export const DeviceListSchema = envelopeSchema(z.array(DeviceSchema));

// ── Collector ────────────────────────────────────────────────

export const CollectorSchema = z.object({
  id: z.string(),
  name: z.string(),
  hostname: z.string(),
  status: z.string(),
  labels: z.record(z.string()),
  last_seen_at: z.string().nullable(),
  group_id: z.string().nullable(),
  group_name: z.string().nullable(),
});

export const CollectorListSchema = envelopeSchema(z.array(CollectorSchema));

// ── Alerts ──────────────────────────────────────────────────

export const AlertEntitySchema = z.object({
  id: z.string(),
  definition_id: z.string(),
  assignment_id: z.string(),
  device_id: z.string().nullable(),
  enabled: z.boolean(),
  state: z.enum(["ok", "firing", "resolved"]),
  severity: z.string().nullable(),
  display_state: z.enum(["active", "cleared"]).nullable(),
  current_value: z.number().nullable(),
  fire_count: z.number(),
  entity_key: z.string(),
  entity_labels: z.record(z.string()),
});

export const AlertEntityListSchema = envelopeSchema(z.array(AlertEntitySchema));

export const AlertLogEntrySchema = z.object({
  id: z.string(),
  definition_id: z.string(),
  definition_name: z.string(),
  entity_key: z.string(),
  action: z.enum(["fire", "escalate", "downgrade", "clear"]),
  severity: z.string(),
  current_value: z.number(),
  threshold_value: z.number(),
  device_id: z.string(),
  device_name: z.string(),
  app_name: z.string(),
  fire_count: z.number(),
  message: z.string(),
  occurred_at: z.string(),
});

export const AlertLogListSchema = envelopeSchema(z.array(AlertLogEntrySchema));

const severityTierSchema = z.object({
  severity: z.enum(["info", "warning", "critical", "emergency", "healthy"]),
  expression: z.string().nullable(),
  message_template: z.string(),
});

export const AlertDefinitionSchema = z.object({
  id: z.string(),
  app_id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  severity_tiers: z.array(severityTierSchema),
  window: z.string(),
  enabled: z.boolean(),
});

export const AlertDefinitionListSchema = envelopeSchema(
  z.array(AlertDefinitionSchema),
);

// ── Dashboard summary ───────────────────────────────────────

const dashboardRecentAlertSchema = z.object({
  id: z.string(),
  definition_name: z.string(),
  device_name: z.string(),
  device_id: z.string().nullable(),
  entity_key: z.string(),
  current_value: z.number().nullable(),
  fire_count: z.number(),
  started_at: z.string().nullable(),
});

const dashboardWorstDeviceSchema = z.object({
  device_id: z.string(),
  device_name: z.string(),
  device_address: z.string(),
  reason: z.enum(["down", "degraded"]),
  firing_alerts: z.number(),
});

const dashboardStaleCollectorSchema = z.object({
  collector_id: z.string(),
  name: z.string(),
  last_seen: z.string().nullable(),
  stale_seconds: z.number().nullable(),
});

const dashboardTopNEntrySchema = z.object({
  device_id: z.string(),
  device_name: z.string(),
  value: z.number(),
  unit: z.string(),
  executed_at: z.string().nullable(),
});

export const DashboardSummarySchema = envelopeSchema(
  z.object({
    alert_summary: z.object({
      total_firing: z.number(),
      recent: z.array(dashboardRecentAlertSchema),
    }),
    device_health: z.object({
      total: z.number(),
      up: z.number(),
      down: z.number(),
      degraded: z.number(),
      worst: z.array(dashboardWorstDeviceSchema),
    }),
    collector_status: z.object({
      total: z.number(),
      online: z.number(),
      offline: z.number(),
      pending: z.number(),
      stale: z.array(dashboardStaleCollectorSchema),
    }),
    performance_top_n: z.object({
      cpu: z.array(dashboardTopNEntrySchema),
      memory: z.array(dashboardTopNEntrySchema),
      bandwidth: z.array(dashboardTopNEntrySchema),
    }),
  }),
);
