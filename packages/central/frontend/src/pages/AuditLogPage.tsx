import { useMemo, useState } from "react";
import { useAuditLogins, useAuditMutations } from "@/api/hooks.ts";
import type { AuditLoginEvent, AuditMutation } from "@/types/api.ts";
import { cn, formatLogTimestamp } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";

type View = "logins" | "mutations";

const LOGIN_TYPES = [
  "login_success",
  "login_failed",
  "logout",
  "token_refresh",
  "token_refresh_failed",
];

const MUTATION_ACTIONS = ["create", "update", "delete"];

const RESOURCE_TYPES = [
  "device",
  "app",
  "assignment",
  "credential",
  "user",
  "role",
  "tenant",
  "alert_definition",
  "automation",
  "connector",
  "template",
  "system_setting",
  "collector",
  "pack",
  "discovery_rule",
];

function EventBadge({ type }: { type: string }) {
  const isFailure = type.includes("failed");
  const isSuccess = type === "login_success" || type === "token_refresh";
  const color = isFailure
    ? "bg-red-500/15 text-red-400 border-red-500/30"
    : isSuccess
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      : "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded border text-xs",
        color,
      )}
    >
      {type}
    </span>
  );
}

function ActionBadge({ action }: { action: string }) {
  const color =
    action === "delete"
      ? "bg-red-500/15 text-red-400 border-red-500/30"
      : action === "create"
        ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
        : "bg-blue-500/15 text-blue-400 border-blue-500/30";
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded border text-xs",
        color,
      )}
    >
      {action}
    </span>
  );
}

