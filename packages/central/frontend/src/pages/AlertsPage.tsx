import { useState } from "react";
import { Bell, Loader2, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import { useActiveAlerts, useAlertRules } from "@/api/hooks.ts";
import { timeAgo } from "@/lib/utils.ts";

type Tab = "active" | "rules";

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { data: alerts, isLoading: alertsLoading } = useActiveAlerts();
  const { data: rules, isLoading: rulesLoading } = useAlertRules();

  const isLoading = tab === "active" ? alertsLoading : rulesLoading;

  return (
    <div className="space-y-4">
      {/* Tab switcher */}
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button
          variant={tab === "active" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("active")}
        >
          <Bell className="h-3.5 w-3.5" />
          Active Alerts
          {alerts && alerts.length > 0 && (
            <Badge variant="destructive" className="ml-1.5">
              {alerts.length}
            </Badge>
          )}
        </Button>
        <Button
          variant={tab === "rules" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("rules")}
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          Alert Rules
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
        </div>
      ) : tab === "active" ? (
        <ActiveAlertsTab alerts={alerts ?? []} />
      ) : (
        <AlertRulesTab rules={rules ?? []} />
      )}
    </div>
  );
}

function ActiveAlertsTab({
  alerts,
}: {
  alerts: Array<{
    id: string;
    rule_id: string;
    state: string;
    labels: Record<string, string>;
    started_at: string;
  }>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-4 w-4" />
          Active Alerts ({alerts.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-emerald-500/50" />
            <p className="text-sm">No active alerts — all clear</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>State</TableHead>
                <TableHead>Rule ID</TableHead>
                <TableHead>Labels</TableHead>
                <TableHead>Started</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {alerts.map((alert) => (
                <TableRow key={alert.id}>
                  <TableCell>
                    <StatusBadge state={alert.state} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-zinc-300">
                    {alert.labels?.rule_name ?? alert.rule_id}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(alert.labels ?? {}).map(
                        ([key, value]) => (
                          <Badge
                            key={key}
                            variant="default"
                            className="text-xs"
                          >
                            {key}: {value}
                          </Badge>
                        ),
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-zinc-500">
                    {timeAgo(alert.started_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function AlertRulesTab({
  rules,
}: {
  rules: Array<{
    id: string;
    name: string;
    rule_type: string;
    severity: string;
    enabled: boolean;
  }>;
}) {
  const severityVariant = (severity: string) => {
    switch (severity.toLowerCase()) {
      case "critical":
        return "destructive" as const;
      case "warning":
        return "warning" as const;
      case "info":
        return "info" as const;
      default:
        return "default" as const;
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          Alert Rules ({rules.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <ShieldCheck className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No alert rules configured</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Enabled</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium text-zinc-100">
                    {rule.name}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {rule.rule_type}
                  </TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(rule.severity)}>
                      {rule.severity}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={rule.enabled ? "success" : "default"}
                    >
                      {rule.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
