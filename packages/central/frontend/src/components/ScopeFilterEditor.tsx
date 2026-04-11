import { useRef, useState } from "react";
import { Plus, Trash2, Asterisk } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import type { IncidentRuleScopeFilter } from "@/types/api.ts";

// Internal row shape — React state is a list of `{key, value, wildcard}`
// rather than a dict so we can track per-row edits without collapsing
// duplicate keys mid-edit. On save we flatten to the `Record<string,string>`
// the API expects. Empty `key` rows are dropped from the output.
interface ScopeRow {
  id: string;
  key: string;
  value: string;
  wildcard: boolean;
}

let rowIdCounter = 0;
const nextRowId = () => `row_${++rowIdCounter}`;

function dictToRows(dict: IncidentRuleScopeFilter | null): ScopeRow[] {
  if (!dict) return [];
  return Object.entries(dict).map(([key, value]) => ({
    id: nextRowId(),
    key,
    value: value === "" ? "" : value,
    wildcard: value === "",
  }));
}

function rowsToDict(rows: ScopeRow[]): IncidentRuleScopeFilter {
  const result: IncidentRuleScopeFilter = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    result[key] = row.wildcard ? "" : row.value;
  }
  return result;
}

/**
 * Mirrors `_validate_scope_filter` in
 * packages/central/src/monctl_central/incidents/engine.py:142.
 * Duplicate keys and empty keys are editor-level concerns that the
 * engine never sees (rowsToDict collapses duplicates on save), so this
 * validator runs against the *live* row list to catch them before submit.
 */
export function validateScopeRows(
  rows: ScopeRow[],
): { ok: true } | { ok: false; error: string } {
  const seen = new Set<string>();
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const key = row.key.trim();
    if (!key) {
      return { ok: false, error: `Row ${i + 1}: key cannot be empty` };
    }
    if (seen.has(key)) {
      return {
        ok: false,
        error: `Row ${i + 1}: duplicate key "${key}"`,
      };
    }
    seen.add(key);
  }
  return { ok: true };
}

interface ScopeFilterEditorProps {
  value: IncidentRuleScopeFilter | null;
  onChange: (next: IncidentRuleScopeFilter | null) => void;
  disabled?: boolean;
}

/**
 * Visual editor for `IncidentRule.scope_filter`. Rows are key/value pairs
 * that AND-match against `AlertEntity.entity_labels` in the engine. A row
 * can be marked "wildcard" to match "key must exist, any value" — that
 * writes the empty string as the value per the engine convention.
 */
