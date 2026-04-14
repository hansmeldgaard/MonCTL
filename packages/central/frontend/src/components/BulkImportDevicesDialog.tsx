import { useState, useMemo } from "react";
import { Key, Loader2, X } from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { LabelEditor } from "@/components/LabelEditor.tsx";
import {
  useBulkImportDevices,
  useCollectorGroups,
  useCredentials,
  useTenants,
} from "@/api/hooks.ts";
import { ApiError } from "@/api/client.ts";
import type { DuplicateCandidate } from "@/types/api.ts";

type DuplicateRow = { address: string; candidates: DuplicateCandidate[] };

const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const IPV6_RE = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/;

function parseAddresses(raw: string): { valid: string[]; invalid: string[] } {
  const tokens = raw
    .split(/[\n,;\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const t of tokens) {
    if (seen.has(t)) continue;
    seen.add(t);
    if (
      (IPV4_RE.test(t) &&
        t
          .split(".")
          .map(Number)
          .every((n) => n <= 255)) ||
      IPV6_RE.test(t)
    ) {
      valid.push(t);
    } else {
      invalid.push(t);
    }
  }
  return { valid, invalid };
}

function formatCredentialType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

interface BulkImportDevicesDialogProps {
  open: boolean;
  onClose: () => void;
}

export function BulkImportDevicesDialog({
  open,
  onClose,
}: BulkImportDevicesDialogProps) {
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: credentials } = useCredentials();
  const bulkImport = useBulkImportDevices();

  const [rawInput, setRawInput] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [deviceCreds, setDeviceCreds] = useState<Record<string, string>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    created: number;
    discovery_queued: number;
    skipped: number;
  } | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateRow[] | null>(null);

  const parsed = useMemo(() => parseAddresses(rawInput), [rawInput]);

  const credsByType = useMemo(() => {
    const map: Record<string, typeof credentials> = {};
    for (const c of credentials ?? []) {
      (map[c.credential_type] ??= []).push(c);
    }
    return map;
  }, [credentials]);

  const availableTypes = useMemo(
    () => Object.keys(credsByType).filter((t) => !(t in deviceCreds)),
    [credsByType, deviceCreds],
  );

  function reset() {
    setRawInput("");
    setTenantId("");
    setCollectorGroupId("");
    setDeviceCreds({});
    setLabels({});
    setError(null);
    setResult(null);
    setDuplicates(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (parsed.valid.length === 0) {
      setError("Enter at least one valid IP address.");
      return;
    }
    if (parsed.invalid.length > 0) {
      const preview = parsed.invalid.slice(0, 5).join(", ");
      const extra =
        parsed.invalid.length > 5 ? ` +${parsed.invalid.length - 5} more` : "";
      setError(
        `Fix ${parsed.invalid.length} invalid address(es) before importing: ${preview}${extra}`,
      );
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

    await submit(false);
  }

  async function submit(force: boolean) {
    setError(null);
    const cleanCreds = Object.fromEntries(
      Object.entries(deviceCreds).filter(([, v]) => v !== ""),
    );
    try {
      const resp = await bulkImport.mutateAsync({
        addresses: parsed.valid,
        tenant_id: tenantId,
        collector_group_id: collectorGroupId,
        credentials: cleanCreds,
        labels: Object.keys(labels).length > 0 ? labels : undefined,
        force: force || undefined,
      });
      setDuplicates(null);
      setResult({
        created: resp.data.created,
        discovery_queued: resp.data.discovery_queued,
        skipped: resp.data.skipped_duplicates?.length ?? 0,
      });
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.detail &&
        typeof err.detail === "object" &&
        (err.detail as { code?: string }).code === "duplicate_candidate"
      ) {
        const dups =
          (err.detail as { duplicates?: DuplicateRow[] }).duplicates ?? [];
        setDuplicates(dups);
        return;
      }
      setError(err instanceof Error ? err.message : "Import failed");
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Import Devices">
      {result ? (
        <div className="py-2 space-y-4">
          <p className="text-sm text-zinc-300">
            <span className="text-green-400 font-semibold">
              {result.created}
            </span>{" "}
            device
            {result.created !== 1 ? "s" : ""} created.
            {result.skipped > 0 && (
              <span className="text-amber-400 ml-1">
                {result.skipped} duplicate{result.skipped !== 1 ? "s" : ""}{" "}
                skipped.
              </span>
            )}
            {result.discovery_queued > 0 && (
              <span className="text-zinc-400 ml-1">
                SNMP discovery queued for {result.discovery_queued} — names will
                update automatically once discovery completes.
              </span>
            )}
          </p>
          <DialogFooter>
            <Button onClick={handleClose}>Done</Button>
          </DialogFooter>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* IP textarea */}
          <div className="space-y-1.5">
            <Label htmlFor="bulk-ips">
              IP Addresses
              <span className="text-zinc-500 font-normal ml-1">
                (one per line, or comma / space separated)
              </span>
            </Label>
            <textarea
              id="bulk-ips"
              className="w-full min-h-[120px] rounded-md border border-zinc-700 bg-zinc-800
                         px-3 py-2 text-sm text-zinc-100 font-mono placeholder:text-zinc-600
                         focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y"
              placeholder={"192.168.1.1\n10.0.0.1\n172.16.0.1"}
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              autoFocus
            />
            {rawInput.trim() && (
              <div className="flex gap-3 text-xs">
                {parsed.valid.length > 0 && (
                  <span className="text-green-400">
                    {parsed.valid.length} valid
                  </span>
                )}
                {parsed.invalid.length > 0 && (
                  <span className="text-red-400">
                    {parsed.invalid.length} invalid:{" "}
                    {parsed.invalid.slice(0, 5).join(", ")}
                    {parsed.invalid.length > 5
                      ? ` +${parsed.invalid.length - 5} more`
                      : ""}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Tenant */}
          <div className="space-y-1.5">
            <Label htmlFor="import-tenant">Tenant</Label>
            <Select
              id="import-tenant"
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
            <Label htmlFor="import-cgroup">Collector Group</Label>
            <Select
              id="import-cgroup"
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

          {/* Credentials */}
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
              Labels{" "}
              <span className="text-zinc-500 font-normal">(optional)</span>
            </Label>
            <LabelEditor labels={labels} onChange={setLabels} />
          </div>

          {/* Error */}
          {error && <p className="text-sm text-red-400">{error}</p>}

          {/* Duplicates warning */}
          {duplicates && duplicates.length > 0 && (
            <div className="rounded border border-amber-600/40 bg-amber-950/30 p-3 space-y-2">
              <p className="text-sm text-amber-300">
                {duplicates.length} of {parsed.valid.length} address
                {parsed.valid.length !== 1 ? "es" : ""} already exist in this
                tenant:
              </p>
              <ul className="text-xs text-amber-200 space-y-0.5 max-h-40 overflow-y-auto font-mono">
                {duplicates.map((d) => (
                  <li key={d.address}>
                    {d.address}
                    {d.candidates[0] ? ` — ${d.candidates[0].name}` : ""}
                  </li>
                ))}
              </ul>
              <p className="text-xs text-zinc-400">
                Click "Import anyway" to create the non-duplicate addresses only
                (the {duplicates.length} listed above will be skipped).
              </p>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={handleClose}>
              Cancel
            </Button>
            {duplicates && duplicates.length > 0 ? (
              <Button
                type="button"
                variant="destructive"
                disabled={bulkImport.isPending}
                onClick={() => submit(true)}
              >
                {bulkImport.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Import anyway ({parsed.valid.length - duplicates.length} new)
              </Button>
            ) : (
              <Button type="submit" disabled={bulkImport.isPending}>
                {bulkImport.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Import{" "}
                {parsed.valid.length > 0
                  ? `${parsed.valid.length} Device${parsed.valid.length !== 1 ? "s" : ""}`
                  : "Devices"}
              </Button>
            )}
          </DialogFooter>
        </form>
      )}
    </Dialog>
  );
}
