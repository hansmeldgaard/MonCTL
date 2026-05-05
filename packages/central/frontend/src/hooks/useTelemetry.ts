import { useCallback } from "react";
import { apiPost } from "@/api/client.ts";

/**
 * Fire-and-forget UI telemetry. POSTs to `/v1/observability/ui-events` which
 * increments the rolling counter `ui.<event>`. Operators read aggregates via
 * `GET /v1/observability/counters?prefix=ui.<surface>&days=7`.
 *
 * Failures are swallowed — telemetry must never break the page.
 */
export function useTelemetry() {
  return useCallback((event: string) => {
    apiPost<void>("/observability/ui-events", { event }).catch(() => {
      // intentional no-op: never let telemetry failures bubble
    });
  }, []);
}
