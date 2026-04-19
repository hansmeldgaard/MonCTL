import { useState, useMemo } from "react";
import {
  Loader2,
  Bug,
  Copy,
  Check,
  AlertTriangle,
  PlayCircle,
} from "lucide-react";
import { Dialog } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { useDebugRun } from "@/api/hooks.ts";
import type { DebugLogRecord, DebugRunBundle } from "@/types/api.ts";

interface Props {
  open: boolean;
  onClose: () => void;
  deviceId: string;
  assignmentId: string;
  appName: string;
  deviceName: string;
}

type TabKey = "logs" | "stdout" | "stderr" | "traceback" | "metrics" | "config";

const TABS: { key: TabKey; label: string }[] = [
  { key: "logs", label: "Logs" },
  { key: "stdout", label: "stdout" },
  { key: "stderr", label: "stderr" },
  { key: "traceback", label: "Traceback" },
  { key: "metrics", label: "Metrics" },
  { key: "config", label: "Config" },
];

export function DebugRunDialog({
  open,
  onClose,
  deviceId,
  assignmentId,
  appName,
  deviceName,
}: Props) {
  const mutation = useDebugRun();
  const [tab, setTab] = useState<TabKey>("logs");

  const bundle: DebugRunBundle | undefined = mutation.data?.data;

  const handleRun = () => {
    setTab("logs");
    mutation.reset();
    mutation.mutate({ deviceId, assignmentId });
  };

  const handleClose = () => {
    mutation.reset();
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title={`Debug Run — ${appName}`}
      size="full"
      className="!max-w-[min(95vw,1600px)] h-[85vh]"
    >
      {!bundle && !mutation.isPending && !mutation.isError && (
        <IdleView appName={appName} deviceName={deviceName} onRun={handleRun} />
      )}

      {mutation.isPending && <RunningView deviceName={deviceName} />}

      {mutation.isError && (
        <ErrorView
          message={(mutation.error as Error)?.message ?? "Debug run failed"}
          onRetry={handleRun}
        />
      )}

      {bundle && !mutation.isPending && (
        <BundleView
          bundle={bundle}
          tab={tab}
          onTabChange={setTab}
          onRerun={handleRun}
        />
      )}
    </Dialog>
  );
}

function IdleView({
  appName,
  deviceName,
  onRun,
}: {
  appName: string;
  deviceName: string;
  onRun: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <Bug className="h-5 w-5 text-brand-400 mt-0.5 shrink-0" />
        <div className="text-sm text-zinc-400">
          Runs <span className="text-zinc-200 font-mono">{appName}</span> once
          against <span className="text-zinc-200 font-mono">{deviceName}</span>{" "}
          on its assigned collector and returns a full diagnostic bundle — logs,
          stdout, stderr, traceback, metrics. The result is{" "}
          <span className="text-zinc-300">not</span> submitted to monitoring
          history.
        </div>
      </div>
      <div className="flex justify-end pt-2 border-t border-zinc-800">
        <Button onClick={onRun}>
          <PlayCircle className="h-4 w-4" />
          Start debug run
        </Button>
      </div>
    </div>
  );
}

function RunningView({ deviceName }: { deviceName: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-sm text-zinc-400">
      <Loader2 className="h-6 w-6 animate-spin text-brand-400" />
      <div>Running debug poll against {deviceName}…</div>
      <div className="text-xs text-zinc-600">
        This may take up to the assignment's configured timeout.
      </div>
    </div>
  );
}

function ErrorView({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3 rounded-md border border-red-900/50 bg-red-950/30 p-3">
        <AlertTriangle className="h-5 w-5 text-red-400 mt-0.5 shrink-0" />
        <div className="text-sm text-red-200">{message}</div>
      </div>
      <div className="flex justify-end">
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      </div>
    </div>
  );
}

