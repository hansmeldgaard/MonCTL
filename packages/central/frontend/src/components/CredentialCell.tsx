import { Badge } from "@/components/ui/badge.tsx";
import { Key } from "lucide-react";

interface CredentialCellProps {
  credentialName: string | null;
  credentialOverrides?: { alias: string; credential_id: string; credential_name: string }[];
  deviceDefaultCredentialName: string | null;
}

export function CredentialCell({
  credentialName,
  credentialOverrides,
  deviceDefaultCredentialName,
}: CredentialCellProps) {
  const overrides = credentialOverrides ?? [];

  if (overrides.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
        {overrides.map((ov) => (
          <Badge key={ov.alias} variant="info" className="text-[10px] gap-1">
            <Key className="h-2.5 w-2.5" />
            {ov.credential_name}
          </Badge>
        ))}
      </div>
    );
  }

  const resolved = credentialName ?? deviceDefaultCredentialName;
  if (resolved) {
    return (
      <Badge variant="info" className="text-[10px] gap-1">
        <Key className="h-2.5 w-2.5" />
        {resolved}
        {!credentialName && deviceDefaultCredentialName && (
          <span className="text-zinc-500 ml-0.5">(default)</span>
        )}
      </Badge>
    );
  }

  return <span className="text-zinc-600 text-xs">{"\u2014"}</span>;
}
