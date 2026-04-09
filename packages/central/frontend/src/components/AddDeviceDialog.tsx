import { useState, useMemo } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateAddress } from "@/lib/validation.ts";
import { Key, Loader2, X } from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { SearchableSelect } from "@/components/ui/searchable-select.tsx";
import {
  useCreateDevice,
  useCollectorGroups,
  useCredentials,
  useDeviceTypes,
  useTenants,
} from "@/api/hooks.ts";
import { LabelEditor } from "@/components/LabelEditor.tsx";

function formatCredentialType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

interface AddDeviceDialogProps {
  open: boolean;
  onClose: () => void;
}

export function AddDeviceDialog({ open, onClose }: AddDeviceDialogProps) {
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: credentials } = useCredentials();
  const { data: deviceTypesResp } = useDeviceTypes({ limit: 500 });
  const createDevice = useCreateDevice();

  const deviceTypes = deviceTypesResp?.data ?? [];

  const nameField = useField("", validateName);
  const addressField = useField("", validateAddress);
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [deviceTypeId, setDeviceTypeId] = useState("");
  const [deviceCreds, setDeviceCreds] = useState<Record<string, string>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const credsByType = useMemo(() => {
    const map: Record<string, typeof credentials> = {};
    for (const c of credentials ?? []) {
      (map[c.credential_type] ??= []).push(c);
    }
    return map;
  }, [credentials]);

  const availableTypes = useMemo(() => {
    return Object.keys(credsByType).filter((t) => !(t in deviceCreds));
  }, [credsByType, deviceCreds]);

  function reset() {
    nameField.reset();
    addressField.reset();
    setTenantId("");
    setCollectorGroupId("");
    setDeviceTypeId("");
    setDeviceCreds({});
    setLabels({});
    setError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!validateAll(nameField, addressField)) return;

    if (!tenantId) {
      setError("Tenant is required.");
      return;
    }

    if (!collectorGroupId) {
      setError("Collector Group is required.");
      return;
    }

    try {
      await createDevice.mutateAsync({
        name: nameField.value.trim(),
        address: addressField.value.trim(),
        tenant_id: tenantId || undefined,
        collector_group_id: collectorGroupId || undefined,
        device_type_id: deviceTypeId || undefined,
        credentials: deviceCreds,
        labels: Object.keys(labels).length > 0 ? labels : undefined,
      });
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create device");
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Add Device">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Name */}
        <div className="space-y-1.5">
          <Label htmlFor="device-name">Name</Label>
          <Input
            id="device-name"
            placeholder="e.g. prod-web-01"
            value={nameField.value}
            onChange={nameField.onChange}
            onBlur={nameField.onBlur}
            autoFocus
          />
          {nameField.error && (
            <p className="text-xs text-red-400 mt-0.5">{nameField.error}</p>
          )}
        </div>

        {/* Address */}
        <div className="space-y-1.5">
          <Label htmlFor="device-address">Address</Label>
          <Input
            id="device-address"
            placeholder="IP, hostname, or URL"
            value={addressField.value}
            onChange={addressField.onChange}
            onBlur={addressField.onBlur}
          />
          {addressField.error && (
            <p className="text-xs text-red-400 mt-0.5">{addressField.error}</p>
          )}
        </div>

        {/* Tenant */}
        <div className="space-y-1.5">
          <Label htmlFor="device-tenant">Tenant</Label>
          <Select
            id="device-tenant"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          >
            <option value="">
              {"\u2014"} Select tenant {"\u2014"}
            </option>
            {(tenants ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
        </div>

        {/* Collector Group */}
        <div className="space-y-1.5">
          <Label htmlFor="device-cgroup">Collector Group</Label>
          <Select
            id="device-cgroup"
            value={collectorGroupId}
            onChange={(e) => setCollectorGroupId(e.target.value)}
          >
            <option value="">
              {"\u2014"} Select collector group {"\u2014"}
            </option>
            {(collectorGroups ?? []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
        </div>

        {/* Device Type */}
        <div className="space-y-1.5">
          <Label htmlFor="device-type">
            Device Type{" "}
            <span className="text-zinc-500 font-normal">(optional)</span>
          </Label>
          <SearchableSelect
            id="device-type"
            value={deviceTypeId}
            onChange={setDeviceTypeId}
            options={[
              { value: "", label: "Auto-detect via SNMP" },
              ...deviceTypes.map((dt) => ({
                value: dt.id,
                label:
                  dt.name +
                  (dt.vendor
                    ? ` (${dt.vendor}${dt.model ? ` ${dt.model}` : ""})`
                    : ""),
              })),
            ]}
            placeholder="Auto-detect via SNMP"
          />
        </div>

        {/* Default Credentials */}
        {credentials && credentials.length > 0 && (
          <div className="space-y-1.5">
            <Label className="flex items-center gap-1.5">
              <Key className="h-3.5 w-3.5" />
              Default Credentials{" "}
              <span className="text-zinc-500 font-normal">(optional)</span>
            </Label>
            <div className="space-y-2">
              {Object.entries(deviceCreds).map(([ctype, credId]) => (
                <div key={ctype} className="flex items-center gap-2">
                  <Badge
                    variant="default"
                    className="text-xs min-w-[110px] justify-center"
                  >
                    {formatCredentialType(ctype)}
                  </Badge>
                  <Select
                    className="flex-1"
                    value={credId}
                    onChange={(e) =>
                      setDeviceCreds((prev) => ({
                        ...prev,
                        [ctype]: e.target.value,
                      }))
                    }
                  >
                    <option value="">-- Select --</option>
                    {(credsByType[ctype] ?? []).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-zinc-500 hover:text-red-400"
                    onClick={() =>
                      setDeviceCreds((prev) => {
                        const next = { ...prev };
                        delete next[ctype];
                        return next;
                      })
                    }
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
              {availableTypes.length > 0 && (
                <Select
                  className="max-w-xs text-zinc-500"
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      setDeviceCreds((prev) => ({
                        ...prev,
                        [e.target.value]: "",
                      }));
                    }
                  }}
                >
                  <option value="">+ Add credential...</option>
                  {availableTypes.map((t) => (
                    <option key={t} value={t}>
                      {formatCredentialType(t)}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          </div>
        )}

        {/* Labels */}
        <div className="space-y-1.5">
          <Label>
            Labels <span className="text-zinc-500 font-normal">(optional)</span>
          </Label>
          <LabelEditor labels={labels} onChange={setLabels} />
        </div>

        {/* Error */}
        {error && <p className="text-sm text-red-400">{error}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createDevice.isPending}>
            {createDevice.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Add Device
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
