import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { CodeEditor } from "@/components/CodeEditor.tsx";
import { useAppConfigKeys } from "@/api/hooks.ts";
import type { DisplayTemplate } from "@/types/api.ts";

interface DisplayTemplateEditorProps {
  appId: string;
  versionId?: string;
  initialTemplate: DisplayTemplate | null;
  onSave: (template: DisplayTemplate) => Promise<void>;
  readOnly?: boolean;
}

const DEFAULT_HTML = `<div class="config-data">
  <!-- Click 'insert' on keys above to add them here -->
</div>`;

const DEFAULT_CSS = `.config-data { font-family: system-ui; font-size: 14px; }`;

export function DisplayTemplateEditor({
  appId,
  versionId,
  initialTemplate,
  onSave,
  readOnly = false,
}: DisplayTemplateEditorProps) {
  const { data: configKeys, isLoading: keysLoading } = useAppConfigKeys(appId, versionId);

  const [html, setHtml] = useState(initialTemplate?.html ?? DEFAULT_HTML);
  const [css, setCss] = useState(initialTemplate?.css ?? DEFAULT_CSS);
  const [cssOpen, setCssOpen] = useState(false);
  const [customKeys, setCustomKeys] = useState<string[]>([]);
  const [newKey, setNewKey] = useState("");
  const [saving, setSaving] = useState(false);

  // Track cursor position for insert
  const htmlRef = useRef(html);
  htmlRef.current = html;

  // All keys: detected + custom
  const allKeys = useMemo(() => {
    const detected = configKeys?.all_keys ?? [];
    return [...new Set([...detected, ...customKeys])].sort();
  }, [configKeys, customKeys]);

  // Keys used in the HTML template
  const usedKeys = useMemo(() => {
    const matches = html.matchAll(/\{\{([a-zA-Z_][a-zA-Z0-9_.-]*)\}\}/g);
    return [...new Set([...matches].map((m) => m[1]))];
  }, [html]);

  const insertKey = useCallback(
    (key: string) => {
      setHtml((prev) => prev + `{{${key}}}`);
    },
    [],
  );

  const addCustomKey = useCallback(() => {
    const k = newKey.trim();
    if (k && /^[a-zA-Z_][a-zA-Z0-9_.-]*$/.test(k) && !customKeys.includes(k)) {
      setCustomKeys((prev) => [...prev, k]);
      setNewKey("");
    }
  }, [newKey, customKeys]);

  const removeCustomKey = useCallback((key: string) => {
    setCustomKeys((prev) => prev.filter((k) => k !== key));
  }, []);

  // Preview: replace {{key}} with [key]
  const previewHtml = useMemo(() => {
    const replaced = html.replace(
      /\{\{([a-zA-Z_][a-zA-Z0-9_.-]*)\}\}/g,
      (_match, key) => `<span style="background:#3b82f6;color:white;padding:1px 4px;border-radius:3px;font-size:12px">[${key}]</span>`,
    );
    return `<!DOCTYPE html><html><head><style>
      body { margin: 8px; background: #18181b; color: #e4e4e7; }
      ${css}
    </style></head><body>${replaced}</body></html>`;
  }, [html, css]);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    if (iframeRef.current) {
      iframeRef.current.srcdoc = previewHtml;
    }
  }, [previewHtml]);

  async function handleSave() {
    setSaving(true);
    try {
      const keyMappings = [...new Set([...usedKeys, ...customKeys])].sort();
      await onSave({ html, css, key_mappings: keyMappings });
    } finally {
      setSaving(false);
    }
  }

  const sourceCodeKeys = new Set(configKeys?.source_code_keys ?? []);
  const clickhouseKeys = new Set(configKeys?.clickhouse_keys ?? []);

  return (
    <div className="space-y-4">
      {/* Key Mappings Panel */}
      <div className="rounded-md border border-zinc-700 bg-zinc-800/50 p-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">
          Available Keys
        </p>
        {keysLoading ? (
          <div className="flex items-center gap-2 py-2 text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Detecting keys...</span>
          </div>
        ) : allKeys.length === 0 && customKeys.length === 0 ? (
          <p className="text-sm text-zinc-600 py-2">
            No keys detected yet. Add keys manually or write config_key references in the source
            code.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {allKeys.map((key) => {
              const isCustom = customKeys.includes(key);
              const isSource = sourceCodeKeys.has(key);
              const isData = clickhouseKeys.has(key);
              return (
                <span key={key} className="inline-flex items-center gap-1">
                  <Badge variant="default" className="font-mono text-xs gap-1">
                    {key}
                    {isSource && (
                      <span className="text-[10px] px-1 rounded bg-green-600/30 text-green-400">
                        source
                      </span>
                    )}
                    {isData && (
                      <span className="text-[10px] px-1 rounded bg-blue-600/30 text-blue-400">
                        data
                      </span>
                    )}
                    {isCustom && (
                      <button
                        onClick={() => removeCustomKey(key)}
                        className="ml-0.5 hover:text-red-400"
                        type="button"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </Badge>
                  {!readOnly && (
                    <button
                      onClick={() => insertKey(key)}
                      className="text-[10px] text-brand-400 hover:text-brand-300 cursor-pointer"
                      type="button"
                    >
                      insert
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        )}
        {!readOnly && (
          <div className="flex items-center gap-2 mt-2">
            <Input
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="Add custom key..."
              className="h-7 text-xs max-w-[200px]"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCustomKey();
                }
              }}
            />
            <Button type="button" size="sm" variant="ghost" onClick={addCustomKey} className="h-7">
              <Plus className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>

      {/* HTML + Preview split */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            HTML Template
          </p>
          <CodeEditor value={html} onChange={readOnly ? undefined : setHtml} readOnly={readOnly} height="calc(100vh - 400px)" />
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Live Preview
          </p>
          <div className="rounded-md border border-zinc-700 overflow-hidden" style={{ height: "calc(100vh - 400px)" }}>
            <iframe
              ref={iframeRef}
              sandbox="allow-scripts allow-same-origin"
              title="Template Preview"
              className="w-full h-full border-0 bg-zinc-900"
            />
          </div>
        </div>
      </div>

      {/* CSS (collapsible) */}
      <details open={cssOpen} onToggle={(e) => setCssOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-zinc-500 select-none">
          CSS {cssOpen ? "▾" : "▸"}
        </summary>
        <div className="mt-1.5">
          <CodeEditor value={css} onChange={readOnly ? undefined : setCss} readOnly={readOnly} height="150px" />
        </div>
      </details>

      {/* Save */}
      {!readOnly && (
        <div className="flex justify-end">
          <Button type="button" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save Template
          </Button>
        </div>
      )}
    </div>
  );
}