export function ScopeFilterEditor({
  value,
  onChange,
  disabled = false,
}: ScopeFilterEditorProps) {
  // Local row state is the source of truth for the editor UI. Empty-key
  // rows and in-progress edits don't survive the round-trip through the
  // dict format, so we can't drive the editor directly off `value` — the
  // act of adding a new row (which starts with an empty key) would emit
  // `{}` upstream and immediately wipe the row we just added.
  //
  // Instead: initialize `rows` from `value` on mount, and only re-hydrate
  // when the parent passes a value we *didn't* just emit ourselves (which
  // happens when the dialog opens on a different rule). `lastEmittedRef`
  // tracks the last dict we pushed upstream; any prop change matching it
  // is our own echo and is ignored.
  const [rows, setRows] = useState<ScopeRow[]>(() => dictToRows(value));
  const lastEmittedRef = useRef<string>(JSON.stringify(value ?? null));
  const [lastValueKey, setLastValueKey] = useState(
    JSON.stringify(value ?? null),
  );
  const valueKey = JSON.stringify(value ?? null);
  if (lastValueKey !== valueKey) {
    if (valueKey !== lastEmittedRef.current) {
      // External change — not something we just emitted. Re-hydrate.
      setRows(dictToRows(value));
    }
    setLastValueKey(valueKey);
  }

  const validation = validateScopeRows(rows);

  const emit = (output: IncidentRuleScopeFilter | null) => {
    lastEmittedRef.current = JSON.stringify(output ?? null);
    onChange(output);
  };

  const pushUpstream = (nextRows: ScopeRow[]) => {
    setRows(nextRows);
    const v = validateScopeRows(nextRows);
    if (!v.ok) {
      // Editor is in an invalid transient state (empty key, duplicate,
      // etc). Don't send a corrupted snapshot upstream — keep the
      // parent's copy of scopeFilter stable so the row doesn't vanish
      // from this editor when React re-runs on the next state tick.
      return;
    }
    const dict = rowsToDict(nextRows);
    emit(Object.keys(dict).length === 0 ? null : dict);
  };

  const enable = () => {
    pushUpstream([{ id: nextRowId(), key: "", value: "", wildcard: false }]);
  };

  const clearAll = () => {
    setRows([]);
    emit(null);
  };

  const addRow = () => {
    pushUpstream([
      ...rows,
      { id: nextRowId(), key: "", value: "", wildcard: false },
    ]);
  };

  const removeRow = (id: string) => {
    pushUpstream(rows.filter((r) => r.id !== id));
  };

  const updateRow = (id: string, patch: Partial<ScopeRow>) => {
    pushUpstream(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  // ── Empty state ──────────────────────────────────────────
  if (rows.length === 0) {
    return (
      <div className="space-y-3">
        <div className="rounded border border-dashed border-zinc-800 bg-zinc-900/40 px-4 py-6 text-center">
          <p className="text-sm text-zinc-400">No scope filter configured.</p>
          <p className="text-xs text-zinc-600 mt-1">
            Without a scope filter, the rule evaluates every entity the alert
            definition matches.
          </p>
          {!disabled && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={enable}
              className="mt-3"
            >
              <Plus className="h-3.5 w-3.5" />
              Enable scope filter
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
          Restrict the rule to entities whose labels AND-match all these
          key/value pairs. Toggle "Any value" to match on key presence only.
        </p>
        {!disabled && (
          <Button type="button" size="sm" variant="ghost" onClick={clearAll}>
            Clear
          </Button>
        )}
      </div>

      <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
        <div className="grid grid-cols-[1fr_1fr_7rem_2rem] items-center gap-2 px-3 py-2 bg-zinc-900/60">
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            Label key
          </span>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            Required value
          </span>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            Any value
          </span>
          <span />
        </div>

        {rows.map((row) => (
          <div
            key={row.id}
            className="grid grid-cols-[1fr_1fr_7rem_2rem] items-center gap-2 px-3 py-2"
          >
            <Input
              value={row.key}
              onChange={(e) => updateRow(row.id, { key: e.target.value })}
              placeholder="device_name"
              disabled={disabled}
              className="font-mono text-xs"
            />
            {row.wildcard ? (
              <div className="flex items-center gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5">
                <Asterisk className="h-3 w-3 text-zinc-500" />
                <span className="text-xs text-zinc-500">any value</span>
              </div>
            ) : (
              <Input
                value={row.value}
                onChange={(e) => updateRow(row.id, { value: e.target.value })}
                placeholder="prod"
                disabled={disabled}
                className="font-mono text-xs"
              />
            )}
            <label className="flex items-center gap-2 cursor-pointer justify-self-start">
              <input
                type="checkbox"
                checked={row.wildcard}
                onChange={(e) =>
                  updateRow(row.id, {
                    wildcard: e.target.checked,
                    value: e.target.checked ? "" : row.value,
                  })
                }
                className="rounded border-zinc-700"
                disabled={disabled}
              />
              <span className="text-xs text-zinc-400">wildcard</span>
            </label>
            {disabled ? (
              <span />
            ) : (
              <button
                type="button"
                onClick={() => removeRow(row.id)}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Remove filter"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>

      {!disabled && (
        <Button type="button" size="sm" variant="secondary" onClick={addRow}>
          <Plus className="h-3.5 w-3.5" />
          Add filter
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
