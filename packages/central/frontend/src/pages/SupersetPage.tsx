import { Shield } from "lucide-react";
import { useAuth } from "@/hooks/useAuth.tsx";

const TIER_DESCRIPTIONS: Record<string, string> = {
  viewer:
    "You're signed in as a Viewer — you can read every dashboard and chart, scoped to the tenants you have access to. SQL Lab is hidden by design.",
  analyst:
    "You're signed in as an Analyst — you can build dashboards and charts AND use SQL Lab. Tenant scope still applies: every query (including raw SQL) only returns rows from your assigned tenants.",
  admin:
    "You're signed in as a Superset Admin — full access including user/role management.",
};

export function SupersetPage() {
  const { user } = useAuth();
  const access = user?.superset_access ?? "viewer";

  if (access === "none") {
    // The OAuth /authorize denial would redirect to a Superset error page
    // anyway; show the same message in MonCTL's chrome so the user gets
    // context about *why* they can't open it.
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3 text-zinc-500">
        <Shield className="h-10 w-10 text-zinc-700" />
        <p className="text-sm">
          You don't have access to Superset. Ask an admin to set your Superset
          access tier in Settings → Users.
        </p>
      </div>
    );
  }

  // Iframe is same-origin via HAProxy at /bi/ (Superset's own blueprints
  // use /superset/* so we can't reuse that prefix externally). SSO happens
  // inside the iframe via the "Sign In with monctl" button on first visit;
  // subsequent visits are seamless as long as the MonCTL session is alive.
  return (
    <div className="h-screen flex flex-col">
      <div className="px-4 py-2 border-b border-zinc-800 bg-zinc-900/50 text-xs text-zinc-500">
        {TIER_DESCRIPTIONS[access] ?? TIER_DESCRIPTIONS.viewer}
      </div>
      <iframe src="/bi/" title="Superset" className="flex-1 w-full border-0" />
    </div>
  );
}
