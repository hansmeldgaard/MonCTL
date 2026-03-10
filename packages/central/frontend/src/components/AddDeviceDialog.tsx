import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { useCreateDevice, useCollectorGroups, useCredentials, useDeviceTypes, useTenants } from "@/api/hooks.ts";

interface AddDeviceDialogProps {
  open: boolean;
  onClose: () => void;
}

export function AddDeviceDialog({ open, onClose }: AddDeviceDialogProps) {
  const { data: deviceTypes } = useDeviceTypes();
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: credentials } = useCredentials();
  const createDevice = useCreateDevice();

  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [deviceType, setDeviceType] = useState("host");
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName("");
    setAddress("");
    setDeviceType("host");
    setTenantId("");
    setCollectorGroupId("");
    setCredentialId("");
    setError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim() || !address.trim()) {
      setError("Name and address are required.");
      return;
    }

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
        name: name.trim(),
        address: address.trim(),
        device_type: deviceType,
        tenant_id: tenantId || undefined,
        collector_group_id: collectorGroupId || undefined,
        default_credential_id: credentialId || undefined,
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
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>

        {/* Address */}
        <div className="space-y-1.5">
          <Label htmlFor="device-address">Address</Label>
          <Input
            id="device-address"
            placeholder="IP, hostname, or URL"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </div>

        {/* Device Type */}
        <div className="space-y-1.5">
          <Label htmlFor="device-type">Device Type</Label>
          <Select
            id="device-type"
            value={deviceType}
            onChange={(e) => setDeviceType(e.target.value)}
          >
            {deviceTypes && deviceTypes.length > 0
              ? deviceTypes.map((dt) => (
                  <option key={dt.id} value={dt.name}>
                    {dt.name}
                    {dt.description ? ` — ${dt.description}` : ""}
                  </option>
                ))
              : (
                  <>
                    <option value="host">host</option>
                    <option value="network">network</option>
                    <option value="api">api</option>
                    <option value="database">database</option>
                    <option value="service">service</option>
                  </>
                )}
          </Select>
        </div>

        {/* Tenant */}
        <div className="space-y-1.5">
          <Label htmlFor="device-tenant">Tenant</Label>
          <Select
            id="device-tenant"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          >
            <option value="">— Select tenant —</option>
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
            <option value="">— Select collector group —</option>
            {(collectorGroups ?? []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
        </div>

        {/* Default Credential (only if credentials exist) */}
        {credentials && credentials.length > 0 && (
          <div className="space-y-1.5">
            <Label htmlFor="device-credential">
              Default Credential <span className="text-zinc-500 font-normal">(optional)</span>
            </Label>
            <Select
              id="device-credential"
              value={credentialId}
              onChange={(e) => setCredentialId(e.target.value)}
            >
              <option value="">— No credential —</option>
              {credentials.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>
        )}

        {/* Error */}
        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}

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
