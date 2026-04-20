import { useRef, useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import type { DisplayTemplate } from "@/types/api.ts";

interface ConfigDataRendererProps {
  template: DisplayTemplate | null;
  data: Record<string, string>;
  className?: string;
}

export function ConfigDataRenderer({
  template,
  data,
  className,
}: ConfigDataRendererProps) {
  if (!template) {
    return <ConfigKeyValueTable data={data} className={className} />;
  }

  return (
    <TemplateRenderer template={template} data={data} className={className} />
  );
}

function TemplateRenderer({
  template,
  data,
  className,
}: {
  template: DisplayTemplate;
  data: Record<string, string>;
  className?: string;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(150);

  const renderedHtml = template.html.replace(
    /\{\{([a-zA-Z_][a-zA-Z0-9_.-]*)\}\}/g,
    (_match, key) => {
      const val = data[key];
      return val !== undefined ? escapeHtml(val) : "\u2014";
    },
  );

  // Inject config data as window.__configData for templates that use JS to parse it
  const dataJson = JSON.stringify(data).replace(/<\//g, "<\\/");

  const srcDoc = `<!DOCTYPE html><html><head><style>
    html, body { margin: 0; padding: 8px; background: #18181b; color: #e4e4e7; font-family: system-ui, -apple-system, sans-serif; font-size: 14px; overflow: hidden; }
    ${template.css ?? ""}
  </style></head><body>
  <script>window.__configData = ${dataJson};</script>
  ${renderedHtml}
  <script>
    // srcDoc + allow-same-origin → iframe inherits parent origin, so we can
    // target it explicitly. "*" would let any document embedding us receive
    // these height messages (and passively fingerprint config-template usage).
    var _parentOrigin = window.location.origin;
    function sendHeight() {
      var h = document.documentElement.scrollHeight;
      window.parent.postMessage({ type: 'config-renderer-height', height: h }, _parentOrigin);
    }
    sendHeight();
    new MutationObserver(sendHeight).observe(document.body, { childList: true, subtree: true });
    setTimeout(sendHeight, 200);
  </script>
  </html>`;

  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      // Only trust our own iframe — an attacker-controlled tab could otherwise
      // send fake height messages to grow the frame and overlay real UI.
      if (e.origin !== window.location.origin) return;
      if (
        e.data?.type === "config-renderer-height" &&
        typeof e.data.height === "number"
      ) {
        setHeight(Math.max(e.data.height + 4, 100));
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  return (
    <div className={className}>
      <iframe
        ref={iframeRef}
        srcDoc={srcDoc}
        sandbox="allow-scripts allow-same-origin"
        title="Config Data"
        className="w-full border-0 rounded-md"
        style={{ height: `${height}px`, background: "#18181b" }}
      />
    </div>
  );
}

/**
 * Detect if keys follow the `type::entity::field` pattern (e.g. "fan::0/FT0::serial_number").
 * If so, render grouped tables. Otherwise fall back to flat key/value.
 */
function ConfigKeyValueTable({
  data,
  className,
}: {
  data: Record<string, string>;
  className?: string;
}) {
  const entries = Object.entries(data);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-zinc-600 py-4 text-center">
        No configuration data available.
      </p>
    );
  }

  // Try to parse as type::entity::field
  const structured = new Map<string, Map<string, Map<string, string>>>();
  let structuredCount = 0;
  const flat: [string, string][] = [];

  for (const [key, value] of entries) {
    const parts = key.split("::");
    if (parts.length === 3) {
      const [group, entity, field] = parts;
      if (!structured.has(group)) structured.set(group, new Map());
      const entityMap = structured.get(group)!;
      if (!entityMap.has(entity)) entityMap.set(entity, new Map());
      entityMap.get(entity)!.set(field, value);
      structuredCount++;
    } else {
      flat.push([key, value]);
    }
  }

  // If most keys are structured, use grouped view
  if (structuredCount > entries.length * 0.5 && structured.size > 0) {
    return (
      <GroupedConfigView
        groups={structured}
        flat={flat}
        className={className}
      />
    );
  }

  // Fallback: flat key/value table
  const sorted = entries.sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className={className}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Key</TableHead>
            <TableHead>Value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map(([key, value]) => (
            <TableRow key={key}>
              <TableCell className="font-mono text-xs text-zinc-400">
                {key}
              </TableCell>
              <TableCell className="font-mono text-sm text-zinc-200">
                {value}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const GROUP_ORDER = ["chassis", "module", "psu", "fan"];
const GROUP_LABELS: Record<string, string> = {
  chassis: "Chassis",
  module: "Modules",
  psu: "Power Supplies",
  fan: "Fans",
};
const GROUP_COLORS: Record<
  string,
  { badge: string; border: string; headerBg: string; stripe: string }
> = {
  chassis: {
    badge: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    border: "border-blue-500/20",
    headerBg: "bg-blue-500/5",
    stripe: "bg-blue-500/5",
  },
  module: {
    badge: "bg-violet-500/20 text-violet-400 border-violet-500/30",
    border: "border-violet-500/20",
    headerBg: "bg-violet-500/5",
    stripe: "bg-violet-500/5",
  },
  psu: {
    badge: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    border: "border-amber-500/20",
    headerBg: "bg-amber-500/5",
    stripe: "bg-amber-500/5",
  },
  fan: {
    badge: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    border: "border-emerald-500/20",
    headerBg: "bg-emerald-500/5",
    stripe: "bg-emerald-500/5",
  },
};
const DEFAULT_COLORS = {
  badge: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  border: "border-zinc-700",
  headerBg: "bg-zinc-800/50",
  stripe: "bg-zinc-800/30",
};

function GroupedConfigView({
  groups,
  flat,
  className,
}: {
  groups: Map<string, Map<string, Map<string, string>>>;
  flat: [string, string][];
  className?: string;
}) {
  // Sort groups: known order first, then alphabetical for unknown
  const sortedGroups = [...groups.entries()].sort(([a], [b]) => {
    const ai = GROUP_ORDER.indexOf(a.toLowerCase());
    const bi = GROUP_ORDER.indexOf(b.toLowerCase());
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });

  return (
    <div className={`space-y-6 ${className ?? ""}`}>
      {sortedGroups.map(([groupName, entities]) => {
        const colors = GROUP_COLORS[groupName.toLowerCase()] ?? DEFAULT_COLORS;

        // Collect all unique fields across entities in this group
        const allFields = new Set<string>();
        for (const fields of entities.values()) {
          for (const f of fields.keys()) allFields.add(f);
        }
        // Sort fields in a sensible order
        const fieldOrder = [
          "description",
          "manufacturer",
          "model",
          "serial_number",
          "hardware_revision",
          "firmware_revision",
          "software_revision",
        ];
        const sortedFields = [...allFields].sort((a, b) => {
          const ai = fieldOrder.indexOf(a);
          const bi = fieldOrder.indexOf(b);
          if (ai !== -1 && bi !== -1) return ai - bi;
          if (ai !== -1) return -1;
          if (bi !== -1) return 1;
          return a.localeCompare(b);
        });

        // Sort entities naturally
        const sortedEntities = [...entities.entries()].sort(([a], [b]) =>
          a.localeCompare(b, undefined, { numeric: true }),
        );

        return (
          <div
            key={groupName}
            className={`rounded-lg border ${colors.border} overflow-hidden`}
          >
            <div
              className={`px-3 py-2 ${colors.headerBg} border-b ${colors.border}`}
            >
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${colors.badge}`}
              >
                {GROUP_LABELS[groupName.toLowerCase()] ?? groupName}
                <span className="ml-1.5 opacity-60">{entities.size}</span>
              </span>
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className={colors.headerBg}>
                    <TableHead className="text-xs whitespace-nowrap font-semibold">
                      Entity
                    </TableHead>
                    {sortedFields.map((f) => (
                      <TableHead key={f} className="text-xs whitespace-nowrap">
                        {f
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (c) => c.toUpperCase())}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedEntities.map(([entityName, fields], idx) => (
                    <TableRow
                      key={entityName}
                      className={idx % 2 === 1 ? colors.stripe : ""}
                    >
                      <TableCell className="font-mono text-xs text-zinc-200 whitespace-nowrap font-medium">
                        {entityName}
                      </TableCell>
                      {sortedFields.map((f) => (
                        <TableCell
                          key={f}
                          className="font-mono text-xs text-zinc-400 max-w-[250px] truncate"
                          title={fields.get(f) ?? ""}
                        >
                          {fields.get(f) ?? "\u2014"}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        );
      })}

      {/* Flat entries that didn't match the pattern */}
      {flat.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-zinc-300 mb-2">Other</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Key</TableHead>
                <TableHead className="text-xs">Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {flat
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, value]) => (
                  <TableRow key={key}>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {key}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-200">
                      {value}
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
