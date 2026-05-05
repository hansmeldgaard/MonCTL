import { lazy, Suspense } from "react";
import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { AppLayout } from "@/layouts/AppLayout.tsx";
import { LoginPage } from "@/pages/LoginPage.tsx";

// F-WEB-025: lazy-load every page so the initial bundle stays small.
// Pages export their component as a named export — re-map to `default`
// because `React.lazy` only accepts default-export modules.
const _named =
  <T extends string>(name: T) =>
  async (mod: Record<string, unknown>) => ({
    default: mod[name] as React.ComponentType,
  });

const DevicesPage = lazy(() =>
  import("@/pages/DevicesPage.tsx").then(_named("DevicesPage")),
);
const DevicesBetaPage = lazy(() =>
  import("@/pages/DevicesBetaPage.tsx").then(_named("DevicesBetaPage")),
);
const DeviceDetailPage = lazy(() =>
  import("@/pages/DeviceDetailPage.tsx").then(_named("DeviceDetailPage")),
);
const AppsPage = lazy(() =>
  import("@/pages/AppsPage.tsx").then(_named("AppsPage")),
);
const AppDetailPage = lazy(() =>
  import("@/pages/AppDetailPage.tsx").then(_named("AppDetailPage")),
);
const AssignmentsPage = lazy(() =>
  import("@/pages/AssignmentsPage.tsx").then(_named("AssignmentsPage")),
);
const AlertsPage = lazy(() =>
  import("@/pages/AlertsPage.tsx").then(_named("AlertsPage")),
);
const AlertDefinitionDetailPage = lazy(() =>
  import("@/pages/AlertDefinitionDetailPage.tsx").then(
    _named("AlertDefinitionDetailPage"),
  ),
);
const IncidentRulesPage = lazy(() =>
  import("@/pages/IncidentRulesPage.tsx").then(_named("IncidentRulesPage")),
);
const IncidentsPage = lazy(() =>
  import("@/pages/IncidentsPage.tsx").then(_named("IncidentsPage")),
);
const TemplatesPage = lazy(() =>
  import("@/pages/TemplatesPage.tsx").then(_named("TemplatesPage")),
);
const PacksPage = lazy(() =>
  import("@/pages/PacksPage.tsx").then(_named("PacksPage")),
);
const PackDetailPage = lazy(() =>
  import("@/pages/PackDetailPage.tsx").then(_named("PackDetailPage")),
);
const PythonModulesPage = lazy(() =>
  import("@/pages/PythonModulesPage.tsx").then(_named("PythonModulesPage")),
);
const ConnectorsPage = lazy(() =>
  import("@/pages/ConnectorsPage.tsx").then(_named("ConnectorsPage")),
);
const ConnectorDetailPage = lazy(() =>
  import("@/pages/ConnectorDetailPage.tsx").then(_named("ConnectorDetailPage")),
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage.tsx").then(_named("SettingsPage")),
);
const SystemHealthPage = lazy(() =>
  import("@/pages/SystemHealthPage.tsx").then(_named("SystemHealthPage")),
);
const DockerInfraPage = lazy(() =>
  import("@/pages/DockerInfraPage.tsx").then(_named("DockerInfraPage")),
);
const UpgradesPage = lazy(() =>
  import("@/pages/UpgradesPage.tsx").then(_named("UpgradesPage")),
);
const SupersetPage = lazy(() =>
  import("@/pages/SupersetPage.tsx").then(_named("SupersetPage")),
);
const DeviceTypesPage = lazy(() =>
  import("@/pages/DiscoveryRulesPage.tsx").then(_named("DeviceTypesPage")),
);
const AutomationsPage = lazy(() =>
  import("@/pages/AutomationsPage.tsx").then(_named("AutomationsPage")),
);
const CredentialsPage = lazy(() =>
  import("@/pages/CredentialsPage.tsx").then(_named("CredentialsPage")),
);
const LabelKeysPage = lazy(() =>
  import("@/pages/LabelKeysPage.tsx").then(_named("LabelKeysPage")),
);

function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-zinc-400">
      <p className="text-6xl font-bold text-zinc-700">404</p>
      <p className="text-lg">Page not found</p>
      <button
        type="button"
        className="mt-2 rounded-md bg-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
        onClick={() => navigate(-1)}
      >
        Go back
      </button>
    </div>
  );
}

function RouteSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/devices" replace />} />
        <Route
          path="system-health"
          element={
            <RouteSuspense>
              <SystemHealthPage />
            </RouteSuspense>
          }
        />
        <Route
          path="docker-infrastructure"
          element={
            <RouteSuspense>
              <DockerInfraPage />
            </RouteSuspense>
          }
        />
        <Route
          path="devices"
          element={
            <RouteSuspense>
              <DevicesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="devices-beta"
          element={
            <RouteSuspense>
              <DevicesBetaPage />
            </RouteSuspense>
          }
        />
        <Route
          path="devices/:id"
          element={
            <RouteSuspense>
              <DeviceDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="devices/:id/:tab"
          element={
            <RouteSuspense>
              <DeviceDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="apps"
          element={
            <RouteSuspense>
              <AppsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="apps/:id"
          element={
            <RouteSuspense>
              <AppDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="connectors"
          element={
            <RouteSuspense>
              <ConnectorsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="connectors/:id"
          element={
            <RouteSuspense>
              <ConnectorDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="python-modules"
          element={
            <RouteSuspense>
              <PythonModulesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="assignments"
          element={
            <RouteSuspense>
              <AssignmentsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="templates"
          element={
            <RouteSuspense>
              <TemplatesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="credentials"
          element={
            <RouteSuspense>
              <CredentialsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="labels"
          element={
            <RouteSuspense>
              <LabelKeysPage />
            </RouteSuspense>
          }
        />
        <Route
          path="packs"
          element={
            <RouteSuspense>
              <PacksPage />
            </RouteSuspense>
          }
        />
        <Route
          path="packs/:id"
          element={
            <RouteSuspense>
              <PackDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="alerts"
          element={
            <RouteSuspense>
              <AlertsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="alerts/definitions/:id"
          element={
            <RouteSuspense>
              <AlertDefinitionDetailPage />
            </RouteSuspense>
          }
        />
        <Route
          path="incident-rules"
          element={
            <RouteSuspense>
              <IncidentRulesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="incidents"
          element={
            <RouteSuspense>
              <IncidentsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="analytics/superset"
          element={
            <RouteSuspense>
              <SupersetPage />
            </RouteSuspense>
          }
        />
        <Route
          path="automations"
          element={
            <RouteSuspense>
              <AutomationsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="upgrades"
          element={
            <RouteSuspense>
              <UpgradesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="device-types"
          element={
            <RouteSuspense>
              <DeviceTypesPage />
            </RouteSuspense>
          }
        />
        <Route
          path="settings"
          element={
            <RouteSuspense>
              <SettingsPage />
            </RouteSuspense>
          }
        />
        <Route
          path="settings/:tab"
          element={
            <RouteSuspense>
              <SettingsPage />
            </RouteSuspense>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