function LoginsTable({
  rows,
  timezone,
}: {
  rows: AuditLoginEvent[];
  timezone: string;
}) {
  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<AuditLoginEvent>[]>(
    () => [
      {
        key: "timestamp",
        label: "Timestamp",
        sortable: false,
        filterable: false,
        defaultWidth: 200,
        cellClassName: "text-zinc-400 font-mono text-xs whitespace-nowrap",
        cell: (r) =>
          r.timestamp ? formatLogTimestamp(r.timestamp, timezone) : "—",
      },
      {
        key: "event_type",
        label: "Event",
        sortable: false,
        filterable: false,
        defaultWidth: 160,
        cell: (r) => <EventBadge type={r.event_type} />,
      },
      {
        key: "username",
        label: "User",
        sortable: false,
        filterable: false,
        defaultWidth: 160,
        cellClassName: "text-zinc-200",
        cell: (r) => r.username || "—",
      },
      {
        key: "ip_address",
        label: "IP",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 font-mono text-xs",
        cell: (r) => r.ip_address || "—",
      },
      {
        key: "failure_reason",
        label: "Reason",
        sortable: false,
        filterable: false,
        defaultWidth: 200,
        cellClassName: "text-zinc-400 text-xs",
        cell: (r) => r.failure_reason || "",
      },
      {
        key: "user_agent",
        label: "User-Agent",
        sortable: false,
        filterable: false,
        defaultWidth: 280,
        cellClassName: "text-zinc-500 text-xs truncate max-w-xs",
        cell: (r) => r.user_agent || "",
      },
    ],
    [timezone],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<AuditLoginEvent>("audit-logins", columns);

  if (!rows.length) {
    return (
      <div className="text-sm text-zinc-500 py-8 text-center">
        No login events.
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-end px-3 py-2 border-b border-zinc-800">
        <DisplayMenu
          columns={columns}
          configMap={configMap}
          onToggleHidden={setHidden}
          onReset={reset}
        />
      </div>
      <div
        className={
          compact ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs" : ""
        }
      >
        <FlexTable<AuditLoginEvent>
          orderedVisibleColumns={orderedVisibleColumns}
          configMap={configMap}
          onOrderChange={setOrder}
          onWidthChange={setWidth}
          rows={rows}
          rowKey={(r) => r.id}
          sortBy=""
          sortDir="asc"
          onSort={() => {}}
          filters={{}}
          onFilterChange={() => {}}
          emptyState="No login events"
        />
      </div>
    </div>
  );
}

function MutationDetailModal({
  row,
  onClose,
  timezone,
}: {
  row: AuditMutation;
  onClose: () => void;
  timezone: string;
}) {
  let oldPretty = "";
  let newPretty = "";
  try {
    oldPretty = JSON.stringify(JSON.parse(row.old_values || "{}"), null, 2);
  } catch {
    oldPretty = row.old_values;
  }
  try {
    newPretty = JSON.stringify(JSON.parse(row.new_values || "{}"), null, 2);
  } catch {
    newPretty = row.new_values;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-zinc-950 border border-zinc-800 rounded-lg shadow-2xl max-w-5xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <div>
            <div className="text-sm font-medium text-zinc-100">
              <ActionBadge action={row.action} />{" "}
              <span className="text-zinc-400">{row.resource_type}</span>
              <span className="text-zinc-600">/</span>
              <span className="font-mono text-xs">{row.resource_id}</span>
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              {formatLogTimestamp(row.timestamp, timezone)} ·{" "}
              {row.username || "system"} · {row.ip_address}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 px-2"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto p-4 grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
              Old values
            </div>
            <pre className="bg-zinc-900 border border-zinc-800 rounded p-3 text-xs text-zinc-300 whitespace-pre-wrap break-all">
              {oldPretty}
            </pre>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
              New values
            </div>
            <pre className="bg-zinc-900 border border-zinc-800 rounded p-3 text-xs text-zinc-300 whitespace-pre-wrap break-all">
              {newPretty}
            </pre>
          </div>
          {row.changed_fields.length > 0 && (
            <div className="col-span-2">
              <div className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
                Changed fields
              </div>
              <div className="flex flex-wrap gap-1">
                {row.changed_fields.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center px-2 py-0.5 rounded bg-zinc-800 text-xs text-zinc-300"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="col-span-2 text-xs text-zinc-500 font-mono">
            request_id: {row.request_id} · method: {row.method} · path:{" "}
            {row.path}
          </div>
        </div>
      </div>
    </div>
  );
}

function MutationsTable({
  rows,
  timezone,
}: {
  rows: AuditMutation[];
  timezone: string;
}) {
  const [selected, setSelected] = useState<AuditMutation | null>(null);
  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<AuditMutation>[]>(
    () => [
      {
        key: "timestamp",
        label: "Timestamp",
        sortable: false,
        filterable: false,
        defaultWidth: 200,
        cellClassName: "text-zinc-400 font-mono text-xs whitespace-nowrap",
        cell: (r) => formatLogTimestamp(r.timestamp, timezone),
      },
      {
        key: "action",
        label: "Action",
        sortable: false,
        filterable: false,
        defaultWidth: 110,
        cell: (r) => <ActionBadge action={r.action} />,
      },
      {
        key: "resource",
        label: "Resource",
        sortable: false,
        filterable: false,
        defaultWidth: 220,
        cellClassName: "text-zinc-200",
        cell: (r) => (
          <>
            {r.resource_type}
            <span className="text-zinc-600 mx-1">/</span>
            <span className="font-mono text-xs text-zinc-500">
              {r.resource_id.slice(0, 8)}
            </span>
          </>
        ),
      },
      {
        key: "username",
        label: "User",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-300",
        cell: (r) => r.username || "system",
      },
      {
        key: "ip_address",
        label: "IP",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 font-mono text-xs",
        cell: (r) => r.ip_address || "—",
      },
      {
        key: "changed_fields",
        label: "Fields",
        sortable: false,
        filterable: false,
        defaultWidth: 280,
        cellClassName: "text-zinc-500 text-xs truncate max-w-xs",
        cell: (r) =>
          `${r.changed_fields.slice(0, 5).join(", ")}${r.changed_fields.length > 5 ? "…" : ""}`,
      },
      {
        key: "__details",
        label: "",
        pickerLabel: "Details",
        sortable: false,
        filterable: false,
        defaultWidth: 80,
        cell: (r) => (
          <button
            type="button"
            onClick={() => setSelected(r)}
            className="text-brand-400 hover:text-brand-300 text-xs underline cursor-pointer"
          >
            details
          </button>
        ),
      },
    ],
    [timezone],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<AuditMutation>("audit-mutations", columns);

  if (!rows.length) {
    return (
      <div className="text-sm text-zinc-500 py-8 text-center">
        No mutation events.
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-end px-3 py-2 border-b border-zinc-800">
        <DisplayMenu
          columns={columns}
          configMap={configMap}
          onToggleHidden={setHidden}
          onReset={reset}
        />
      </div>
      <div
        className={
          compact ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs" : ""
        }
      >
        <FlexTable<AuditMutation>
          orderedVisibleColumns={orderedVisibleColumns}
          configMap={configMap}
          onOrderChange={setOrder}
          onWidthChange={setWidth}
          rows={rows}
          rowKey={(r) => `${r.request_id}-${r.resource_id}-${r.timestamp}`}
          sortBy=""
          sortDir="asc"
          onSort={() => {}}
          filters={{}}
          onFilterChange={() => {}}
          emptyState="No mutation events"
        />
      </div>
      {selected && (
        <MutationDetailModal
          row={selected}
          onClose={() => setSelected(null)}
          timezone={timezone}
        />
      )}
    </>
  );
}

export function AuditLogPage() {
  const timezone = useTimezone();
  const [view, setView] = useState<View>("logins");
  const [eventType, setEventType] = useState("");
  const [username, setUsername] = useState("");
  const [ipAddress, setIpAddress] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [action, setAction] = useState("");

  const loginsQuery = useAuditLogins({
    event_type: view === "logins" ? eventType : undefined,
    username: view === "logins" ? username : undefined,
    ip_address: view === "logins" ? ipAddress : undefined,
    limit: 200,
  });

  const mutationsQuery = useAuditMutations({
    resource_type: view === "mutations" ? resourceType : undefined,
    action: view === "mutations" ? action : undefined,
    username: view === "mutations" ? username : undefined,
    ip_address: view === "mutations" ? ipAddress : undefined,
    limit: 200,
  });

  const loginRows = loginsQuery.data?.data ?? [];
  const mutationRows = mutationsQuery.data?.data ?? [];
  const loginTotal = loginsQuery.data?.meta?.total ?? loginRows.length;
  const mutationTotal = mutationsQuery.data?.meta?.total ?? mutationRows.length;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-zinc-100">Audit Log</h2>
        <p className="text-sm text-zinc-500">
          Authentication events and all mutations across the system.
        </p>
      </div>

      {/* View switcher */}
      <div className="flex gap-1 border-b border-zinc-800">
        <button
          onClick={() => setView("logins")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 cursor-pointer",
            view === "logins"
              ? "border-brand-500 text-brand-400"
              : "border-transparent text-zinc-500 hover:text-zinc-300",
          )}
        >
          Logins ({loginTotal})
        </button>
        <button
          onClick={() => setView("mutations")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 cursor-pointer",
            view === "mutations"
              ? "border-brand-500 text-brand-400"
              : "border-transparent text-zinc-500 hover:text-zinc-300",
          )}
        >
          Mutations ({mutationTotal})
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {view === "logins" ? (
          <select
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-200"
          >
            <option value="">All event types</option>
            {LOGIN_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        ) : (
          <>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-200"
            >
              <option value="">All resources</option>
              {RESOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-200"
            >
              <option value="">All actions</option>
              {MUTATION_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </>
        )}
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
        />
        <input
          value={ipAddress}
          onChange={(e) => setIpAddress(e.target.value)}
          placeholder="IP address"
          className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
        />
      </div>

      {/* Content */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg">
        {view === "logins" ? (
          loginsQuery.isLoading ? (
            <div className="p-8 text-center text-zinc-500">Loading…</div>
          ) : (
            <LoginsTable rows={loginRows} timezone={timezone} />
          )
        ) : mutationsQuery.isLoading ? (
          <div className="p-8 text-center text-zinc-500">Loading…</div>
        ) : (
          <MutationsTable rows={mutationRows} timezone={timezone} />
        )}
      </div>
    </div>
  );
}
