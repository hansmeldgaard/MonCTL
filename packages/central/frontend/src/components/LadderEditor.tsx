import { Plus, Trash2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Select } from "@/components/ui/select.tsx";
import type { IncidentRuleSeverityLadderStep } from "@/types/api.ts";

// Must stay in sync with _SEVERITY_PRIORITY in
// packages/central/src/monctl_central/incidents/engine.py:51
const SEVERITY_PRIORITY: Record<string, number> = {
  info: 0,
  warning: 1,
  critical: 2,
  emergency: 3,
};

const SEVERITY_OPTIONS: IncidentRuleSeverityLadderStep["severity"][] = [
  "info",
  "warning",
  "critical",
  "emergency",
];

/**
 * Mirrors the validation in
 * packages/central/src/monctl_central/incidents/engine.py::_validate_ladder.
 * Returns `{ ok: true }` when the ladder is valid, otherwise an `error` string
 * ready to render to the operator. An empty or null ladder is considered
 * "no ladder configured" — that's valid too; the editor treats it as `null`.
 */
export function validateLadder(
  ladder: IncidentRuleSeverityLadderStep[] | null,
): { ok: true } | { ok: false; error: string } {
  if (ladder === null || ladder.length === 0) return { ok: true };
  if (ladder[0].after_seconds !== 0) {
    return { ok: false, error: "Step 1 must have after_seconds = 0" };
  }

  let lastSec = -1;
  let lastPri = -1;
  for (let i = 0; i < ladder.length; i++) {
    const step = ladder[i];
    if (!Number.isInteger(step.after_seconds) || step.after_seconds < 0) {
      return {
        ok: false,
        error: `Step ${i + 1}: after_seconds must be a non-negative integer`,
      };
    }
    if (step.after_seconds <= lastSec && i > 0) {
      return {
        ok: false,
        error: `Step ${i + 1}: after_seconds must be strictly greater than the previous step`,
      };
    }
    const pri = SEVERITY_PRIORITY[step.severity];
    if (pri === undefined) {
      return {
        ok: false,
        error: `Step ${i + 1}: invalid severity "${step.severity}"`,
      };
    }
    if (pri < lastPri) {
      return {
        ok: false,
        error: `Step ${i + 1}: severity cannot be lower than the previous step — a ladder only escalates`,
      };
    }
    lastSec = step.after_seconds;
    lastPri = pri;
  }
  return { ok: true };
}

function formatDuration(seconds: number): string {
  if (seconds === 0) return "on open";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s === 0 ? `${m}m` : `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

interface LadderEditorProps {
  value: IncidentRuleSeverityLadderStep[] | null;
  onChange: (next: IncidentRuleSeverityLadderStep[] | null) => void;
  baseSeverity?: string;
  disabled?: boolean;
}

/**
 * Visual editor for `IncidentRule.severity_ladder`. The first row is pinned
 * at `after_seconds = 0` (the "on open" severity); subsequent rows configure
 * wall-clock escalation timers. Validation runs on every change and surfaces
 * below the table.
 */
export function LadderEditor({
  value,
  onChange,
  baseSeverity = "warning",
  disabled = false,
}: LadderEditorProps) {
  const validation = validateLadder(value);

  const enableLadder = () => {
    const severity = (
      SEVERITY_OPTIONS.includes(
        baseSeverity as IncidentRuleSeverityLadderStep["severity"],
      )
        ? baseSeverity
        : "warning"
    ) as IncidentRuleSeverityLadderStep["severity"];
    onChange([{ after_seconds: 0, severity }]);
  };

  const clearLadder = () => onChange(null);

  const updateStep = (
    index: number,
    patch: Partial<IncidentRuleSeverityLadderStep>,
  ) => {
    if (!value) return;
    const next = value.map((step, i) =>
      i === index ? { ...step, ...patch } : step,
    );
    onChange(next);
  };

  const addStep = () => {
    if (!value || value.length === 0) return;
    const last = value[value.length - 1];
    const nextSeverity: IncidentRuleSeverityLadderStep["severity"] = (() => {
      const idx = SEVERITY_OPTIONS.indexOf(last.severity);
      if (idx === -1 || idx === SEVERITY_OPTIONS.length - 1)
        return last.severity;
      return SEVERITY_OPTIONS[idx + 1];
    })();
    onChange([
      ...value,
      { after_seconds: last.after_seconds + 300, severity: nextSeverity },
    ]);
  };

  const removeStep = (index: number) => {
    if (!value || index === 0) return; // first step is pinned
    onChange(value.filter((_, i) => i !== index));
  };

  // ── Empty state ──────────────────────────────────────────
  if (value === null || value.length === 0) {
    return (
      <div className="space-y-3">
        <div className="rounded border border-dashed border-zinc-800 bg-zinc-900/40 px-4 py-6 text-center">
          <p className="text-sm text-zinc-400">
            No severity ladder configured.
          </p>
          <p className="text-xs text-zinc-600 mt-1">
            Without a ladder, incident severity stays at the rule's base level.
          </p>
          {!disabled && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={enableLadder}
              className="mt-3"
            >
              <Plus className="h-3.5 w-3.5" />
              Enable ladder
            </Button>
          )}
        </div>
      </div>
    );
  }

  // ── Editor ───────────────────────────────────────────────
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-500">
          Promote severity over time after an incident opens. Runs on wall-clock
          time independently of consecutive/cumulative mode.
        </p>
        {!disabled && (
          <Button type="button" size="sm" variant="ghost" onClick={clearLadder}>
            Clear
          </Button>
        )}
      </div>

      <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
        {/* Header */}
        <div className="grid grid-cols-[2rem_1fr_10rem_2rem] items-center gap-2 px-3 py-2 bg-zinc-900/60">
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            #
          </span>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            After (seconds)
          </span>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            Severity
          </span>
          <span />
        </div>

        {value.map((step, idx) => {
          const isFirst = idx === 0;
          return (
            <div
              key={idx}
              className="grid grid-cols-[2rem_1fr_10rem_2rem] items-center gap-2 px-3 py-2"
            >
              <span className="text-xs text-zinc-500 font-mono">{idx + 1}</span>
              {isFirst ? (
                <div className="flex items-center gap-2 text-xs text-zinc-400">
                  <Lock className="h-3 w-3" />
                  <span className="font-mono">0</span>
                  <span className="text-zinc-600">— on open</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={1}
                    value={step.after_seconds}
                    onChange={(e) =>
                      updateStep(idx, {
                        after_seconds: Number(e.target.value) || 0,
                      })
                    }
                    disabled={disabled}
                    className="w-24 font-mono text-xs"
                  />
                  <span className="text-xs text-zinc-500">
                    {formatDuration(step.after_seconds)}
                  </span>
                </div>
              )}
              <Select
                value={step.severity}
                onChange={(e) =>
                  updateStep(idx, {
                    severity: e.target
                      .value as IncidentRuleSeverityLadderStep["severity"],
                  })
                }
                disabled={disabled}
                className="text-xs"
              >
                {SEVERITY_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
              {isFirst || disabled ? (
                <span />
              ) : (
                <button
                  type="button"
                  onClick={() => removeStep(idx)}
                  className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  title="Remove step"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          );
        })}
      </div>

      {!disabled && (
        <Button type="button" size="sm" variant="secondary" onClick={addStep}>
          <Plus className="h-3.5 w-3.5" />
          Add step
        </Button>
      )}

      {!validation.ok && (
        <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          {validation.error}
        </div>
      )}
    </div>
  );
}
