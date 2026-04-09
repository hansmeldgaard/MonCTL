import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { apiGet, apiPost } from "@/api/client.ts";
import type { AuthUser, LoginPayload } from "@/types/api.ts";

// How often to proactively refresh the access token (ms)
const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

// How often to check if the user has been idle (ms)
const IDLE_CHECK_INTERVAL_MS = 30 * 1000; // 30 seconds

// Throttle activity tracking (ms)
const ACTIVITY_THROTTLE_MS = 10 * 1000; // 10 seconds

// Events that count as user activity
const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  "mousemove",
  "mousedown",
  "keydown",
  "touchstart",
  "scroll",
];

interface AuthState {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const lastActivityRef = useRef<number>(Date.now());
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const idleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------- Core auth actions ----------

  const refresh = useCallback(async () => {
    try {
      const res = await apiGet<AuthUser>("/auth/me");
      setUser(res.data);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const login = useCallback(
    async (payload: LoginPayload) => {
      await apiPost("/auth/login", payload);
      await refresh();
      lastActivityRef.current = Date.now();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    try {
      await apiPost("/auth/logout");
    } finally {
      setUser(null);
    }
  }, []);

  // ---------- Initial load ----------

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // ---------- Activity tracking ----------

  useEffect(() => {
    let lastThrottle = 0;

    function handleActivity() {
      const now = Date.now();
      if (now - lastThrottle > ACTIVITY_THROTTLE_MS) {
        lastActivityRef.current = now;
        lastThrottle = now;
      }
    }

    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, handleActivity, { passive: true });
    }

    return () => {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, handleActivity);
      }
    };
  }, []);

  // ---------- Periodic silent refresh ----------

  useEffect(() => {
    if (!user) {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      return;
    }

    refreshTimerRef.current = setInterval(async () => {
      const idleMs = Date.now() - lastActivityRef.current;
      const idleTimeoutMs = (user.idle_timeout_minutes || 60) * 60 * 1000;

      // Don't refresh if idle (let the token expire naturally)
      // idle_timeout_minutes=0 means "never timeout" — always refresh
      if (user.idle_timeout_minutes !== 0 && idleMs >= idleTimeoutMs) {
        return;
      }

      try {
        const res = await fetch("/v1/auth/refresh", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (res.ok) {
          // Update user data from refresh response (e.g. idle_timeout may have changed)
          const body = await res.json();
          if (body?.data?.idle_timeout_minutes !== undefined) {
            setUser((prev) =>
              prev
                ? {
                    ...prev,
                    idle_timeout_minutes: body.data.idle_timeout_minutes,
                  }
                : prev,
            );
          }
        } else {
          // Refresh failed — token expired
          setUser(null);
        }
      } catch {
        // Network error — don't log out, just skip this cycle
      }
    }, REFRESH_INTERVAL_MS);

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [user]);

  // ---------- Idle timeout detection ----------

  useEffect(() => {
    if (!user) {
      if (idleTimerRef.current) {
        clearInterval(idleTimerRef.current);
        idleTimerRef.current = null;
      }
      return;
    }

    const idleTimeoutMinutes = user.idle_timeout_minutes ?? 60;

    // 0 = never timeout
    if (idleTimeoutMinutes === 0) {
      return;
    }

    const idleTimeoutMs = idleTimeoutMinutes * 60 * 1000;

    idleTimerRef.current = setInterval(() => {
      const idleMs = Date.now() - lastActivityRef.current;
      if (idleMs >= idleTimeoutMs) {
        void logout();
      }
    }, IDLE_CHECK_INTERVAL_MS);

    return () => {
      if (idleTimerRef.current) {
        clearInterval(idleTimerRef.current);
        idleTimerRef.current = null;
      }
    };
  }, [user, logout]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        login,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
