import { KeyRound, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useCredentials } from "@/api/hooks.ts";
import { formatDate } from "@/lib/utils.ts";

export function CredentialsPage() {
  const { data: credentials, isLoading } = useCredentials();

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-sm text-zinc-500">
        {credentials?.length ?? 0} credential{(credentials?.length ?? 0) !== 1 ? "s" : ""}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            Credentials
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!credentials || credentials.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <KeyRound className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No credentials stored</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {credentials.map((cred) => (
                  <TableRow key={cred.id}>
                    <TableCell className="font-medium text-zinc-100">
                      {cred.name}
                    </TableCell>
                    <TableCell className="max-w-[300px] truncate text-zinc-400">
                      {cred.description || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="info">{cred.credential_type}</Badge>
                    </TableCell>
                    <TableCell className="text-zinc-500">
                      {formatDate(cred.created_at)}
                    </TableCell>
                    <TableCell className="text-zinc-500">
                      {formatDate(cred.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
