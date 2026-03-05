import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiGetRaw, apiPost, apiPut } from "@/api/client.ts";
import type {
  ActiveAlert,
  AlertRule,
  AppDetail,
  AppSummary,
  Assignment,
  Collector,
  CollectorGroup,
  Credential,
  Device,
  DeviceAssignment,
  DeviceResults,
  DeviceType,
  HealthStatus,
  MonitoringConfig,
  ResultRecord,
  SnmpOid,
  Tenant,
  User,
  UserWithTenants,
} from "@/types/api.ts";

// ── Polling intervals ────────────────────────────────────

const POLL_LIST = 30_000;    // 30 seconds for list views
const POLL_DETAIL = 15_000;  // 15 seconds for detail views

// ── Devices ──────────────────────────────────────────────

export function useDevices() {
  return useQuery({
    queryKey: ["devices"],
    queryFn: () => apiGet<Device[]>("/devices"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Device Results (detail) ──────────────────────────────

export function useDeviceResults(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["device-results", deviceId],
    queryFn: () => apiGet<DeviceResults>(`/results/by-device/${deviceId}`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

// ── Single Device ────────────────────────────────────────

export function useDevice(id: string | undefined) {
  return useQuery({
    queryKey: ["device", id],
    queryFn: () => apiGet<Device>(`/devices/${id}`),
    select: (res) => res.data,
    enabled: !!id,
    refetchInterval: POLL_LIST,
  });
}

// ── Result History ───────────────────────────────────────

export function useResultHistory(deviceId: string | undefined, limit = 100) {
  return useQuery({
    queryKey: ["results", deviceId, limit],
    queryFn: () =>
      apiGet<ResultRecord[]>(`/results?device_id=${deviceId}&limit=${limit}`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

// ── Latest Results ───────────────────────────────────────

export function useLatestResults() {
  return useQuery({
    queryKey: ["results-latest"],
    queryFn: () => apiGet<ResultRecord[]>("/results/latest"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Collectors ───────────────────────────────────────────

export function useCollectors() {
  return useQuery({
    queryKey: ["collectors"],
    queryFn: () => apiGet<Collector[]>("/collectors"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Assignments ──────────────────────────────────────────

export function useAssignments() {
  return useQuery({
    queryKey: ["assignments"],
    queryFn: () => apiGet<Assignment[]>("/apps/assignments"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Credentials ──────────────────────────────────────────

export function useCredentials() {
  return useQuery({
    queryKey: ["credentials"],
    queryFn: () => apiGet<Credential[]>("/credentials"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Alerts ───────────────────────────────────────────────

export function useActiveAlerts() {
  return useQuery({
    queryKey: ["alerts-active"],
    queryFn: () => apiGet<ActiveAlert[]>("/alerts/active"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useAlertRules() {
  return useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => apiGet<AlertRule[]>("/alerts/rules"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Health ───────────────────────────────────────────────

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiGetRaw<HealthStatus>("/health"),
    refetchInterval: POLL_LIST,
  });
}

// ── Device Types ─────────────────────────────────────────

export function useDeviceTypes() {
  return useQuery({
    queryKey: ["device-types"],
    queryFn: () => apiGet<DeviceType[]>("/device-types"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateDeviceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiPost<DeviceType>("/device-types", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-types"] });
    },
  });
}

export function useDeleteDeviceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/device-types/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-types"] });
    },
  });
}

// ── Tenants ───────────────────────────────────────────────

export function useTenants() {
  return useQuery({
    queryKey: ["tenants"],
    queryFn: () => apiGet<Tenant[]>("/tenants"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string }) =>
      apiPost<Tenant>("/tenants", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

export function useUpdateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiPut<Tenant>(`/tenants/${id}`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

export function useDeleteTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/tenants/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

// ── Collector Groups ───────────────────────────────────────

export function useCollectorGroups() {
  return useQuery({
    queryKey: ["collector-groups"],
    queryFn: () => apiGet<CollectorGroup[]>("/collector-groups"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateCollectorGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiPost<CollectorGroup>("/collector-groups", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collector-groups"] });
    },
  });
}

export function useUpdateCollectorGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string } }) =>
      apiPut<CollectorGroup>(`/collector-groups/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collector-groups"] });
    },
  });
}

export function useDeleteCollectorGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/collector-groups/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collector-groups"] });
      qc.invalidateQueries({ queryKey: ["collectors"] });
    },
  });
}

// ── Collector mutations ────────────────────────────────────

export function useUpdateCollector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; group_id?: string } }) =>
      apiPut<Collector>(`/collectors/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collectors"] });
    },
  });
}

export function useDeleteCollector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/collectors/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collectors"] });
    },
  });
}

// ── Device mutations ──────────────────────────────────────

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      address: string;
      device_type: string;
      tenant_id?: string;
      collector_group_id?: string;
      labels?: Record<string, string>;
    }) => apiPost<Device>("/devices", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/devices/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}

export function useUpdateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<{
        name: string;
        address: string;
        device_type: string;
        tenant_id: string | null;
        collector_group_id: string | null;
        labels: Record<string, string>;
      }>;
    }) => apiPut<Device>(`/devices/${id}`, data),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device", id] });
    },
  });
}

// ── Device detail — time-range history ───────────────────

export function useDeviceHistory(
  deviceId: string | undefined,
  fromTs: string | null,
  toTs: string | null = null,
  limit = 1000,
) {
  return useQuery({
    queryKey: ["device-history", deviceId, fromTs, toTs, limit],
    queryFn: () => {
      const params = new URLSearchParams({
        device_id: deviceId!,
        limit: String(limit),
        ...(fromTs ? { from_ts: fromTs } : {}),
        ...(toTs ? { to_ts: toTs } : {}),
      });
      return apiGet<ResultRecord[]>(`/results?${params}`);
    },
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

// ── Device assignments (for Settings tab) ────────────────

export function useDeviceAssignments(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["device-assignments", deviceId],
    queryFn: () =>
      apiGet<DeviceAssignment[]>(`/apps/assignments?device_id=${deviceId}`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_LIST,
  });
}

export function useDeleteAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/apps/assignments/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
  });
}

// ── Apps list + app detail (for AddAssignmentDialog) ─────

export function useApps() {
  return useQuery({
    queryKey: ["apps"],
    queryFn: () => apiGet<AppSummary[]>("/apps"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useAppDetail(appId: string | undefined) {
  return useQuery({
    queryKey: ["app-detail", appId],
    queryFn: () => apiGet<AppDetail>(`/apps/${appId}`),
    select: (res) => res.data,
    enabled: !!appId,
  });
}

export function useCreateAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      app_id: string;
      app_version_id: string;
      collector_id?: string | null;  // null/omitted = group-level routing
      device_id: string;
      schedule_type: string;
      schedule_value: string;
      config: Record<string, unknown>;
      resource_limits?: Record<string, unknown>;
    }) => apiPost<{ id: string }>("/apps/assignments", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
  });
}

// ── Users (admin only) ────────────────────────────────────

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => apiGet<User[]>("/users"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useUser(id: string | undefined) {
  return useQuery({
    queryKey: ["user", id],
    queryFn: () => apiGet<UserWithTenants>(`/users/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      username: string;
      password: string;
      role: string;
      display_name?: string;
      email?: string;
      all_tenants?: boolean;
    }) => apiPost<User>("/users", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<{
        role: string;
        display_name: string | null;
        email: string | null;
        all_tenants: boolean;
        is_active: boolean;
      }>;
    }) => apiPut<User>(`/users/${id}`, data),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["user", id] });
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/users/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useUserTenants(userId: string | undefined) {
  return useQuery({
    queryKey: ["user-tenants", userId],
    queryFn: () => apiGet<{ id: string; name: string }[]>(`/users/${userId}/tenants`),
    select: (res) => res.data,
    enabled: !!userId,
  });
}

export function useAssignTenantToUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, tenantId }: { userId: string; tenantId: string }) =>
      apiPost(`/users/${userId}/tenants`, { tenant_id: tenantId }),
    onSuccess: (_res, { userId }) => {
      qc.invalidateQueries({ queryKey: ["user-tenants", userId] });
      qc.invalidateQueries({ queryKey: ["user", userId] });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useRemoveTenantFromUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, tenantId }: { userId: string; tenantId: string }) =>
      apiDelete(`/users/${userId}/tenants/${tenantId}`),
    onSuccess: (_res, { userId }) => {
      qc.invalidateQueries({ queryKey: ["user-tenants", userId] });
      qc.invalidateQueries({ queryKey: ["user", userId] });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

// ── SNMP OID Catalog ──────────────────────────────────────

export function useSnmpOids() {
  return useQuery({
    queryKey: ["snmp-oids"],
    queryFn: () => apiGet<SnmpOid[]>("/snmp-oids"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateSnmpOid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; oid: string; description?: string }) =>
      apiPost<SnmpOid>("/snmp-oids", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["snmp-oids"] });
    },
  });
}

export function useUpdateSnmpOid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; oid?: string; description?: string } }) =>
      apiPut<SnmpOid>(`/snmp-oids/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["snmp-oids"] });
    },
  });
}

export function useDeleteSnmpOid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/snmp-oids/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["snmp-oids"] });
    },
  });
}

// ── Device Monitoring Config ──────────────────────────────

export function useDeviceMonitoring(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["device-monitoring", deviceId],
    queryFn: () => apiGet<MonitoringConfig>(`/devices/${deviceId}/monitoring`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_LIST,
  });
}

export function useUpdateDeviceMonitoring() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MonitoringConfig }) =>
      apiPut<MonitoringConfig>(`/devices/${id}/monitoring`, data),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ["device-monitoring", id] });
      qc.invalidateQueries({ queryKey: ["device-assignments", id] });
    },
  });
}
