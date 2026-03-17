import { useState } from "react";
import {
  Check,
  CheckCheck,
  Clock,
  Loader2,
  Plus,
  Settings2,
  Trash2,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  useActiveEvents,
  useAcknowledgeEvents,
  useAlertRules,
  useClearEvents,
  useClearedEvents,
  useCreateEventPolicy,
  useDeleteEventPolicy,
  useEventPolicies,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import type { MonitoringEvent, EventPolicy } from "@/types/api.ts";

type Tab = "active" | "cleared" | "policies";

const severityVariant = (severity: string) => {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "emergency":
      return "destructive" as const;
    case "warning":
      return "warning" as const;
    case "info":
      return "info" as const;
    default:
      return "default" as const;
  }
};

export function EventsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { data: activeEvents, isLoading: activeLoading } = useActiveEvents();
  const { data: clearedEvents, isLoading: clearedLoading } = useClearedEvents();
  const { data: policies, isLoading: policiesLoading } = useEventPolicies();

  const isLoading =
    tab === "active" ? activeLoading :
    tab === "cleared" ? clearedLoading :
    policiesLoading;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button
          variant={tab === "active" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("active")}
        >
          <Zap className="h-3.5 w-3.5" />
          Active Events
          {activeEvents && activeEvents.length > 0 && (
            <Badge variant="destructive" className="ml-1.5">
              {activeEvents.length}
            </Badge>
          )}
        </Button>
        <Button
          variant={tab === "cleared" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("cleared")}
        >
          <Clock className="h-3.5 w-3.5" />
          Cleared
        </Button>
        <Button
          variant={tab === "policies" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("policies")}
        >
          <Settings2 className="h-3.5 w-3.5" />
          Policies
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
        </div>
      ) : tab === "active" ? (
        <ActiveEventsTab events={activeEvents ?? []} />
      ) : tab === "cleared" ? (
        <ClearedEventsTab events={clearedEvents ?? []} />
      ) : (
        <PoliciesTab policies={policies ?? []} />
      )}
    </div>
  );
}

