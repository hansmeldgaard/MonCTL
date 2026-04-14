import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Loader2, Plus, Save, Trash2 } from "lucide-react";

import {
  useAlertDefinition,
  useAppThresholds,
  useDeleteAlertDefinition,
  useUpdateAlertDefinition,
} from "@/api/hooks.ts";
import type { SeverityTier } from "@/types/api.ts";
import { Button } from "@/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Input } from "@/components/ui/input.tsx";

type NonHealthySeverity = "info" | "warning" | "critical" | "emergency";

const SEVERITY_ORDER: Record<SeverityTier["severity"], number> = {
  healthy: -1,
  info: 0,
  warning: 1,
  critical: 2,
  emergency: 3,
};

const SEVERITY_COLOURS: Record<SeverityTier["severity"], string> = {
  healthy: "bg-green-600 text-white",
  info: "bg-sky-600 text-white",
  warning: "bg-orange-600 text-white",
  critical: "bg-red-600 text-white",
  emergency: "bg-purple-700 text-white",
};

const NON_HEALTHY: NonHealthySeverity[] = [
  "info",
  "warning",
  "critical",
  "emergency",
];

export function AlertDefinitionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: defn, isLoading } = useAlertDefinition(id ?? "");
  const { data: variables } = useAppThresholds(defn?.app_id ?? "");
  const updateDef = useUpdateAlertDefinition();
  const deleteDef = useDeleteAlertDefinition();

  const [tiers, setTiers] = useState<SeverityTier[] | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Seed local tier state from the loaded def once.
  const liveTiers = tiers ?? defn?.severity_tiers ?? [];
  const dirty =
    tiers !== null && defn
      ? JSON.stringify(tiers) !== JSON.stringify(defn.severity_tiers)
      : false;

  const sortedTiers = useMemo(
    () =>
      [...liveTiers].sort(
        (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
      ),
    [liveTiers],
  );

  if (isLoading || !defn) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  const updateTier = (idx: number, patch: Partial<SeverityTier>) => {
    const next = [...liveTiers];
    const target = sortedTiers[idx];
    const originalIdx = next.findIndex((t) => t.severity === target.severity);
    if (originalIdx < 0) return;
    next[originalIdx] = { ...next[originalIdx], ...patch } as SeverityTier;
    setTiers(next);
  };

  const removeTier = (severity: SeverityTier["severity"]) => {
    setTiers(liveTiers.filter((t) => t.severity !== severity));
  };

  const availableNonHealthy = NON_HEALTHY.filter(
    (s) => !liveTiers.some((t) => t.severity === s),
  );
  const hasHealthy = liveTiers.some((t) => t.severity === "healthy");

  const addTier = (severity: SeverityTier["severity"]) => {
    const tier: SeverityTier = {
      severity,
      expression: "",
      message_template:
        severity === "healthy"
          ? `${defn.name} on {device_name} recovered`
          : `${defn.name} on {device_name}: {value}`,
    };
    setTiers([...liveTiers, tier]);
  };

  const handleSave = async () => {
    if (!dirty) return;
    setSaveError(null);
    setSaving(true);
    try {
      // Strip empty expressions and validate per-severity rules client-side
      // so the API error is nicer to read.
      const toSend = (tiers ?? []).map((t) => ({
        severity: t.severity,
        expression: (t.expression || "").trim() || null,
        message_template: (t.message_template || "").trim(),
      }));
      for (const t of toSend) {
        if (t.severity !== "healthy" && !t.expression) {
          throw new Error(`Tier '${t.severity}' needs an expression`);
        }
        if (!t.message_template) {
          throw new Error(`Tier '${t.severity}' needs a message template`);
        }
      }
      await updateDef.mutateAsync({
        id: defn.id,
        severity_tiers: toSend,
      });
      setTiers(null); // resync from refetched def
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Delete alert definition "${defn.name}"?`)) return;
    await deleteDef.mutateAsync(defn.id);
    navigate("/alerts");
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Link to="/alerts" className="hover:text-zinc-200">
              Alerts
            </Link>
            <span>/</span>
            <span>Definitions</span>
          </div>
          <h1 className="text-xl font-semibold text-zinc-100">{defn.name}</h1>
          <div className="flex items-center gap-3 text-sm text-zinc-400">
            <span>
              App:{" "}
              <Link
                to={`/apps/${defn.app_id}`}
                className="text-brand-400 hover:underline"
              >
                {defn.app_name ?? defn.app_id}
              </Link>
            </span>
            <span>Window: {defn.window}</span>
            <span>
              {defn.enabled ? (
                <span className="text-green-400">Enabled</span>
              ) : (
                <span className="text-zinc-500">Disabled</span>
              )}
            </span>
            {defn.pack_origin && (
              <span className="text-zinc-500">pack: {defn.pack_origin}</span>
            )}
          </div>
          {defn.description && (
            <p className="max-w-3xl text-sm text-zinc-400">
              {defn.description}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="bg-brand-500 hover:bg-brand-400"
          >
            <Save className="mr-1 h-4 w-4" />
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button variant="outline" onClick={handleDelete}>
            <Trash2 className="mr-1 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {saveError && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {saveError}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Severity tiers</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-zinc-500">
            Each tier is evaluated independently per cycle. The engine picks
            the highest-severity tier whose expression matches as the live
            severity. The <span className="font-semibold">healthy</span> tier
            never fires an alert — it only <em>clears</em> an already-active
            one. With an expression set it acts as a positive-clear signal;
            leave it blank to fall back to the legacy behavior (any
            non-matching sample clears the alert).
          </p>
          <div className="space-y-3">
            {sortedTiers.map((t, idx) => (
              <div
                key={t.severity}
                className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/40 p-3"
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold uppercase ${SEVERITY_COLOURS[t.severity]}`}
                  >
                    {t.severity}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-zinc-500 hover:text-red-400"
                    onClick={() => removeTier(t.severity)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-400">
                    Expression{t.severity === "healthy" ? " (optional)" : ""}
                  </label>
                  <Input
                    value={t.expression ?? ""}
                    onChange={(e) =>
                      updateTier(idx, { expression: e.target.value })
                    }
                    placeholder={
                      t.severity === "healthy"
                        ? "e.g. rtt_ms < 50  (leave blank for legacy auto-clear)"
                        : "e.g. rtt_ms > rtt_ms_warn"
                    }
                    className="font-mono text-sm"
                  />
                  {t.severity === "healthy" && (
                    <p className="mt-1 text-xs text-zinc-500">
                      When this matches, an active alert clears. Blank =
                      legacy auto-clear on any non-matching cycle.
                    </p>
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-400">
                    Message template
                  </label>
                  <textarea
                    value={t.message_template ?? ""}
                    onChange={(e) =>
                      updateTier(idx, { message_template: e.target.value })
                    }
                    rows={2}
                    className="flex w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                  />
                  <p className="mt-1 text-xs text-zinc-500">
                    Variables: {"{device_name}"}, {"{value}"}, {"{if_name}"},{" "}
                    {"{component}"}, any threshold var as {"{<name>}"}.
                  </p>
                </div>
              </div>
            ))}
          </div>

          {(availableNonHealthy.length > 0 || !hasHealthy) && (
            <div className="mt-3 flex items-center gap-2">
              <span className="text-sm text-zinc-400">Add tier:</span>
              {!hasHealthy && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => addTier("healthy")}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  healthy
                </Button>
              )}
              {availableNonHealthy.map((s) => (
                <Button
                  key={s}
                  size="sm"
                  variant="outline"
                  onClick={() => addTier(s)}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  {s}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {variables && variables.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Threshold variables</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-2 text-xs text-zinc-500">
              Named thresholds available in expressions and templates for this
              app's alerts. Edit defaults on the app page.
            </p>
            <ul className="space-y-1 text-sm">
              {variables.map((v) => (
                <li key={v.id} className="text-zinc-300">
                  <span className="font-mono text-brand-400">{v.name}</span>
                  <span className="text-zinc-500"> = </span>
                  <span>{v.default_value}</span>
                  {v.unit && <span className="text-zinc-500"> {v.unit}</span>}
                  {v.description && (
                    <span className="text-zinc-500"> — {v.description}</span>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
