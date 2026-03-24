import { Select } from "@/components/ui/select.tsx";
import { Input } from "@/components/ui/input.tsx";
import { useSnmpOids, useCredentials } from "@/api/hooks.ts";

interface SchemaConfigFieldsProps {
  schema: Record<string, unknown> | null | undefined;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  prefix: string;
  disabled?: boolean;
}

export function SchemaConfigFields({
  schema,
  config,
  onChange,
  prefix,
  disabled,
}: SchemaConfigFieldsProps) {
  const { data: snmpOids } = useSnmpOids();
  const { data: credentials } = useCredentials();

  if (!schema || typeof schema !== "object") return null;
  const properties = (schema as { properties?: Record<string, Record<string, unknown>> }).properties;
  if (!properties) return null;

  const setField = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <>
      {Object.entries(properties).map(([key, prop]) => {
        const widget = prop["x-widget"] as string | undefined;
        const title = (prop.title as string) ?? key;
        const defaultVal = prop.default;
        const currentVal = config[key] ?? defaultVal ?? "";

        // SNMP OID selector
        if (widget === "snmp-oid") {
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Select
                id={`${prefix}-${key}`}
                value={String(currentVal)}
                onChange={(e) => setField(key, e.target.value)}
                disabled={disabled}
              >
                <option value="">-- {title} --</option>
                {(snmpOids ?? []).map((o) => (
                  <option key={o.id} value={o.oid}>{o.name} ({o.oid})</option>
                ))}
              </Select>
            </div>
          );
        }

        // Credential selector
        if (widget === "credential") {
          const credName = typeof currentVal === "string" && currentVal.startsWith("$credential:")
            ? currentVal.slice("$credential:".length)
            : String(currentVal);
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Select
                id={`${prefix}-${key}`}
                value={credName}
                onChange={(e) => setField(key, e.target.value ? `$credential:${e.target.value}` : "")}
                disabled={disabled}
              >
                <option value="">-- {title} --</option>
                {(credentials ?? []).map((c) => (
                  <option key={c.id} value={c.name}>{c.name}</option>
                ))}
              </Select>
            </div>
          );
        }

        // Number input
        if (prop.type === "integer" || prop.type === "number") {
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Input
                id={`${prefix}-${key}`}
                type="number"
                min={prop.minimum as number | undefined}
                max={prop.maximum as number | undefined}
                value={currentVal !== "" ? String(currentVal) : String(defaultVal ?? "")}
                onChange={(e) => setField(key, e.target.value ? parseInt(e.target.value, 10) : undefined)}
                className="w-28"
                disabled={disabled}
              />
            </div>
          );
        }

        // Default: text input
        return (
          <div key={key} className="space-y-1">
            <span className="text-xs text-zinc-400">{title}</span>
            <Input
              id={`${prefix}-${key}`}
              value={String(currentVal)}
              onChange={(e) => setField(key, e.target.value)}
              disabled={disabled}
            />
          </div>
        );
      })}
    </>
  );
}
