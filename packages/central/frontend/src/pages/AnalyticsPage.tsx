import { ExternalLink, Activity, Bell, Network, Server } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { useSystemSettings } from "@/api/hooks.ts";

const DASHBOARDS = [
  {
    name: "Device Performance",
    description: "CPU, memory, disk metrics over time",
    icon: Server,
    path: "/collection/root",
  },
  {
    name: "Interface Traffic",
    description: "Bandwidth, errors, utilization per interface",
    icon: Network,
    path: "/collection/root",
  },
  {
    name: "Availability Overview",
    description: "Uptime, response times, unreachable devices",
    icon: Activity,
    path: "/collection/root",
  },
  {
    name: "Alert History",
    description: "Alert trends, noisy rules, raw log",
    icon: Bell,
    path: "/collection/root",
  },
];

export function AnalyticsPage() {
  const { data: systemSettings } = useSystemSettings();
  const metabaseUrl = systemSettings?.metabase_url || "";

  if (!metabaseUrl) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-zinc-100">Analytics & Custom Dashboards</h1>
        <p className="text-sm text-zinc-500">
          Metabase is not configured. Set the <code className="rounded bg-zinc-800 px-1 py-0.5">metabase_url</code> in
          Settings to enable analytics dashboards.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">Analytics & Custom Dashboards</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Explore monitoring data, build custom dashboards, and run ad-hoc SQL queries against ClickHouse.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {DASHBOARDS.map((d) => {
          const Icon = d.icon;
          return (
            <a
              key={d.name}
              href={`${metabaseUrl}${d.path}`}
              target="_blank"
              rel="noopener noreferrer"
              className="block"
            >
              <Card className="hover:border-brand-500/50 transition-colors cursor-pointer h-full">
                <CardHeader className="pb-2">
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-brand-400" />
                    <CardTitle className="text-sm">{d.name}</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-zinc-500">{d.description}</p>
                </CardContent>
              </Card>
            </a>
          );
        })}
      </div>

      <div className="flex items-center gap-4">
        <a
          href={metabaseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm text-brand-400 hover:text-brand-300"
        >
          Open Metabase
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        <a
          href={`${metabaseUrl}/question#new`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-300"
        >
          New SQL Query
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
}
