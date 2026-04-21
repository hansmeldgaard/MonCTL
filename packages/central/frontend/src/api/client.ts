import type { z } from "zod";
import type { ApiResponse } from "@/types/api.ts";

const BASE_URL = "/v1";

/**
 * Cap + redact an error-response body before surfacing it to the UI. Servers
 * sometimes echo validation errors that include request fields (usernames,
 * emails, credential names); JSON-stringifying them straight into a toast or
 * error-tracking payload is an info-disclosure risk. We strip known-sensitive
 * keys and trim the result to keep tool output and logs readable.
 */
const _SENSITIVE_KEY =
  /(password|api_key|token|secret|jwt|credential|private)/i;

function _sanitize(value: unknown, depth = 0): unknown {
  if (depth > 2) return "[…]";
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) {
    return value.slice(0, 10).map((v) => _sanitize(v, depth + 1));
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = _SENSITIVE_KEY.test(k) ? "[REDACTED]" : _sanitize(v, depth + 1);
  }
  return out;
}

function safeStringifyError(body: unknown, max = 200): string {
  try {
    const s = JSON.stringify(_sanitize(body));
    return s.length > max ? s.slice(0, max) + "…" : s;
  } catch {
    return "Unknown error";
  }
}

/**
 * Send the user to /login preserving the page they were on so that after a
 * successful re-auth the router can bounce them back. `client.ts` runs outside
 * of React, so we can't use `useNavigate` here — `location.replace` is the
 * right primitive (no extra history entry, no back-button loop into a 401 page).
 */
function redirectToLogin() {
  if (window.location.pathname.startsWith("/login")) return;
  const next = window.location.pathname + window.location.search;
  const qs = next && next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
  window.location.replace(`/login${qs}`);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// ---------- Silent refresh machinery ----------

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

/**
 * Attempt to refresh the access token using the refresh cookie.
 * Returns true if successful, false otherwise.
 * Deduplicates concurrent refresh attempts.
 */
async function tryRefreshToken(): Promise<boolean> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }
  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

// ---------- Core request function ----------

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;

  let res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  // On 401, attempt one silent refresh, then retry the original request
  if (res.status === 401 && !endpoint.startsWith("/auth/")) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      res = await fetch(url, {
        ...options,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...options.headers,
        },
      });
    }
  }

  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Unauthorized");
  }

  if (res.status === 403) {
    let detail = "Permission denied";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(403, detail);
  }

  if (!res.ok) {
    let message = "Unknown error";
    let detail: unknown = undefined;
    try {
      const body = await res.json();
      detail = body.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        message =
          (detail as { message?: string }).message ??
          safeStringifyError(detail);
      } else {
        message = safeStringifyError(body);
      }
    } catch {
      const raw = await res.text().catch(() => "Unknown error");
      message = raw.length > 200 ? raw.slice(0, 200) + "…" : raw;
    }
    throw new ApiError(res.status, message, detail);
  }

  // 204 No Content (and any other empty-body success) has no JSON to parse.
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export function apiGet<T>(endpoint: string): Promise<ApiResponse<T>> {
  return request<ApiResponse<T>>(endpoint);
}

/**
 * Same as `apiGet` but additionally runs the response through a zod schema and
 * logs drift to the console. Returns the original response either way — this
 * is a non-blocking telemetry layer, not a gate. The point is to surface
 * backend contract drift during development / staging, not to break prod UI
 * on a rename the user couldn't possibly fix themselves.
 */
export async function apiGetSafe<T>(
  endpoint: string,
  schema: z.ZodTypeAny,
): Promise<ApiResponse<T>> {
  const res = await request<ApiResponse<T>>(endpoint);
  const parsed = schema.safeParse(res);
  if (!parsed.success) {
    // Log the first few issues — a full pretty-print on a big list response
    // would flood the console.
    const issues = parsed.error.issues.slice(0, 5).map((i) => ({
      path: i.path.join("."),
      code: i.code,
      message: i.message,
    }));
    // eslint-disable-next-line no-console
    console.warn(
      `[schema-drift] ${endpoint}: ${parsed.error.issues.length} issue(s)`,
      issues,
    );
  }
  return res;
}

export function apiPost<T>(
  endpoint: string,
  body?: unknown,
): Promise<ApiResponse<T>> {
  return request<ApiResponse<T>>(endpoint, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function apiPut<T>(
  endpoint: string,
  body?: unknown,
): Promise<ApiResponse<T>> {
  return request<ApiResponse<T>>(endpoint, {
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function apiPatch<T>(
  endpoint: string,
  body?: unknown,
): Promise<ApiResponse<T>> {
  return request<ApiResponse<T>>(endpoint, {
    method: "PATCH",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function apiDelete(endpoint: string): Promise<void> {
  return request<void>(endpoint, { method: "DELETE" });
}

// Special version for health endpoint which has a slightly different shape
export function apiGetRaw<T>(endpoint: string): Promise<T> {
  return request<T>(endpoint);
}

export async function apiPostFormData<T>(
  endpoint: string,
  formData: FormData,
): Promise<ApiResponse<T>> {
  const url = `${BASE_URL}${endpoint}`;

  let res = await fetch(url, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  // On 401, attempt one silent refresh, then retry
  if (res.status === 401 && !endpoint.startsWith("/auth/")) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      res = await fetch(url, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
    }
  }

  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Unauthorized");
  }

  if (res.status === 403) {
    let detail = "Permission denied";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(403, detail);
  }

  if (!res.ok) {
    let message = "Unknown error";
    let detail: unknown = undefined;
    try {
      const body = await res.json();
      detail = body.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        message =
          (detail as { message?: string }).message ??
          safeStringifyError(detail);
      } else {
        message = safeStringifyError(body);
      }
    } catch {
      const raw = await res.text().catch(() => "Unknown error");
      message = raw.length > 200 ? raw.slice(0, 200) + "…" : raw;
    }
    throw new ApiError(res.status, message, detail);
  }

  return res.json() as Promise<ApiResponse<T>>;
}
