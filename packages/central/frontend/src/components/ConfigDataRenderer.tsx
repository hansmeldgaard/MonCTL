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

export function ConfigDataRenderer({ template, data, className }: ConfigDataRendererProps) {
  if (!template) {
    return <ConfigKeyValueTable data={data} className={className} />;
  }

  return <TemplateRenderer template={template} data={data} className={className} />;
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

  const srcDoc = `<!DOCTYPE html><html><head><style>
    body { margin: 8px; background: #18181b; color: #e4e4e7; font-family: system-ui; }
    ${template.css ?? ""}
  </style></head><body>${renderedHtml}</body></html>`;

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.srcdoc = srcDoc;

    const onLoad = () => {
      try {
        const h = iframe.contentDocument?.body?.scrollHeight;
        if (h && h > 0) setHeight(h + 16);
      } catch {
        // cross-origin
      }
    };
    iframe.addEventListener("load", onLoad);
    return () => iframe.removeEventListener("load", onLoad);
  }, [srcDoc]);

  return (
    <div className={className}>
      <iframe
        ref={iframeRef}
        sandbox="allow-same-origin"
        title="Config Data"
        className="w-full border-0 rounded-md"
        style={{ height: `${height}px`, background: "#18181b" }}
      />
    </div>
  );
}

function ConfigKeyValueTable({
  data,
  className,
}: {
  data: Record<string, string>;
  className?: string;
}) {
  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));

  if (entries.length === 0) {
    return (
      <p className="text-sm text-zinc-600 py-4 text-center">No configuration data available.</p>
    );
  }

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
          {entries.map(([key, value]) => (
            <TableRow key={key}>
              <TableCell className="font-mono text-xs text-zinc-400">{key}</TableCell>
              <TableCell className="font-mono text-sm text-zinc-200">{value}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
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
