import { useState, useEffect } from "react";
import { Activity, Database, Loader2, Save } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Select } from "@/components/ui/select.tsx";
import { useDevice, useSystemSettings, useUpdateDevice } from "@/api/hooks.ts";

function RetentionOverrideSelect({
  label,
  systemDefault,
  value,
  options,
  onChange,
}: {
  label: string;
  systemDefault: string;
  value: string | undefined;
  options: number[];
  onChange: (v: string | undefined) => void;
}) {
  const isOverridden = value != null && value !== "";
  function fmtDays(d: number): string {
    if (d >= 730) return `${Math.round(d / 365)} years`;
    if (d >= 365) return "1 year";
    return `${d} days`;
  }
  return (
    <div className="space-y-0.5">
      <span className="text-xs text-zinc-600">{label}</span>
      <Select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        className={isOverridden ? "border-brand-500/50" : ""}
      >
        <option value="">
          System default ({fmtDays(Number(systemDefault))})
        </option>
        {options.map((o) => (
          <option key={o} value={String(o)}>
            {fmtDays(o)}
          </option>
        ))}
      </Select>
    </div>
  );
}

function RetentionOverrideTriple({
  rawKey,
  hourlyKey,
  dailyKey,
  overrides,
  systemSettings,
  onChange,
  rawOptions,
  hourlyOptions,
  dailyOptions,
  rawDefault,
  hourlyDefault,
  dailyDefault,
}: {
  rawKey: string;
  hourlyKey: string;
  dailyKey: string;
  overrides: Record<string, string>;
  systemSettings: Record<string, string>;
  onChange: (key: string, value: string | undefined) => void;
  rawOptions: number[];
  hourlyOptions: number[];
  dailyOptions: number[];
  rawDefault: string;
  hourlyDefault: string;
  dailyDefault: string;
}) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <RetentionOverrideSelect
        label="Raw"
        systemDefault={systemSettings[rawKey] ?? rawDefault}
        value={overrides[rawKey]}
        options={rawOptions}
        onChange={(v) => onChange(rawKey, v)}
      />
      <RetentionOverrideSelect
        label="Hourly rollup"
        systemDefault={systemSettings[hourlyKey] ?? hourlyDefault}
        value={overrides[hourlyKey]}
        options={hourlyOptions}
        onChange={(v) => onChange(hourlyKey, v)}
      />
      <RetentionOverrideSelect
        label="Daily rollup"
        systemDefault={systemSettings[dailyKey] ?? dailyDefault}
        value={overrides[dailyKey]}
        options={dailyOptions}
        onChange={(v) => onChange(dailyKey, v)}
      />
    </div>
  );
}

export function RetentionTab({ deviceId }: { deviceId: string }) {
  const { data: device } = useDevice(deviceId);
  const { data: systemSettings } = useSystemSettings();
  const updateDevice = useUpdateDevice();

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [modified, setModified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (device?.retention_overrides) {
      setOverrides(device.retention_overrides);
      setModified(false);
    }
  }, [device]);

  function handleChange(key: string, value: string | undefined) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value == null || value === "") {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
    setModified(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: { retention_overrides: overrides },
      });
      setModified(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  if (!device || !systemSettings) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-400">
          Override system-wide retention for this device. Empty fields inherit
          the system default.
        </p>
        <div className="flex items-center gap-2">
          {saved && <span className="text-sm text-emerald-400">Saved.</span>}
          {modified && (
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Database className="h-4 w-4" /> Interface Data
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="interface_raw_retention_days"
            hourlyKey="interface_hourly_retention_days"
            dailyKey="interface_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[3, 7, 14, 30, 60, 90]}
            hourlyOptions={[30, 60, 90, 180, 365]}
            dailyOptions={[180, 365, 730, 1095, 1825]}
            rawDefault="7"
            hourlyDefault="90"
            dailyDefault="730"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Database className="h-4 w-4" /> Performance Data
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="perf_raw_retention_days"
            hourlyKey="perf_hourly_retention_days"
            dailyKey="perf_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[3, 7, 14, 30, 60, 90]}
            hourlyOptions={[30, 60, 90, 180, 365]}
            dailyOptions={[180, 365, 730, 1095, 1825]}
            rawDefault="7"
            hourlyDefault="90"
            dailyDefault="730"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Activity className="h-4 w-4" /> Availability & Latency
          </CardTitle>
          <p className="text-xs text-zinc-600">
            Ping, port, and HTTP check data. Keep daily rollups for years of
            device health history.
          </p>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="avail_raw_retention_days"
            hourlyKey="avail_hourly_retention_days"
            dailyKey="avail_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[7, 14, 30, 60, 90]}
            hourlyOptions={[90, 180, 365, 730]}
            dailyOptions={[365, 730, 1095, 1825, 2555]}
            rawDefault="30"
            hourlyDefault="365"
            dailyDefault="1825"
          />
        </CardContent>
      </Card>
    </div>
  );
}