function BundleView({
  bundle,
  tab,
  onTabChange,
  onRerun,
}: {
  bundle: DebugRunBundle;
  tab: TabKey;
  onTabChange: (k: TabKey) => void;
  onRerun: () => void;
}) {
  const resultStatus = bundle.result?.status ?? "unknown";
  const errorCategory = bundle.result?.error_category ?? "";
  const execMs = bundle.result?.execution_time_ms ?? 0;

  const statusColor =
    bundle.success || resultStatus === "ok"
      ? "bg-emerald-900/40 text-emerald-300 border-emerald-800/60"
      : "bg-red-900/40 text-red-300 border-red-800/60";

  return (
    <div className="space-y-3">
      {/* Header strip */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={`px-2 py-0.5 rounded border font-medium uppercase tracking-wide ${statusColor}`}
        >
          {bundle.success ? "ok" : resultStatus}
        </span>
        {bundle.fail_phase && (
          <span className="px-2 py-0.5 rounded border border-red-800/60 bg-red-950/40 text-red-300 font-medium">
            fail phase: {bundle.fail_phase}
          </span>
        )}
        {errorCategory && (
          <span className="px-2 py-0.5 rounded border border-zinc-700 bg-zinc-800 text-zinc-300">
            category: {errorCategory}
          </span>
        )}
        <span className="text-zinc-500">
          exec {execMs} ms · total {bundle.duration_ms} ms
        </span>
        <span className="text-zinc-600">
          · {bundle.logs?.length ?? 0} log records
        </span>
        <div className="ml-auto">
          <Button size="sm" variant="secondary" onClick={onRerun}>
            Run again
          </Button>
        </div>
      </div>

      {bundle.result?.error_message && (
        <div className="rounded-md border border-red-900/50 bg-red-950/30 p-3 text-xs font-mono text-red-200 whitespace-pre-wrap break-all">
          {bundle.result.error_message}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-zinc-800">
        {TABS.map((t) => {
          const count = tabCount(bundle, t.key);
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              onClick={() => onTabChange(t.key)}
              className={`px-3 py-1.5 text-xs rounded-t transition-colors cursor-pointer border-b-2 ${
                active
                  ? "text-zinc-100 border-brand-500"
                  : "text-zinc-500 hover:text-zinc-300 border-transparent"
              }`}
            >
              {t.label}
              {count !== undefined && (
                <span
                  className={`ml-1.5 text-[10px] ${active ? "text-brand-400" : "text-zinc-600"}`}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
        <div className="ml-auto pb-1">
          <CopyButton value={tabContent(bundle, tab)} />
        </div>
      </div>

      {/* Tab body */}
      <div>
        {tab === "logs" && <LogsPane logs={bundle.logs ?? []} />}
        {tab === "stdout" && <TextPane text={bundle.stdout ?? ""} />}
        {tab === "stderr" && <TextPane text={bundle.stderr ?? ""} />}
        {tab === "traceback" && <TextPane text={bundle.traceback ?? ""} />}
        {tab === "metrics" && (
          <TextPane
            text={
              bundle.result?.metrics
                ? JSON.stringify(bundle.result.metrics, null, 2)
                : ""
            }
          />
        )}
        {tab === "config" && (
          <TextPane
            text={
              bundle.result?.config_data
                ? JSON.stringify(bundle.result.config_data, null, 2)
                : ""
            }
          />
        )}
      </div>
    </div>
  );
}

function tabCount(bundle: DebugRunBundle, key: TabKey): number | undefined {
  switch (key) {
    case "logs":
      return bundle.logs?.length ?? 0;
    case "stdout":
      return bundle.stdout?.length ?? 0;
    case "stderr":
      return bundle.stderr?.length ?? 0;
    case "metrics":
      return bundle.result?.metrics?.length ?? 0;
    default:
      return undefined;
  }
}

function tabContent(bundle: DebugRunBundle, key: TabKey): string {
  switch (key) {
    case "logs":
      return (bundle.logs ?? []).map((r) => formatLogLine(r)).join("\n");
    case "stdout":
      return bundle.stdout ?? "";
    case "stderr":
      return bundle.stderr ?? "";
    case "traceback":
      return bundle.traceback ?? "";
    case "metrics":
      return bundle.result?.metrics
        ? JSON.stringify(bundle.result.metrics, null, 2)
        : "";
    case "config":
      return bundle.result?.config_data
        ? JSON.stringify(bundle.result.config_data, null, 2)
        : "";
  }
}

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: "text-zinc-600",
  INFO: "text-zinc-300",
  WARNING: "text-amber-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-300",
};

function formatLogLine(r: DebugLogRecord): string {
  const ts = new Date(r.timestamp * 1000);
  const hh = String(ts.getUTCHours()).padStart(2, "0");
  const mm = String(ts.getUTCMinutes()).padStart(2, "0");
  const ss = String(ts.getUTCSeconds()).padStart(2, "0");
  const ms = String(ts.getUTCMilliseconds()).padStart(3, "0");
  return `[${hh}:${mm}:${ss}.${ms}] ${r.level.padEnd(7)} ${r.logger}: ${r.message}`;
}

function LogsPane({ logs }: { logs: DebugLogRecord[] }) {
  const lines = useMemo(() => logs, [logs]);
  if (!lines.length) {
    return (
      <div className="font-mono text-xs bg-zinc-950 rounded p-3 italic text-zinc-600">
        (no log records captured)
      </div>
    );
  }
  return (
    <div className="font-mono text-xs bg-zinc-950 rounded p-3 overflow-auto max-h-[65vh] space-y-0.5">
      {lines.map((r, i) => (
        <div
          key={i}
          className={`whitespace-pre-wrap break-all ${LEVEL_COLOR[r.level] ?? "text-zinc-300"}`}
        >
          {formatLogLine(r)}
          {r.exc_info && (
            <div className="text-red-400 pl-4 mt-0.5">{r.exc_info}</div>
          )}
        </div>
      ))}
    </div>
  );
}

function TextPane({ text }: { text: string }) {
  if (!text) {
    return (
      <div className="font-mono text-xs bg-zinc-950 rounded p-3 italic text-zinc-600">
        (empty)
      </div>
    );
  }
  return (
    <pre className="font-mono text-xs bg-zinc-950 rounded p-3 overflow-auto max-h-[65vh] whitespace-pre-wrap break-all text-zinc-300">
      {text}
    </pre>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      onClick={onClick}
      disabled={!value}
      className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 disabled:opacity-40 cursor-pointer"
      title="Copy"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
