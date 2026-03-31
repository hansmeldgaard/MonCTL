import type { ApiResponse } from "@/types/api.ts";

const BASE_URL = "/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }

  if (res.status === 403) {
    let detail = "Permission denied";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch { /* ignore */ }
    throw new ApiError(403, detail);
  }

  if (!res.ok) {
    let message = "Unknown error";
    try {
      const body = await res.json();
      message = body.detail ?? JSON.stringify(body);
    } catch {
      message = await res.text().catch(() => "Unknown error");
    }
    throw new ApiError(res.status, message);
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
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }

  if (res.status === 403) {
    let detail = "Permission denied";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch { /* ignore */ }
    throw new ApiError(403, detail);
  }

  if (!res.ok) {
    let message = "Unknown error";
    try {
      const body = await res.json();
      message = body.detail ?? JSON.stringify(body);
    } catch {
      message = await res.text().catch(() => "Unknown error");
    }
    throw new ApiError(res.status, message);
  }

  return res.json() as Promise<ApiResponse<T>>;
}
