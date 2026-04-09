import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth.tsx";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { required } from "@/lib/validation.ts";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ApiError } from "@/api/client.ts";

export function LoginPage() {
  const { login, isAuthenticated, isLoading: authLoading } = useAuth();
  const usernameField = useField("", required);
  const passwordField = useField("", required);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-950">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!validateAll(usernameField, passwordField)) return;
    setError("");
    setIsSubmitting(true);

    try {
      await login({
        username: usernameField.value,
        password: passwordField.value,
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 401
            ? "Invalid username or password"
            : `Login failed: ${err.message}`,
        );
      } else {
        setError("An unexpected error occurred");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-4">
      {/* Subtle background gradient */}
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-brand-900/20 via-zinc-950 to-zinc-950" />

      <div className="relative w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600/15">
            <img src="/logo-icon.svg" alt="MonCTL" className="h-7 w-7" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
            MonCTL
          </h1>
          <p className="mt-1 text-sm text-zinc-500">Monitoring Platform</p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl shadow-black/20">
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            <div>
              <Input
                id="username"
                label="Username"
                type="text"
                placeholder="Enter username"
                autoComplete="username"
                value={usernameField.value}
                onChange={usernameField.onChange}
                onBlur={usernameField.onBlur}
                required
              />
              {usernameField.error && (
                <p className="text-xs text-red-400 mt-0.5">
                  {usernameField.error}
                </p>
              )}
            </div>
            <div>
              <Input
                id="password"
                label="Password"
                type="password"
                placeholder="Enter password"
                autoComplete="current-password"
                value={passwordField.value}
                onChange={passwordField.onChange}
                onBlur={passwordField.onBlur}
                required
              />
              {passwordField.error && (
                <p className="text-xs text-red-400 mt-0.5">
                  {passwordField.error}
                </p>
              )}
            </div>

            {error && (
              <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-400">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Sign in
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-zinc-600">
          Secure monitoring access
        </p>
      </div>
    </div>
  );
}
