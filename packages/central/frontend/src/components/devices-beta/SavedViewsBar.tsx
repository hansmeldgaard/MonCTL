import { useState } from "react";
import { Activity, Plus, X } from "lucide-react";
import {
  useCreateSavedView,
  useDeleteSavedView,
  useSavedViews,
} from "@/api/hooks.ts";
import { useTelemetry } from "@/hooks/useTelemetry.ts";
import type { SavedView, SavedViewFilter } from "@/types/api.ts";

interface SavedViewsBarProps {
  page: string; // 'devices-beta'
  activeViewId: string | null;
  onPickView: (view: SavedView) => void;
  /** Snapshot of the current page filter state, used by Save current. */
  currentFilter: SavedViewFilter;
}

export function SavedViewsBar({
  page,
  activeViewId,
  onPickView,
  currentFilter,
}: SavedViewsBarProps) {
  const { data: response } = useSavedViews(page);
  const views = response?.data ?? [];
  const createView = useCreateSavedView();
  const deleteView = useDeleteSavedView();
  const track = useTelemetry();
  const [hoverId, setHoverId] = useState<string | null>(null);

  async function handleSaveCurrent() {
    const name = window.prompt("Name this view:");
    if (!name?.trim()) return;
    await createView.mutateAsync({
      page,
      name: name.trim(),
      filter_json: currentFilter,
    });
    track("devices_beta.view_saved");
  }

  return (
    <div className="flex h-[34px] items-center gap-1.5 overflow-x-auto px-4 pb-2.5">
      <span
        className="shrink-0 text-[10.5px] font-medium uppercase tracking-[0.5px]"
        style={{ color: "var(--text-4)" }}
      >
        Views
      </span>
      {views.map((v) => {
        const active = v.id === activeViewId;
        const hovered = v.id === hoverId;
        return (
          <div
            key={v.id}
            className="group relative flex shrink-0 items-center"
            onMouseEnter={() => setHoverId(v.id)}
            onMouseLeave={() => setHoverId(null)}
          >
            <button
              type="button"
              onClick={() => onPickView(v)}
              className="flex h-6 cursor-pointer items-center gap-1.5 rounded-[4px] border px-2 text-[11.5px] transition-colors"
              style={{
                background: active
                  ? "color-mix(in oklch, var(--brand) 16%, transparent)"
                  : "var(--surf-2)",
                borderColor: active
                  ? "color-mix(in oklch, var(--brand) 45%, transparent)"
                  : "var(--border)",
                color: active ? "var(--text)" : "var(--text-2)",
                fontWeight: active ? 500 : 400,
                paddingRight: hovered ? 22 : undefined,
              }}
            >
              <Activity className="h-2.5 w-2.5 opacity-70" aria-hidden />
              <span>{v.name}</span>
            </button>
            {hovered && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(`Delete view "${v.name}"?`)) {
                    void deleteView.mutateAsync({ id: v.id, page });
                  }
                }}
                className="absolute right-1 cursor-pointer rounded p-0.5 transition-colors hover:bg-white/10"
                style={{ color: "var(--text-3)" }}
                aria-label={`Delete view ${v.name}`}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            )}
          </div>
        );
      })}
      <span
        aria-hidden
        className="mx-1 h-4 w-px shrink-0"
        style={{ background: "var(--border)" }}
      />
      <button
        type="button"
        onClick={() => void handleSaveCurrent()}
        disabled={createView.isPending}
        className="flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded-[4px] border border-dashed px-2 text-[11.5px] transition-colors hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ borderColor: "var(--border-2)", color: "var(--text-3)" }}
      >
        <Plus className="h-2.5 w-2.5" /> Save current
      </button>
    </div>
  );
}
