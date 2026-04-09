import { useState } from "react";
import { Select } from "@/components/ui/select.tsx";
import { Input } from "@/components/ui/input.tsx";
import { useSnmpOids, useCredentials } from "@/api/hooks.ts";

interface DeviceCredentialEntry {
  id: string;
  name: string;
  credential_type: string;
}

interface SchemaConfigFieldsProps {
  schema: Record<string, unknown> | null | undefined;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  prefix: string;
  disabled?: boolean;
  deviceCredentials?: Record<string, DeviceCredentialEntry>;
}

function OidSelector({
  id,
  value,
  onChange,
  disabled,
  title,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  title: string;
}) {
  const { data: snmpOids } = useSnmpOids();
  const oids = snmpOids ?? [];
  const inList = oids.some((o) => o.oid === value);
  const [custom, setCustom] = useState(!inList && value !== "");

  if (custom) {
    return (
      <div className="flex gap-2">
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="1.3.6.1.2.1.1.3.0"
          disabled={disabled}
          className="flex-1"
        />
        <button
          type="button"
          onClick={() => setCustom(false)}
          className="text-xs text-zinc-400 hover:text-zinc-200 whitespace-nowrap"
        >
          Pick from list
        </button>
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      <Select
        id={id}
        value={value}
        onChange={(e) => {
          if (e.target.value === "__custom__") {
            setCustom(true);
            return;
          }
          onChange(e.target.value);
        }}
        disabled={disabled}
        className="flex-1"
      >
        <option value="">-- {title} --</option>
        {oids.map((o) => (
          <option key={o.id} value={o.oid}>
            {o.name} ({o.oid})
          </option>
        ))}
        <option value="__custom__">Custom OID...</option>
      </Select>
    </div>
  );
}

export function SchemaConfigFields({
  schema,
  config,
  onChange,
  prefix,
  disabled,
  deviceCredentials,
}: SchemaConfigFieldsProps) {
  const { data: credentials } = useCredentials();

  if (!schema || typeof schema !== "object") return null;
  const properties = (
    schema as { properties?: Record<string, Record<string, unknown>> }
  ).properties;
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
              <OidSelector
                id={`${prefix}-${key}`}
                value={String(currentVal)}
                onChange={(v) => setField(key, v)}
                disabled={disabled}
                title={title}
              />
            </div>
          );
        }

        // Credential selector
        if (widget === "credential") {
          const credName =
            typeof currentVal === "string" &&
            currentVal.startsWith("$credential:")
              ? currentVal.slice("$credential:".length)
              : String(currentVal);
          // Derive credential type from property key (e.g. "snmp_credential" → "snmp")
          // or from explicit x-credential-type in schema
          const credType =
            (prop["x-credential-type"] as string) ??
            key.replace(/_credential$/, "");
          const deviceCred = deviceCredentials?.[credType];
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Select
                id={`${prefix}-${key}`}
                value={credName}
                onChange={(e) =>
                  setField(
                    key,
                    e.target.value ? `$credential:${e.target.value}` : "",
                  )
                }
                disabled={disabled}
              >
                <option value="">-- None --</option>
                <option value="$credential:__device_default__">
                  {deviceCred
                    ? `Use Device Default (${deviceCred.name})`
                    : "Use Device Default Credential"}
                </option>
                {(credentials ?? [])
                  .filter(
                    (c) => !credType || c.credential_type.startsWith(credType),
                  )
                  .map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name}
                    </option>
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
                value={
                  currentVal !== ""
                    ? String(currentVal)
                    : String(defaultVal ?? "")
                }
                onChange={(e) =>
                  setField(
                    key,
                    e.target.value ? parseInt(e.target.value, 10) : undefined,
                  )
                }
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
