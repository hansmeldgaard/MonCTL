import { useState } from "react";
import { Bell, Loader2, Save, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useCreateThresholdOverride,
  useDeleteThresholdOverride,
  useDeviceThresholds,
  useUpdateThresholdOverride,
} from "@/api/hooks.ts";
import type { DeviceThresholdRow } from "@/types/api.ts";

function formatDeviceThresholdValue(
  value: number | null | undefined,
  unit: string | null,
): string {
  if (value == null) return "\u2014";
  if (unit === "percent") return `${value}%`;
  if (unit === "ms") return `${value} ms`;
  if (unit === "seconds") return `${value}s`;
  if (unit === "dBm") return `${value} dBm`;
  if (unit === "pps") return `${value} pps`;
  if (unit === "bps") {
    if (value >= 1_000_000_000)
      return `${(value / 1_000_000_000).toFixed(1)} Gbps`;
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} Mbps`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)} kbps`;
    return `${value} bps`;
  }
  if (unit === "bytes") {
    if (value >= 1_073_741_824)
      return `${(value / 1_073_741_824).toFixed(1)} GB`;
    if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MB`;
    if (value >= 1_024) return `${(value / 1_024).toFixed(1)} KB`;
    return `${value} B`;
  }
  if (unit) return `${value} ${unit}`;
  return String(value);
}

function ThresholdRow({
  row,
  onSaveOverride,
  onDeleteOverride,
}: {
  row: DeviceThresholdRow;
  onSaveOverride: (varId: string, value: number, existingId?: string) => void;
  onDeleteOverride: (id: string) => void;
}) {
  const [editValue, setEditValue] = useState<string>("");
  const [editing, setEditing] = useState(false);

  const handleSave = () => {
    const val = parseFloat(editValue);
    if (isNaN(val) || !isFinite(val)) return;
    onSaveOverride(row.variable_id, val, row.device_override_id ?? undefined);
    setEditing(false);
  };

  const effectiveSource =
    row.device_value != null
      ? "device"
      : row.app_value != null
        ? "app"
        : "default";

  return (
    <TableRow>
      <TableCell className="font-medium text-zinc-100">
        {row.display_name || row.name}
      </TableCell>
      <TableCell className="text-zinc-400 font-mono text-sm">
        {formatDeviceThresholdValue(row.expression_default, row.unit)}
      </TableCell>
      <TableCell className="text-zinc-400 font-mono text-sm">
        {row.app_value != null ? (
          <span className="text-blue-400">
            {formatDeviceThresholdValue(row.app_value, row.unit)}
          </span>
        ) : (
          "\u2014"
        )}
      </TableCell>
      <TableCell>
        {editing ? (
          <div className="flex items-center gap-1">
            <Input
              className="w-20 h-7 text-xs"
              type="number"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSave();
                if (e.key === "Escape") setEditing(false);
              }}
              autoFocus
            />
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-1"
              onClick={handleSave}
            >
              <Save className="h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-1"
              onClick={() => setEditing(false)}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <span
              className={`text-sm cursor-pointer hover:text-brand-400 ${row.device_value != null ? "text-brand-400 font-medium" : "text-zinc-500"}`}
              onClick={() => {
                setEditValue(String(row.device_value ?? row.effective_value));
                setEditing(true);
              }}
            >
              {row.device_value != null
                ? formatDeviceThresholdValue(row.device_value, row.unit)
                : "\u2014"}
            </span>
            {row.device_override_id && (
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-1 text-zinc-500 hover:text-red-400"
                onClick={() => onDeleteOverride(row.device_override_id!)}
              >
                <X className="h-3 w-3" />
              </Button>
            )}
          </div>
        )}
      </TableCell>
      <TableCell>
        <span
          className={
            effectiveSource !== "default"
              ? "font-mono text-sm text-brand-400 font-medium"
              : "font-mono text-sm text-zinc-300"
          }
        >
          {formatDeviceThresholdValue(row.effective_value, row.unit)}
        </span>
        {effectiveSource === "device" && (
          <span className="ml-1.5 text-xs text-zinc-500">
            (device override)
          </span>
        )}
        {effectiveSource === "app" && (
          <span className="ml-1.5 text-xs text-zinc-500">(app value)</span>
        )}
      </TableCell>
    </TableRow>
  );
}

export function ThresholdsTab({ deviceId }: { deviceId: string }) {
  const { data: thresholds, isLoading } = useDeviceThresholds(deviceId);
  const createOverride = useCreateThresholdOverride();
  const updateOverride = useUpdateThresholdOverride();
  const deleteOverride = useDeleteThresholdOverride();

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!thresholds || thresholds.length === 0) {
    return (
      <Card>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No threshold variables for this device</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const grouped = thresholds.reduce<Record<string, DeviceThresholdRow[]>>(
    (acc, row) => {
      const key = row.app_name || "Unknown";
      if (!acc[key]) acc[key] = [];
      acc[key].push(row);
      return acc;
    },
    {},
  );

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([appName, rows]) => (
        <Card key={appName}>
          <CardHeader>
            <CardTitle className="text-sm">{appName}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Threshold</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead>App Value</TableHead>
                  <TableHead>Device Override</TableHead>
                  <TableHead>Effective</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <ThresholdRow
                    key={row.variable_id}
                    row={row}
                    onSaveOverride={(varId, value, existingId) => {
                      if (existingId) {
                        updateOverride.mutate({ id: existingId, value });
                      } else {
                        createOverride.mutate({
                          variable_id: varId,
                          device_id: deviceId,
                          value,
                        });
                      }
                    }}
                    onDeleteOverride={(id) => deleteOverride.mutate(id)}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
