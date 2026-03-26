import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Plus, Loader2, ArrowLeft, Save } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { DashboardWidget } from "@/components/DashboardWidget.tsx";
import { AddWidgetDialog } from "@/components/AddWidgetDialog.tsx";
import {
  useAnalyticsDashboard,
  useUpdateAnalyticsDashboard,
  useAnalyticsTables,
} from "@/api/hooks.ts";
import type { AnalyticsWidgetConfig } from "@/types/api.ts";

const ROW_HEIGHT = 40;

interface LocalWidget {
  id: string;
  title: string;
  config: AnalyticsWidgetConfig;
  layout: { x: number; y: number; w: number; h: number };
}

export function DashboardEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: dashboard, isLoading } = useAnalyticsDashboard(id || "");
  const updateMut = useUpdateAnalyticsDashboard();
  const { data: tables } = useAnalyticsTables();

  const [widgets, setWidgets] = useState<LocalWidget[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [showAddWidget, setShowAddWidget] = useState(false);
  const [editWidgetIdx, setEditWidgetIdx] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);

  const schema = useMemo(() => {
    if (!tables) return undefined;
    const s: Record<string, string[]> = {};
    for (const t of tables) s[t.name] = t.columns.map((c) => c.name);
    return s;
  }, [tables]);

  // Load dashboard data
  useEffect(() => {
    if (dashboard) {
      setName(dashboard.name);
      setDescription(dashboard.description);
      setWidgets(
        dashboard.widgets.map((w) => ({
          id: w.id,
          title: w.title,
          config: w.config,
          layout: w.layout,
        }))
      );
    }
  }, [dashboard]);

  function addWidget(data: { title: string; config: AnalyticsWidgetConfig }) {
    const y = widgets.reduce((max, w) => Math.max(max, w.layout.y + w.layout.h), 0);
    setWidgets((prev) => [
      ...prev,
      {
        id: `new-${Date.now()}`,
        title: data.title,
        config: data.config,
        layout: { x: 0, y, w: 12, h: 6 },
      },
    ]);
    setDirty(true);
  }

  function updateWidget(idx: number, data: { title: string; config: AnalyticsWidgetConfig }) {
    setWidgets((prev) => prev.map((w, i) => (i === idx ? { ...w, ...data } : w)));
    setDirty(true);
    setEditWidgetIdx(null);
  }

  function deleteWidget(idx: number) {
    if (!confirm(`Delete widget "${widgets[idx].title}"?`)) return;
    setWidgets((prev) => prev.filter((_, i) => i !== idx));
    setDirty(true);
  }

  async function handleSave() {
    if (!id) return;
    await updateMut.mutateAsync({
      id,
      name,
      description,
      widgets: widgets.map((w) => ({
        title: w.title,
        config: w.config,
        layout: w.layout,
      })),
    });
    setDirty(false);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-800 shrink-0">
        <Button size="sm" variant="ghost" onClick={() => navigate("/analytics/dashboards")} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Back
        </Button>
        <Input
          value={name}
          onChange={(e) => { setName(e.target.value); setDirty(true); }}
          className="max-w-xs text-sm font-semibold"
          placeholder="Dashboard name"
        />
        <Button size="sm" variant="outline" onClick={() => setShowAddWidget(true)} className="gap-1 ml-auto">
          <Plus className="h-3.5 w-3.5" />
          Add Widget
        </Button>
        <Button
          size="sm"
          onClick={handleSave}
          disabled={updateMut.isPending || !dirty}
          className="gap-1"
        >
          {updateMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save
        </Button>
      </div>

      {/* Widget grid (simple CSS grid — react-grid-layout added later if needed) */}
      <div className="flex-1 overflow-auto p-4">
        {widgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-zinc-600">
            <p className="text-sm mb-3">No widgets yet</p>
            <Button size="sm" variant="outline" onClick={() => setShowAddWidget(true)} className="gap-1">
              <Plus className="h-3.5 w-3.5" />
              Add your first widget
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {widgets.map((w, i) => (
              <div
                key={w.id}
                className={w.layout.w > 12 ? "col-span-2" : "col-span-1"}
                style={{ minHeight: `${(w.layout.h || 6) * ROW_HEIGHT}px` }}
              >
                <DashboardWidget
                  id={w.id}
                  title={w.title}
                  config={w.config}
                  onEdit={() => setEditWidgetIdx(i)}
                  onDelete={() => deleteWidget(i)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Widget Dialog */}
      <AddWidgetDialog
        open={showAddWidget}
        onClose={() => setShowAddWidget(false)}
        onSave={addWidget}
        schema={schema}
      />

      {/* Edit Widget Dialog */}
      {editWidgetIdx !== null && (
        <AddWidgetDialog
          open
          onClose={() => setEditWidgetIdx(null)}
          onSave={(data) => updateWidget(editWidgetIdx, data)}
          initial={widgets[editWidgetIdx]}
          schema={schema}
        />
      )}
    </div>
  );
}
