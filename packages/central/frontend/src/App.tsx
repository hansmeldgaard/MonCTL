import { Routes, Route } from "react-router-dom";
import { AppLayout } from "@/layouts/AppLayout.tsx";
import { LoginPage } from "@/pages/LoginPage.tsx";
import { DashboardPage } from "@/pages/DashboardPage.tsx";
import { DevicesPage } from "@/pages/DevicesPage.tsx";
import { DeviceDetailPage } from "@/pages/DeviceDetailPage.tsx";
import { DeviceTypesPage } from "@/pages/DeviceTypesPage.tsx";
import { CollectorsPage } from "@/pages/CollectorsPage.tsx";
import { AssignmentsPage } from "@/pages/AssignmentsPage.tsx";
import { CredentialsPage } from "@/pages/CredentialsPage.tsx";
import { AlertsPage } from "@/pages/AlertsPage.tsx";
import { SettingsPage } from "@/pages/SettingsPage.tsx";
import { UsersPage } from "@/pages/UsersPage.tsx";
import { TenantsPage } from "@/pages/TenantsPage.tsx";
import { SnmpOidsPage } from "@/pages/SnmpOidsPage.tsx";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="devices/:id" element={<DeviceDetailPage />} />
        <Route path="device-types" element={<DeviceTypesPage />} />
        <Route path="collectors" element={<CollectorsPage />} />
        <Route path="assignments" element={<AssignmentsPage />} />
        <Route path="credentials" element={<CredentialsPage />} />
        <Route path="snmp-oids" element={<SnmpOidsPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="tenants" element={<TenantsPage />} />
      </Route>
    </Routes>
  );
}