function ActiveEventsTab({ events }: { events: MonitoringEvent[] }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ackMut = useAcknowledgeEvents();
  const clearMut = useClearEvents();

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === events.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(events.map((e) => e.id)));
    }
  };

  const handleAck = async () => {
    await ackMut.mutateAsync([...selected]);
    setSelected(new Set());
  };

  const handleClear = async () => {
    await clearMut.mutateAsync([...selected]);
    setSelected(new Set());
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            Active Events ({events.length})
          </CardTitle>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleAck()}
                disabled={ackMut.isPending}
              >
                <Check className="h-3.5 w-3.5" />
                Acknowledge ({selected.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleClear()}
                disabled={clearMut.isPending}
              >
                <CheckCheck className="h-3.5 w-3.5" />
                Clear ({selected.size})
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Zap className="mb-2 h-8 w-8 text-emerald-500/50" />
            <p className="text-sm">No active events</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input
                    type="checkbox"
                    checked={selected.size === events.length && events.length > 0}
                    onChange={toggleAll}
                    className="rounded border-zinc-700"
                  />
                </TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Policy</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Device</TableHead>
                <TableHead>Occurred</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((evt) => (
                <TableRow key={evt.id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={selected.has(evt.id)}
                      onChange={() => toggle(evt.id)}
                      className="rounded border-zinc-700"
                    />
                  </TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(evt.severity)}>
                      {evt.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.source}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm">
                    {evt.policy_name || evt.definition_name}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm max-w-sm truncate">
                    {evt.message}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {evt.device_name || "—"}
                  </TableCell>
                  <TableCell className="text-zinc-500">
                    {evt.occurred_at ? timeAgo(evt.occurred_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function ClearedEventsTab({ events }: { events: MonitoringEvent[] }) {
  const tz = useTimezone();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Cleared Events ({events.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Clock className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No cleared events</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Severity</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Device</TableHead>
                <TableHead>Occurred</TableHead>
                <TableHead>Cleared At</TableHead>
                <TableHead>Cleared By</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((evt) => (
                <TableRow key={evt.id}>
                  <TableCell>
                    <Badge variant={severityVariant(evt.severity)}>
                      {evt.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.source}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm max-w-sm truncate">
                    {evt.message}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {evt.device_name || "—"}
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">
                    {evt.occurred_at ? formatDate(evt.occurred_at, tz) : "—"}
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">
                    {evt.cleared_at ? formatDate(evt.cleared_at, tz) : "—"}
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.cleared_by || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function PoliciesTab({ policies }: { policies: EventPolicy[] }) {
  const [showCreate, setShowCreate] = useState(false);
  const deleteMut = useDeleteEventPolicy();

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Settings2 className="h-4 w-4" />
              Event Policies ({policies.length})
            </CardTitle>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="h-3.5 w-3.5" />
              Create Policy
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {policies.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Settings2 className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No event policies configured</p>
              <p className="text-xs text-zinc-600 mt-1">
                Create a policy to promote alerts to events
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Alert Definition</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Threshold</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Auto-clear</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {policies.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium text-zinc-100">
                      {p.name}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {p.definition_name || p.definition_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="default">
                        {p.mode}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {p.mode === "consecutive"
                        ? `${p.fire_count_threshold} consecutive`
                        : `${p.fire_count_threshold} of ${p.window_size}`}
                    </TableCell>
                    <TableCell>
                      <Badge variant={severityVariant(p.event_severity)}>
                        {p.event_severity}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.auto_clear_on_resolve ? "success" : "default"}>
                        {p.auto_clear_on_resolve ? "Yes" : "No"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.enabled ? "success" : "default"}>
                        {p.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-zinc-500 hover:text-red-400"
                        onClick={() => deleteMut.mutate(p.id)}
                        disabled={deleteMut.isPending}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {showCreate && (
        <CreatePolicyDialog onClose={() => setShowCreate(false)} />
      )}
    </>
  );
}

function CreatePolicyDialog({ onClose }: { onClose: () => void }) {
  const { data: definitions } = useAlertRules();
  const createMut = useCreateEventPolicy();

  const [name, setName] = useState("");
  const [definitionId, setDefinitionId] = useState("");
  const [mode, setMode] = useState("consecutive");
  const [threshold, setThreshold] = useState(3);
  const [windowSize, setWindowSize] = useState(5);
  const [severity, setSeverity] = useState("warning");
  const [messageTemplate, setMessageTemplate] = useState("");
  const [autoClear, setAutoClear] = useState(true);

  const handleSubmit = async () => {
    if (!name || !definitionId) return;
    await createMut.mutateAsync({
      name,
      definition_id: definitionId,
      mode,
      fire_count_threshold: threshold,
      window_size: windowSize,
      event_severity: severity,
      message_template: messageTemplate || undefined,
      auto_clear_on_resolve: autoClear,
    });
    onClose();
  };

  return (
    <Dialog open onClose={onClose} title="Create Event Policy">
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Interface Util Sustained" />
        </div>

        <div className="space-y-1.5">
          <Label>Alert Definition</Label>
          <Select value={definitionId} onChange={(e) => setDefinitionId(e.target.value)}>
            <option value="">Select alert definition</option>
            {(definitions ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <Select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="consecutive">Consecutive</option>
              <option value="cumulative">Cumulative</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Severity</Label>
            <Select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Fire Count Threshold</Label>
            <Input
              type="number"
              min={1}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </div>
          {mode === "cumulative" && (
            <div className="space-y-1.5">
              <Label>Window Size</Label>
              <Input
                type="number"
                min={1}
                value={windowSize}
                onChange={(e) => setWindowSize(Number(e.target.value))}
              />
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <Label>Message Template (optional)</Label>
          <Input
            value={messageTemplate}
            onChange={(e) => setMessageTemplate(e.target.value)}
            placeholder="{rule_name}: {value} on {device_name} [{fire_count}x]"
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="auto-clear"
            checked={autoClear}
            onChange={(e) => setAutoClear(e.target.checked)}
            className="rounded border-zinc-700"
          />
          <Label htmlFor="auto-clear">Auto-clear on resolve</Label>
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={() => void handleSubmit()}
          disabled={!name || !definitionId || createMut.isPending}
        >
          {createMut.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Create
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
