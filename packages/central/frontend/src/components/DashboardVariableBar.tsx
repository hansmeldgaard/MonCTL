import { X } from "lucide-react";
import type { DashboardVariable } from "@/types/api.ts";

interface Props {
  variables: DashboardVariable[];
  values: Record<string, string>;
  onClear: (name: string) => void;
}

export function DashboardVariableBar({ variables, values, onClear }: Props) {
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-zinc-800 bg-zinc-900/50 overflow-x-auto">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide shrink-0">Vars</span>
      {variables.map((v) => {
        const val = values[v.name];
        const isSet = val && val !== v.default_value;
        return (
          <div
            key={v.name}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs shrink-0 ${
              isSet
                ? "bg-brand-600/20 text-brand-400 border border-brand-600/30"
                : "bg-zinc-800 text-zinc-500 border border-zinc-700"
            }`}
          >
            <span className="font-mono text-[11px]">{v.name}</span>
            {val && (
              <>
                <span className="text-zinc-600">=</span>
                <span className="truncate max-w-24">{val}</span>
              </>
            )}
            {isSet && (
              <button
                onClick={() => onClear(v.name)}
                className="text-zinc-500 hover:text-zinc-300 ml-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
