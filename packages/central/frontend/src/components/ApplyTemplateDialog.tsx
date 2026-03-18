import { useState } from "react";
import { FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { useTemplates, useApplyTemplate } from "@/api/hooks.ts";
import type { Template } from "@/types/api.ts";

interface Props {
  open: boolean;
  onClose: () => void;
  deviceIds: string[];
  deviceName?: string;
}

export function ApplyTemplateDialog({ open, onClose, deviceIds, deviceName }: Props) {
  const { data: templates } = useTemplates();
  const applyTemplate = useApplyTemplate();

  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedTemplate = templates?.find((t: Template) => t.id === selectedTemplateId);
  const apps = selectedTemplate?.config?.apps ?? [];

  function handleClose() {
    setSelectedTemplateId("");
    setResult(null);
    setError(null);
    onClose();
  }

  async function handleApply() {
    if (!selectedTemplateId || deviceIds.length === 0) return;
    setError(null);
    setResult(null);

    try {
      const res = await applyTemplate.mutateAsync({
        templateId: selectedTemplateId,
        deviceIds,
      });
      const count = (res as { data?: { applied?: number } })?.data?.applied ?? deviceIds.length;
      setResult(`Template applied to ${count} device${count !== 1 ? "s" : ""}.`);
      setTimeout(handleClose, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply template");
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Apply Template">
      <div className="space-y-4">
        {deviceName && (
          <p className="text-sm text-zinc-400">
            Apply a template to <span className="font-medium text-zinc-200">{deviceName}</span>
          </p>
        )}
        {!deviceName && deviceIds.length > 1 && (
          <p className="text-sm text-zinc-400">
            Apply a template to <span className="font-medium text-zinc-200">{deviceIds.length} devices</span>
          </p>
        )}

        <div className="space-y-1.5">
          <Label>Template</Label>
          <Select
            value={selectedTemplateId}
            onChange={(e) => setSelectedTemplateId(e.target.value)}
          >
            <option value="">Select a template...</option>
            {(templates ?? []).map((t: Template) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </Select>
        </div>

        {selectedTemplate && apps.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-xs text-zinc-500">Apps to be assigned</Label>
            <div className="rounded-md border border-zinc-700 bg-zinc-800/50 p-3 space-y-1.5">
              {apps.map((app: { app_id?: string; app_name?: string; role?: string; schedule_value?: string }, idx: number) => (
                <div key={idx} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-zinc-200">{app.app_name ?? app.app_id ?? "unknown"}</span>
                  <div className="flex items-center gap-2">
                    {app.role && <Badge variant="info" className="text-[10px]">{app.role}</Badge>}
                    {app.schedule_value && (
                      <span className="text-xs text-zinc-500">{app.schedule_value}s</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {selectedTemplate && apps.length === 0 && (
          <p className="text-sm text-zinc-500 italic">This template has no apps configured.</p>
        )}

        {error && <p className="text-sm text-red-400">{error}</p>}
        {result && <p className="text-sm text-emerald-400">{result}</p>}
      </div>

      <DialogFooter>
        <Button variant="secondary" onClick={handleClose}>Cancel</Button>
        <Button
          onClick={handleApply}
          disabled={!selectedTemplateId || apps.length === 0 || applyTemplate.isPending}
        >
          {applyTemplate.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
          ) : (
            <FileText className="h-4 w-4 mr-1.5" />
          )}
          Apply
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
