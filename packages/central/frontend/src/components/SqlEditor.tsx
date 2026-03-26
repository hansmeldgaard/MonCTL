import { useEffect, useRef } from "react";
import { EditorView, basicSetup } from "codemirror";
import { keymap } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorState } from "@codemirror/state";
import { sql } from "@codemirror/lang-sql";

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onExecute?: () => void;
  schema?: Record<string, string[]>;
  height?: string;
}

export function SqlEditor({
  value, onChange, onExecute, schema, height = "200px",
}: SqlEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onExecuteRef = useRef(onExecute);
  onExecuteRef.current = onExecute;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!containerRef.current) return;

    const extensions = [
      basicSetup,
      sql({ schema: schema || {}, upperCaseKeywords: true }),
      oneDark,
      EditorView.theme({
        "&": { height: "100%", fontSize: "13px" },
        ".cm-scroller": { overflow: "auto" },
      }),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChangeRef.current(update.state.doc.toString());
        }
      }),
      keymap.of([
        {
          key: "Ctrl-Enter",
          mac: "Cmd-Enter",
          run: () => {
            onExecuteRef.current?.();
            return true;
          },
        },
      ]),
    ];

    const state = EditorState.create({ doc: value, extensions });
    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;

    return () => { view.destroy(); viewRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, height]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  return (
    <div
      ref={containerRef}
      className="rounded-md border border-zinc-700 overflow-hidden"
      style={{ resize: "vertical", height, minHeight: "100px" }}
    />
  );
}
