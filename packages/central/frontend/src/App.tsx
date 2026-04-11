import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { AppLayout } from "@/layouts/AppLayout.tsx";
import { LoginPage } from "@/pages/LoginPage.tsx";
import { DevicesPage } from "@/pages/DevicesPage.tsx";
import { DeviceDetailPage } from "@/pages/DeviceDetailPage.tsx";
import { AppsPage } from "@/pages/AppsPage.tsx";
import { AppDetailPage } from "@/pages/AppDetailPage.tsx";
import { AssignmentsPage } from "@/pages/AssignmentsPage.tsx";
import { AlertsPage } from "@/pages/AlertsPage.tsx";
import { EventsPage } from "@/pages/EventsPage.tsx";
import { IncidentRulesPage } from "@/pages/IncidentRulesPage.tsx";
import { TemplatesPage } from "@/pages/TemplatesPage.tsx";
import { PacksPage } from "@/pages/PacksPage.tsx";
import { PackDetailPage } from "@/pages/PackDetailPage.tsx";
import { PythonModulesPage } from "@/pages/PythonModulesPage.tsx";
import { ConnectorsPage } from "@/pages/ConnectorsPage.tsx";
import { ConnectorDetailPage } from "@/pages/ConnectorDetailPage.tsx";
import { SettingsPage } from "@/pages/SettingsPage.tsx";
import { SystemHealthPage } from "@/pages/SystemHealthPage.tsx";
// DockerInfraPage now lives as a tab in SystemHealthPage
import { DockerInfraPage } from "@/pages/DockerInfraPage.tsx";
import { UpgradesPage } from "@/pages/UpgradesPage.tsx";
import { SQLExplorerPage } from "@/pages/SQLExplorerPage.tsx";
import { CustomDashboardsPage } from "@/pages/CustomDashboardsPage.tsx";
import { DashboardEditorPage } from "@/pages/DashboardEditorPage.tsx";
import { DeviceTypesPage } from "@/pages/DiscoveryRulesPage.tsx";
import { AutomationsPage } from "@/pages/AutomationsPage.tsx";
import { CredentialsPage } from "@/pages/CredentialsPage.tsx";
import { LabelKeysPage } from "@/pages/LabelKeysPage.tsx";

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

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/devices" replace />} />
        <Route path="system-health" element={<SystemHealthPage />} />
        <Route path="docker-infrastructure" element={<DockerInfraPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="devices/:id" element={<DeviceDetailPage />} />
        <Route path="apps" element={<AppsPage />} />
        <Route path="apps/:id" element={<AppDetailPage />} />
        <Route path="connectors" element={<ConnectorsPage />} />
        <Route path="connectors/:id" element={<ConnectorDetailPage />} />
        <Route path="python-modules" element={<PythonModulesPage />} />
        <Route path="assignments" element={<AssignmentsPage />} />
        <Route path="templates" element={<TemplatesPage />} />
        <Route path="credentials" element={<CredentialsPage />} />
        <Route path="labels" element={<LabelKeysPage />} />
        <Route path="packs" element={<PacksPage />} />
        <Route path="packs/:id" element={<PackDetailPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="incident-rules" element={<IncidentRulesPage />} />
        <Route path="analytics/explorer" element={<SQLExplorerPage />} />
        <Route path="analytics/dashboards" element={<CustomDashboardsPage />} />
        <Route
          path="analytics/dashboards/:id"
          element={<DashboardEditorPage />}
        />
        <Route path="automations" element={<AutomationsPage />} />
        <Route path="upgrades" element={<UpgradesPage />} />
        <Route path="device-types" element={<DeviceTypesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/:tab" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
