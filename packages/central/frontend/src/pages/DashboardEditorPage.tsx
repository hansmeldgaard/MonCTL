import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Plus, Loader2, ArrowLeft, Save } from "lucide-react";
import { ResponsiveGridLayout, useContainerWidth, verticalCompactor, type LayoutItem } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { DashboardWidget } from "@/components/DashboardWidget.tsx";
import { AddWidgetDialog } from "@/components/AddWidgetDialog.tsx";
import { DashboardTimePicker, type TimeRange } from "@/components/DashboardTimePicker.tsx";
import { DashboardVariableBar } from "@/components/DashboardVariableBar.tsx";
import {
  useAnalyticsDashboard,
  useUpdateAnalyticsDashboard,
  useAnalyticsTables,
} from "@/api/hooks.ts";
import type { AnalyticsWidgetConfig, DashboardVariable } from "@/types/api.ts";

const ROW_HEIGHT = 40;
const COLS = 24;

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
  const [timeRange, setTimeRange] = useState<TimeRange>({ from: "now-1h", to: "now" });
  const [variableDefs, setVariableDefs] = useState<DashboardVariable[]>([]);
  const [variableValues, setVariableValues] = useState<Record<string, string>>({});
  const [showVarManager, setShowVarManager] = useState(false);
  const [newVarName, setNewVarName] = useState("");
  const [newVarDefault, setNewVarDefault] = useState("");
  const mounted = useRef(false);
  const { width: containerWidth, containerRef } = useContainerWidth();

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
      if (dashboard.variables) {
        setVariableDefs(dashboard.variables);
        const vals: Record<string, string> = {};
        for (const v of dashboard.variables) {
          if (v.default_value) vals[v.name] = v.default_value;
        }
        setVariableValues(vals);
      }
      mounted.current = false;
    }
  }, [dashboard]);

  const handleLayoutChange = useCallback((layout: readonly LayoutItem[], _layouts: unknown) => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    setWidgets((prev) => {
      const updated = prev.map((w) => {
        const item = layout.find((l) => l.i === w.id);
        if (!item) return w;
        const newLayout = { x: item.x, y: item.y, w: item.w, h: item.h };
        if (
          newLayout.x === w.layout.x &&
          newLayout.y === w.layout.y &&
          newLayout.w === w.layout.w &&
          newLayout.h === w.layout.h
        ) return w;
        return { ...w, layout: newLayout };
      });
      if (updated.some((w, i) => w !== prev[i])) {
        setDirty(true);
        return updated;
      }
      return prev;
    });
  }, []);

  function addWidget(data: { title: string; config: AnalyticsWidgetConfig; layout?: { w: number } }) {
    const y = widgets.reduce((max, w) => Math.max(max, w.layout.y + w.layout.h), 0);
    const w = data.layout?.w || 12;
    setWidgets((prev) => [
      ...prev,
      {
        id: `new-${Date.now()}`,
        title: data.title,
        config: data.config,
        layout: { x: 0, y, w, h: 6 },
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

  function handleVariableChange(name: string, value: string) {
    setVariableValues((prev) => ({ ...prev, [name]: value }));
  }

  function clearVariable(name: string) {
    setVariableValues((prev) => {
      const next = { ...prev };
      const def = variableDefs.find((v) => v.name === name);
      if (def?.default_value) {
        next[name] = def.default_value;
      } else {
        delete next[name];
      }
      return next;
    });
  }

  function addVariableDef() {
    if (!newVarName.trim()) return;
    if (variableDefs.some((v) => v.name === newVarName.trim())) return;
    const newVar: DashboardVariable = {
      name: newVarName.trim(),
      type: "string",
      default_value: newVarDefault.trim() || "",
    };
    setVariableDefs((prev) => [...prev, newVar]);
    if (newVarDefault.trim()) {
      setVariableValues((prev) => ({ ...prev, [newVar.name]: newVar.default_value }));
    }
    setNewVarName("");
    setNewVarDefault("");
    setDirty(true);
  }

  function removeVariableDef(name: string) {
    setVariableDefs((prev) => prev.filter((v) => v.name !== name));
    setVariableValues((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    setDirty(true);
  }

  async function handleSave() {
    if (!id) return;
    await updateMut.mutateAsync({
      id,
      name,
      description,
      variables: variableDefs,
      widgets: widgets.map((w) => ({
        title: w.title,
        config: w.config,
        layout: w.layout,
      })),
    });
    setDirty(false);
  }

  const gridLayout = useMemo(
    () =>
      widgets.map((w) => ({
        i: w.id,
        x: w.layout.x ?? 0,
        y: w.layout.y ?? 0,
        w: w.layout.w ?? 12,
        h: w.layout.h ?? 6,
        minW: 6,
        minH: 3,
      })),
    [widgets]
  );

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
        <DashboardTimePicker value={timeRange} onChange={setTimeRange} />
        <Button size="sm" variant="outline" onClick={() => setShowVarManager(!showVarManager)} className="gap-1 text-xs">
          Variables
        </Button>
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

      {/* Variable manager */}
      {showVarManager && (
        <div className="px-4 py-2 border-b border-zinc-800 bg-zinc-900/50 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400 font-medium">Dashboard Variables</span>
          </div>
          {variableDefs.map((v) => (
            <div key={v.name} className="flex items-center gap-2 text-xs">
              <code className="text-brand-400">{`{var:${v.name}}`}</code>
              <span className="text-zinc-500">default: {v.default_value || "(none)"}</span>
              <button onClick={() => removeVariableDef(v.name)} className="text-zinc-600 hover:text-red-400 ml-auto">Remove</button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newVarName}
              onChange={(e) => setNewVarName(e.target.value)}
              placeholder="Variable name"
              className="w-32 text-xs h-7"
            />
            <Input
              value={newVarDefault}
              onChange={(e) => setNewVarDefault(e.target.value)}
              placeholder="Default value"
              className="w-32 text-xs h-7"
            />
            <Button size="sm" variant="outline" onClick={addVariableDef} className="h-7 text-xs">Add</Button>
          </div>
        </div>
      )}

      {/* Variable bar */}
      {variableDefs.length > 0 && (
        <DashboardVariableBar
          variables={variableDefs}
          values={variableValues}
          onClear={clearVariable}
        />
      )}

      {/* Widget grid */}
      <div className="flex-1 overflow-auto p-4" ref={containerRef}>
        {widgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-zinc-600">
            <p className="text-sm mb-3">No widgets yet</p>
            <Button size="sm" variant="outline" onClick={() => setShowAddWidget(true)} className="gap-1">
              <Plus className="h-3.5 w-3.5" />
              Add your first widget
            </Button>
          </div>
        ) : (
          <ResponsiveGridLayout
            className="dashboard-grid"
            width={containerWidth}
            layouts={{ lg: gridLayout }}
            breakpoints={{ lg: 0 }}
            cols={{ lg: COLS }}
            rowHeight={ROW_HEIGHT}
            margin={[12, 12] as const}
            dragConfig={{ enabled: true, handle: ".drag-handle", bounded: false, threshold: 3 }}
            resizeConfig={{ enabled: true, handles: ["se"] as const }}
            compactor={verticalCompactor}
            onLayoutChange={handleLayoutChange}
          >
            {widgets.map((w, i) => (
              <div key={w.id}>
                <DashboardWidget
                  id={w.id}
                  title={w.title}
                  config={w.config}
                  timeRange={timeRange}
                  variables={variableValues}
                  onVariableChange={handleVariableChange}
                  onEdit={() => setEditWidgetIdx(i)}
                  onDelete={() => deleteWidget(i)}
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        )}
      </div>

      {/* Add Widget Dialog */}
      <AddWidgetDialog
        open={showAddWidget}
        onClose={() => setShowAddWidget(false)}
        onSave={addWidget}
        schema={schema}
        variableDefs={variableDefs}
      />

      {/* Edit Widget Dialog */}
      {editWidgetIdx !== null && (
        <AddWidgetDialog
          open
          onClose={() => setEditWidgetIdx(null)}
          onSave={(data) => updateWidget(editWidgetIdx, data)}
          initial={widgets[editWidgetIdx]}
          schema={schema}
          variableDefs={variableDefs}
        />
      )}
    </div>
  );
}
