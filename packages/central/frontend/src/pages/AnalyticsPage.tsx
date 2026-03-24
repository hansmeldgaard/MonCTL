import { ExternalLink, BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { useSystemSettings } from "@/api/hooks.ts";

const dashboards = [
  {
    name: "Device Performance",
    path: "/d/device-performance",
    description: "CPU, memory, disk metrics per device over time",
  },
  {
    name: "Interface Traffic",
    path: "/d/interface-traffic",
    description: "Bandwidth, errors, utilization per interface",
  },
  {
    name: "Availability Overview",
    path: "/d/availability-overview",
    description: "Uptime, response times, reachability heatmap",
  },
  {
    name: "Alert History",
    path: "/d/alert-history",
    description: "Alert trends, noisiest rules, duration analysis",
  },
];

export function AnalyticsPage() {
  const { data: systemSettings } = useSystemSettings();
  const grafanaUrl = systemSettings?.grafana_url || "";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">
          Analytics & Custom Dashboards
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Build custom dashboards, explore metrics, and run ad-hoc queries
          against your monitoring data.
        </p>
      </div>

      {!grafanaUrl ? (
        <Card>
          <CardContent className="py-8">
            <div className="flex flex-col items-center justify-center text-zinc-500">
              <BarChart3 className="mb-3 h-10 w-10 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-400">
                Grafana not configured
              </p>
              <p className="mt-1 text-xs">
                Set the <code className="rounded bg-zinc-800 px-1 py-0.5">grafana_url</code> in
                Settings to enable analytics dashboards.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {dashboards.map((d) => (
              <a
                key={d.path}
                href={`${grafanaUrl}${d.path}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block"
              >
                <Card className="hover:border-brand-500/50 transition-colors cursor-pointer h-full">
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      {d.name}
                      <ExternalLink className="h-3 w-3 text-zinc-600" />
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xs text-zinc-500">{d.description}</p>
                  </CardContent>
                </Card>
              </a>
            ))}
          </div>

          <a
            href={grafanaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-brand-400 hover:text-brand-300"
          >
            Open Grafana Dashboard Builder
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </>
      )}
    </div>
  );
}
