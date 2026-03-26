import { Routes, Route } from "react-router-dom";
import { AppLayout } from "@/layouts/AppLayout.tsx";
import { LoginPage } from "@/pages/LoginPage.tsx";
import { DashboardPage } from "@/pages/DashboardPage.tsx";
import { DevicesPage } from "@/pages/DevicesPage.tsx";
import { DeviceDetailPage } from "@/pages/DeviceDetailPage.tsx";
import { AppsPage } from "@/pages/AppsPage.tsx";
import { AppDetailPage } from "@/pages/AppDetailPage.tsx";
import { AssignmentsPage } from "@/pages/AssignmentsPage.tsx";
import { AlertsPage } from "@/pages/AlertsPage.tsx";
import { EventsPage } from "@/pages/EventsPage.tsx";
import { TemplatesPage } from "@/pages/TemplatesPage.tsx";
import { PacksPage } from "@/pages/PacksPage.tsx";
import { PackDetailPage } from "@/pages/PackDetailPage.tsx";
import { PythonModulesPage } from "@/pages/PythonModulesPage.tsx";
import { ConnectorsPage } from "@/pages/ConnectorsPage.tsx";
import { ConnectorDetailPage } from "@/pages/ConnectorDetailPage.tsx";
import { SettingsPage } from "@/pages/SettingsPage.tsx";
import { SystemHealthPage } from "@/pages/SystemHealthPage.tsx";
import { DockerInfraPage } from "@/pages/DockerInfraPage.tsx";
import { UpgradesPage } from "@/pages/UpgradesPage.tsx";
import { SQLExplorerPage } from "@/pages/SQLExplorerPage.tsx";
import { CustomDashboardsPage } from "@/pages/CustomDashboardsPage.tsx";
import { DashboardEditorPage } from "@/pages/DashboardEditorPage.tsx";
import { DeviceTypesPage } from "@/pages/DiscoveryRulesPage.tsx";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
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
        <Route path="packs" element={<PacksPage />} />
        <Route path="packs/:id" element={<PackDetailPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="analytics/explorer" element={<SQLExplorerPage />} />
        <Route path="analytics/dashboards" element={<CustomDashboardsPage />} />
        <Route path="analytics/dashboards/:id" element={<DashboardEditorPage />} />
        <Route path="upgrades" element={<UpgradesPage />} />
        <Route path="device-types" element={<DeviceTypesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/:tab" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
