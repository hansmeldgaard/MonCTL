import { useState, useMemo } from "react";
import { Plus, Trash2, ChevronDown, ChevronRight, AlertTriangle, X } from "lucide-react";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { SchemaConfigFields } from "@/components/SchemaConfigFields.tsx";
import { LabelEditor } from "@/components/LabelEditor.tsx";
import {
  useApps,
  useAppDetail,
  useCredentials,
  useCollectorGroups,
} from "@/api/hooks.ts";
import type {
  TemplateConfig,
  TemplateMonitoringConfig,
  TemplateMonitoringCheck,
  TemplateAppEntry,
  AppSummary,
  InterfaceRule,
} from "@/types/api.ts";

interface TemplateConfigEditorProps {
  value: TemplateConfig;
  onChange: (config: TemplateConfig) => void;
  disabled?: boolean;
}

export function TemplateConfigEditor({ value, onChange, disabled }: TemplateConfigEditorProps) {
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Section enable state — auto-enabled if data exists
  const [monEnabled, setMonEnabled] = useState(!!value.monitoring);
  const [appsEnabled, setAppsEnabled] = useState(!!(value.apps && value.apps.length > 0));
  const [credEnabled, setCredEnabled] = useState(!!value.default_credential_id);
  const [cgEnabled, setCgEnabled] = useState(!!value.default_collector_group_id);
  const [labelsEnabled, setLabelsEnabled] = useState(
    !!(value.labels && Object.keys(value.labels).length > 0),
  );
  const [ifRulesEnabled, setIfRulesEnabled] = useState(
    !!(value.interface_rules && value.interface_rules.length > 0),
  );

  function switchToJson() {
    setJsonText(JSON.stringify(value, null, 2));
    setJsonError(null);
    setMode("json");
  }

  function switchToVisual() {
    try {
      const parsed = JSON.parse(jsonText);
      onChange(parsed);
      setJsonError(null);
      setMode("visual");
      // Sync enable states
      setMonEnabled(!!parsed.monitoring);
      setAppsEnabled(!!(parsed.apps && parsed.apps.length > 0));
      setCredEnabled(!!parsed.default_credential_id);
      setCgEnabled(!!parsed.default_collector_group_id);
      setLabelsEnabled(!!(parsed.labels && Object.keys(parsed.labels).length > 0));
      setIfRulesEnabled(!!(parsed.interface_rules && parsed.interface_rules.length > 0));
    } catch {
      setJsonError("Invalid JSON — fix errors before switching to Visual mode.");
    }
  }

  function update(patch: Partial<TemplateConfig>) {
    onChange({ ...value, ...patch });
  }

  function toggleSection(
    section: string,
    enabled: boolean,
    setEnabled: (v: boolean) => void,
  ) {
    setEnabled(!enabled);
    if (enabled) {
      // Disabling — remove the key from config
      const next = { ...value };
      delete (next as Record<string, unknown>)[section];
      onChange(next);
    }
  }

  return (
    <div className="space-y-3">
      {/* Mode toggle */}
      <div className="flex items-center justify-between">
        <Label className="text-sm font-medium text-zinc-300">Template Configuration</Label>
        <div className="flex items-center gap-1 rounded-md border border-zinc-700 p-0.5">
          <button
            type="button"
            className={`px-3 py-1 text-xs rounded ${mode === "visual" ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"}`}
            onClick={mode === "json" ? switchToVisual : undefined}
          >
            Visual
          </button>
          <button
            type="button"
            className={`px-3 py-1 text-xs rounded ${mode === "json" ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"}`}
            onClick={mode === "visual" ? switchToJson : undefined}
          >
            JSON
          </button>
        </div>
      </div>

      {mode === "json" ? (
        <div className="space-y-1.5">
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              setJsonError(null);
              try {
                const parsed = JSON.parse(e.target.value);
                onChange(parsed);
              } catch {
                // Don't update parent while typing invalid JSON
              }
            }}
            rows={16}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
            disabled={disabled}
          />
          {jsonError && <p className="text-xs text-red-400">{jsonError}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Section: Monitoring */}
          <SectionHeader
            label="Monitoring"
            enabled={monEnabled}
            onToggle={() => toggleSection("monitoring", monEnabled, setMonEnabled)}
            count={
              monEnabled
                ? [value.monitoring?.availability, value.monitoring?.latency, value.monitoring?.interface].filter(Boolean).length
                : 0
            }
          />
          {monEnabled && (
            <div className="ml-6 space-y-2">
              <MonitoringSection
                monitoring={value.monitoring || {}}
                onChange={(m) => update({ monitoring: m })}
                disabled={disabled}
              />
            </div>
          )}

          {/* Section: Apps */}
          <SectionHeader
            label="Apps"
            enabled={appsEnabled}
            onToggle={() => toggleSection("apps", appsEnabled, setAppsEnabled)}
            count={appsEnabled ? (value.apps?.length ?? 0) : 0}
          />
          {appsEnabled && (
            <div className="ml-6 space-y-2">
              <AppListSection
                apps={value.apps || []}
                onChange={(apps) => update({ apps })}
                disabled={disabled}
              />
            </div>
          )}

          {/* Section: Default Credential */}
          <SectionHeader
            label="Default Credential"
            enabled={credEnabled}
            onToggle={() => toggleSection("default_credential_id", credEnabled, setCredEnabled)}
          />
          {credEnabled && (
            <div className="ml-6">
              <CredentialSection
                credentialId={value.default_credential_id}
                onChange={(id) => update({ default_credential_id: id })}
                disabled={disabled}
              />
            </div>
          )}

          {/* Section: Collector Group */}
          <SectionHeader
            label="Collector Group"
            enabled={cgEnabled}
            onToggle={() => toggleSection("default_collector_group_id", cgEnabled, setCgEnabled)}
          />
          {cgEnabled && (
            <div className="ml-6">
              <CollectorGroupSection
                groupId={value.default_collector_group_id}
                onChange={(id) => update({ default_collector_group_id: id })}
                disabled={disabled}
              />
            </div>
          )}

          {/* Section: Labels */}
          <SectionHeader
            label="Labels"
            enabled={labelsEnabled}
            onToggle={() => toggleSection("labels", labelsEnabled, setLabelsEnabled)}
            count={labelsEnabled ? Object.keys(value.labels || {}).length : 0}
          />
          {labelsEnabled && (
            <div className="ml-6">
              <LabelEditor
                labels={value.labels || {}}
                onChange={(labels) =>
                  update({ labels: Object.keys(labels).length > 0 ? labels : undefined })
                }
              />
              <p className="mt-1 text-xs text-zinc-500">
                Merged with existing device labels when applied. Existing keys are overwritten.
              </p>
            </div>
          )}

          {/* Section: Interface Rules */}
          <SectionHeader
            label="Interface Rules"
            enabled={ifRulesEnabled}
            onToggle={() => toggleSection("interface_rules", ifRulesEnabled, setIfRulesEnabled)}
            count={ifRulesEnabled ? (value.interface_rules?.length ?? 0) : 0}
          />
          {ifRulesEnabled && (
            <div className="ml-6">
              <InterfaceRulesSection
                rules={value.interface_rules || []}
                onChange={(rules) => update({ interface_rules: rules.length > 0 ? rules : undefined })}
                disabled={disabled}
              />
              <p className="mt-1 text-xs text-zinc-500">
                Auto-configure interface monitoring based on name, alias, description, or speed when discovered.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Section Header ── */

function SectionHeader({
  label,
  enabled,
  onToggle,
  count,
}: {
  label: string;
  enabled: boolean;
  onToggle: () => void;
  count?: number;
}) {
  return (
    <div
      className="flex items-center gap-2 cursor-pointer select-none group"
      onClick={onToggle}
    >
      <input
        type="checkbox"
        checked={enabled}
        onChange={onToggle}
        onClick={(e) => e.stopPropagation()}
        className="h-3.5 w-3.5 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 focus:ring-offset-0"
      />
      {enabled ? (
        <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
      ) : (
        <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />
      )}
      <span className="text-sm font-medium text-zinc-200 group-hover:text-zinc-100">
        {label}
      </span>
      {count != null && count > 0 && (
        <Badge variant="default" className="text-xs">
          {count}
        </Badge>
      )}
      {!enabled && (
        <span className="text-xs text-zinc-600 italic">not included</span>
      )}
    </div>
  );
}

/* ── Section 0: Monitoring ── */

const AVAIL_LATENCY_INTERVALS = [
  { value: "30", label: "30s" },
  { value: "60", label: "60s" },
  { value: "120", label: "2 min" },
  { value: "300", label: "5 min" },
];

const INTERFACE_INTERVALS = [
  { value: "60", label: "1 min" },
  { value: "120", label: "2 min" },
  { value: "300", label: "5 min" },
  { value: "600", label: "10 min" },
  { value: "900", label: "15 min" },
  { value: "1800", label: "30 min" },
];

function MonitoringSection({
  monitoring,
  onChange,
  disabled,
}: {
  monitoring: TemplateMonitoringConfig;
  onChange: (m: TemplateMonitoringConfig) => void;
  disabled?: boolean;
}) {
  const { data: appsResp } = useApps();
  const allApps = appsResp?.data ?? [];
  const monitoringApps = useMemo(
    () => allApps.filter((a) => a.target_table === "availability_latency"),
    [allApps],
  );
  const interfaceApps = useMemo(
    () => allApps.filter((a) => a.target_table === "interface"),
    [allApps],
  );

  return (
    <div className="space-y-2">
      <MonitoringRoleRow
        role="availability"
        label="Availability check"
        check={monitoring.availability}
        apps={monitoringApps}
        intervals={AVAIL_LATENCY_INTERVALS}
        onChange={(c) => onChange({ ...monitoring, availability: c })}
        onClear={() => {
          const next = { ...monitoring };
          delete next.availability;
          onChange(next);
        }}
        disabled={disabled}
      />
      <MonitoringRoleRow
        role="latency"
        label="Latency check"
        check={monitoring.latency}
        apps={monitoringApps}
        intervals={AVAIL_LATENCY_INTERVALS}
        onChange={(c) => onChange({ ...monitoring, latency: c })}
        onClear={() => {
          const next = { ...monitoring };
          delete next.latency;
          onChange(next);
        }}
        disabled={disabled}
      />
      <MonitoringRoleRow
        role="interface"
        label="Interface polling"
        check={monitoring.interface}
        apps={interfaceApps}
        intervals={INTERFACE_INTERVALS}
        onChange={(c) => onChange({ ...monitoring, interface: c })}
        onClear={() => {
          const next = { ...monitoring };
          delete next.interface;
          onChange(next);
        }}
        disabled={disabled}
      />
    </div>
  );
}

function MonitoringRoleRow({
  role,
  label,
  check,
  apps,
  intervals,
  onChange,
  onClear,
  disabled,
}: {
  role: string;
  label: string;
  check: TemplateMonitoringCheck | null | undefined;
  apps: AppSummary[];
  intervals: { value: string; label: string }[];
  onChange: (c: TemplateMonitoringCheck) => void;
  onClear: () => void;
  disabled?: boolean;
}) {
  const enabled = !!check;
  const appId = apps.find((a) => a.name === check?.app_name)?.id;
  const { data: appDetail } = useAppDetail(appId);
  const hasSchema =
    appDetail?.config_schema &&
    (appDetail.config_schema as { properties?: Record<string, unknown> }).properties &&
    Object.keys(
      (appDetail.config_schema as { properties: Record<string, unknown> }).properties,
    ).length > 0;

  function toggle() {
    if (enabled) {
      onClear();
    } else {
      const defaultApp = apps[0]?.name ?? "";
      const defaultInterval = role === "interface" ? 300 : 60;
      onChange({ app_name: defaultApp, config: {}, interval_seconds: defaultInterval });
    }
  }

  return (
    <div className={`rounded-md border p-3 ${enabled ? "border-zinc-700" : "border-zinc-800 opacity-50"}`}>
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={enabled}
          onChange={toggle}
          className="h-3.5 w-3.5 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 focus:ring-offset-0"
        />
        <span className="text-sm font-medium text-zinc-300">{label}</span>
      </div>
      {enabled && check && (
        <div className="mt-2 space-y-2">
          <div className="grid grid-cols-[1fr_130px] gap-2">
            <Select
              value={check.app_name}
              onChange={(e) => onChange({ ...check, app_name: e.target.value, config: {} })}
              disabled={disabled}
            >
              <option value="">-- Select app --</option>
              {apps.map((a) => (
                <option key={a.id} value={a.name}>
                  {a.description || a.name}
                </option>
              ))}
            </Select>
            <Select
              value={String(check.interval_seconds)}
              onChange={(e) => onChange({ ...check, interval_seconds: parseInt(e.target.value, 10) })}
              disabled={disabled}
            >
              {intervals.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </Select>
          </div>
          {check.app_name && hasSchema && (
            <SchemaConfigFields
              schema={appDetail!.config_schema}
              config={check.config}
              onChange={(newConfig) => onChange({ ...check, config: newConfig })}
              prefix={`mon-${role}`}
              disabled={disabled}
            />
          )}
        </div>
      )}
    </div>
  );
}

/* ── Section 1: Apps ── */

function AppListSection({
  apps,
  onChange,
  disabled,
}: {
  apps: TemplateAppEntry[];
  onChange: (apps: TemplateAppEntry[]) => void;
  disabled?: boolean;
}) {
  function addApp() {
    onChange([
      ...apps,
      { app_name: "", schedule_type: "interval", schedule_value: "60", config: {} },
    ]);
  }

  function updateApp(index: number, entry: TemplateAppEntry) {
    const next = [...apps];
    next[index] = entry;
    onChange(next);
  }

  function removeApp(index: number) {
    onChange(apps.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-2">
      {apps.map((entry, i) => (
        <TemplateAppCard
          key={i}
          entry={entry}
          index={i}
          onChange={(e) => updateApp(i, e)}
          onRemove={() => removeApp(i)}
          disabled={disabled}
        />
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={addApp} className="gap-1.5">
        <Plus className="h-3.5 w-3.5" /> Add App
      </Button>
    </div>
  );
}

function TemplateAppCard({
  entry,
  index,
  onChange,
  onRemove,
  disabled,
}: {
  entry: TemplateAppEntry;
  index: number;
  onChange: (e: TemplateAppEntry) => void;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const { data: appsResp } = useApps();
  const allApps = appsResp?.data ?? [];
  const appId = allApps.find((a) => a.name === entry.app_name)?.id;
  const { data: appDetail } = useAppDetail(appId);
  const hasSchema =
    appDetail?.config_schema &&
    (appDetail.config_schema as { properties?: Record<string, unknown> }).properties &&
    Object.keys(
      (appDetail.config_schema as { properties: Record<string, unknown> }).properties,
    ).length > 0;
  const [expanded, setExpanded] = useState(!entry.app_name);
  const appNotFound = entry.app_name && !allApps.find((a) => a.name === entry.app_name);

  return (
    <div className="rounded-md border border-zinc-700 p-3 space-y-2">
      {/* Summary row */}
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-2 cursor-pointer flex-1 min-w-0"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
          )}
          <span className="text-sm text-zinc-200 truncate">
            {entry.app_name || "New app"}
          </span>
          {appNotFound && (
            <span className="flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle className="h-3 w-3" /> Not found
            </span>
          )}
          {entry.app_name && !expanded && (
            <span className="text-xs text-zinc-500">
              {entry.schedule_type} / {entry.schedule_value}s
              {entry.role ? ` / ${entry.role}` : ""}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
          title="Remove"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Expanded form */}
      {expanded && (
        <div className="space-y-3 pt-1">
          <div>
            <Label className="text-xs text-zinc-400">App</Label>
            <Select
              value={entry.app_name}
              onChange={(e) => onChange({ ...entry, app_name: e.target.value, config: {} })}
              disabled={disabled}
            >
              <option value="">-- Select app --</option>
              {allApps.map((a) => (
                <option key={a.id} value={a.name}>
                  {a.name} {a.description ? `- ${a.description}` : ""}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs text-zinc-400">Schedule Type</Label>
              <Select
                value={entry.schedule_type}
                onChange={(e) => onChange({ ...entry, schedule_type: e.target.value })}
                disabled={disabled}
              >
                <option value="interval">Interval (seconds)</option>
                <option value="cron">Cron expression</option>
              </Select>
            </div>
            <div>
              <Label className="text-xs text-zinc-400">
                {entry.schedule_type === "interval" ? "Interval (s)" : "Cron"}
              </Label>
              <Input
                value={entry.schedule_value}
                onChange={(e) => onChange({ ...entry, schedule_value: e.target.value })}
                placeholder={entry.schedule_type === "interval" ? "60" : "*/5 * * * *"}
                disabled={disabled}
              />
            </div>
          </div>

          <div>
            <Label className="text-xs text-zinc-400">
              Role <span className="text-zinc-600">(optional)</span>
            </Label>
            <Select
              value={entry.role || ""}
              onChange={(e) => onChange({ ...entry, role: e.target.value || undefined })}
              disabled={disabled}
            >
              <option value="">-- None --</option>
              <option value="performance">performance</option>
              <option value="config">config</option>
            </Select>
          </div>

          {/* Schema-driven config fields */}
          {entry.app_name && hasSchema ? (
            <div className="space-y-2 rounded-md border border-zinc-800 p-3">
              <span className="text-xs font-medium text-zinc-400">App Configuration</span>
              <SchemaConfigFields
                schema={appDetail!.config_schema}
                config={entry.config}
                onChange={(newConfig) => onChange({ ...entry, config: newConfig })}
                prefix={`tpl-app-${index}`}
                disabled={disabled}
              />
            </div>
          ) : entry.app_name ? (
            <div>
              <Label className="text-xs text-zinc-400">Config (JSON)</Label>
              <textarea
                rows={3}
                value={JSON.stringify(entry.config, null, 2)}
                onChange={(e) => {
                  try {
                    onChange({ ...entry, config: JSON.parse(e.target.value) });
                  } catch {
                    /* typing */
                  }
                }}
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-1 focus:ring-brand-500"
                placeholder="{}"
                disabled={disabled}
              />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/* ── Section 2: Credential ── */

function CredentialSection({
  credentialId,
  onChange,
  disabled,
}: {
  credentialId: string | undefined;
  onChange: (id: string | undefined) => void;
  disabled?: boolean;
}) {
  const { data: credentials } = useCredentials();

  return (
    <div className="space-y-1.5">
      <Select
        value={credentialId || ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        disabled={disabled}
      >
        <option value="">-- None --</option>
        {(credentials ?? []).map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.credential_type})
          </option>
        ))}
      </Select>
      <p className="text-xs text-zinc-500">
        Applied as the device's default credential when the template is applied.
      </p>
    </div>
  );
}

/* ── Section 3: Collector Group ── */

function CollectorGroupSection({
  groupId,
  onChange,
  disabled,
}: {
  groupId: string | undefined;
  onChange: (id: string | undefined) => void;
  disabled?: boolean;
}) {
  const { data: groups } = useCollectorGroups();

  return (
    <div className="space-y-1.5">
      <Select
        value={groupId || ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        disabled={disabled}
      >
        <option value="">-- None (keep existing) --</option>
        {(groups ?? []).map((g) => (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ))}
      </Select>
      <p className="text-xs text-zinc-500">
        Moves devices into this collector group when the template is applied.
      </p>
    </div>
  );
}

/* ── Section 4: Interface Rules ── */

const IF_MATCH_TYPES = [
  { value: "glob", label: "Glob" },
  { value: "regex", label: "Regex" },
  { value: "exact", label: "Exact" },
];
const IF_NUM_OPS = [
  { value: "eq", label: "=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
];
const IF_METRICS = [
  { value: "all", label: "All" },
  { value: "traffic,status", label: "Traffic + Status" },
  { value: "traffic", label: "Traffic" },
  { value: "traffic,errors", label: "Traffic + Errors" },
  { value: "traffic,errors,discards,status", label: "All (explicit)" },
];

function newRule(): InterfaceRule {
  return { name: "", match: { if_alias: { pattern: "*", type: "glob" } }, settings: { polling_enabled: true }, priority: 10 };
}

function InterfaceRulesSection({
  rules,
  onChange,
  disabled,
}: {
  rules: InterfaceRule[];
  onChange: (rules: InterfaceRule[]) => void;
  disabled?: boolean;
}) {
  const add = () => onChange([...rules, newRule()]);
  const update = (i: number, r: InterfaceRule) => { const next = [...rules]; next[i] = r; onChange(next); };
  const remove = (i: number) => onChange(rules.filter((_, idx) => idx !== i));

  return (
    <div className="space-y-2">
      {rules.map((rule, i) => (
        <TemplateInterfaceRuleCard key={i} rule={rule} onChange={(r) => update(i, r)} onRemove={() => remove(i)} disabled={disabled} />
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={add} className="gap-1.5">
        <Plus className="h-3.5 w-3.5" /> Add Rule
      </Button>
    </div>
  );
}

function TemplateInterfaceRuleCard({
  rule,
  onChange,
  onRemove,
  disabled,
}: {
  rule: InterfaceRule;
  onChange: (r: InterfaceRule) => void;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const [expanded, setExpanded] = useState(!rule.name);
  const matchFields = Object.keys(rule.match);
  const hasSpeed = "if_speed_mbps" in rule.match;

  const updateMatch = (field: string, spec: Record<string, unknown>) => {
    onChange({ ...rule, match: { ...rule.match, [field]: spec } });
  };
  const removeMatchField = (field: string) => {
    const next = { ...rule.match };
    delete (next as Record<string, unknown>)[field];
    onChange({ ...rule, match: next });
  };
  const addMatchField = (field: string) => {
    if (field === "if_speed_mbps") {
      onChange({ ...rule, match: { ...rule.match, if_speed_mbps: { op: "gte", value: 1000 } } });
    } else {
      onChange({ ...rule, match: { ...rule.match, [field]: { pattern: "*", type: "glob" } } });
    }
  };

  return (
    <div className="rounded-md border border-zinc-700 p-3 space-y-2">
      {/* Summary row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 cursor-pointer flex-1 min-w-0" onClick={() => setExpanded(!expanded)}>
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />}
          <span className="text-sm text-zinc-200 truncate">{rule.name || "New rule"}</span>
          {!expanded && (
            <span className="text-xs text-zinc-500">
              prio {rule.priority} · {matchFields.length} condition{matchFields.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <button type="button" onClick={onRemove} className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer" title="Remove">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {expanded && (
        <div className="space-y-3 pt-1">
          <div className="grid grid-cols-[1fr_80px] gap-2">
            <div>
              <Label className="text-xs text-zinc-400">Rule Name</Label>
              <Input value={rule.name} onChange={e => onChange({ ...rule, name: e.target.value })} placeholder="e.g. Uplinks - full monitoring" disabled={disabled} />
            </div>
            <div>
              <Label className="text-xs text-zinc-400">Priority</Label>
              <Input type="number" value={rule.priority} onChange={e => onChange({ ...rule, priority: parseInt(e.target.value, 10) || 0 })} min={0} disabled={disabled} />
            </div>
          </div>

          {/* Match */}
          <div className="space-y-1.5 rounded-md border border-zinc-800 p-2">
            <span className="text-xs font-medium text-zinc-400">Match Conditions</span>
            {matchFields.map((field) => {
              const spec = (rule.match as Record<string, Record<string, unknown>>)[field];
              if (field === "if_speed_mbps") {
                return (
                  <div key={field} className="flex items-center gap-1.5">
                    <span className="text-xs text-zinc-400 w-24 shrink-0">{field}</span>
                    <Select value={String(spec.op ?? "gte")} onChange={e => updateMatch(field, { ...spec, op: e.target.value })} disabled={disabled} className="w-16">
                      {IF_NUM_OPS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </Select>
                    <Input type="number" value={spec.value as number ?? 0} onChange={e => updateMatch(field, { ...spec, value: parseInt(e.target.value, 10) || 0 })} className="w-24" disabled={disabled} />
                    <span className="text-[10px] text-zinc-600">Mbps</span>
                    <button type="button" onClick={() => removeMatchField(field)} className="text-zinc-600 hover:text-red-400 cursor-pointer"><X className="h-3 w-3" /></button>
                  </div>
                );
              }
              return (
                <div key={field} className="flex items-center gap-1.5">
                  <span className="text-xs text-zinc-400 w-24 shrink-0">{field}</span>
                  <Select value={String(spec.type ?? "glob")} onChange={e => updateMatch(field, { ...spec, type: e.target.value })} disabled={disabled} className="w-20">
                    {IF_MATCH_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </Select>
                  <Input value={String(spec.pattern ?? "")} onChange={e => updateMatch(field, { ...spec, pattern: e.target.value })} placeholder="Pattern..." disabled={disabled} className="flex-1" />
                  <button type="button" onClick={() => removeMatchField(field)} className="text-zinc-600 hover:text-red-400 cursor-pointer"><X className="h-3 w-3" /></button>
                </div>
              );
            })}
            <div className="flex items-center gap-1 pt-1">
              {["if_alias", "if_name", "if_descr"].filter(f => !(f in rule.match)).map(f => (
                <button key={f} type="button" onClick={() => addMatchField(f)} disabled={disabled}
                  className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors">
                  + {f}
                </button>
              ))}
              {!hasSpeed && (
                <button type="button" onClick={() => addMatchField("if_speed_mbps")} disabled={disabled}
                  className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors">
                  + if_speed_mbps
                </button>
              )}
            </div>
          </div>

          {/* Settings */}
          <div className="space-y-1.5 rounded-md border border-zinc-800 p-2">
            <span className="text-xs font-medium text-zinc-400">Settings to Apply</span>
            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={rule.settings.polling_enabled ?? true}
                  onChange={e => onChange({ ...rule, settings: { ...rule.settings, polling_enabled: e.target.checked } })}
                  disabled={disabled} className="accent-brand-500" />
                <span className="text-zinc-300">Polling</span>
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={rule.settings.alerting_enabled ?? true}
                  onChange={e => onChange({ ...rule, settings: { ...rule.settings, alerting_enabled: e.target.checked } })}
                  disabled={disabled} className="accent-amber-500" />
                <span className="text-zinc-300">Alerting</span>
              </label>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400">Metrics:</span>
                <Select value={rule.settings.poll_metrics ?? "all"}
                  onChange={e => onChange({ ...rule, settings: { ...rule.settings, poll_metrics: e.target.value } })}
                  disabled={disabled} className="w-44">
                  {IF_METRICS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Select>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
