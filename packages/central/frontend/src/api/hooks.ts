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
  CredentialDetail,
  CredentialKey,
  CredentialTemplate,
  CredentialTemplateField,
  Device,
  DeviceAssignment,
  DeviceListParams,
  DeviceResults,
  DeviceType,
  HealthStatus,
  InterfaceRecord,
  MonitoringConfig,
  RegistrationToken,
  ResultRecord,
  SnmpOid,
  SystemHealthReport,
  SystemSettings,
  Template,
  Tenant,
  TlsCertificateInfo,
  User,
  UserWithTenants,
} from "@/types/api.ts";

// ── Polling intervals ────────────────────────────────────

const POLL_LIST = 30_000;    // 30 seconds for list views
const POLL_DETAIL = 15_000;  // 15 seconds for detail views

// ── Devices ──────────────────────────────────────────────

export function useDevices(params: DeviceListParams = {}) {
  const queryString = new URLSearchParams();
  if (params.limit) queryString.set("limit", String(params.limit));
  if (params.offset !== undefined) queryString.set("offset", String(params.offset));
  if (params.sort_by) queryString.set("sort_by", params.sort_by);
  if (params.sort_dir) queryString.set("sort_dir", params.sort_dir);
  if (params.name) queryString.set("name", params.name);
  if (params.address) queryString.set("address", params.address);
  if (params.device_type) queryString.set("device_type", params.device_type);
  if (params.tenant_name) queryString.set("tenant_name", params.tenant_name);
  if (params.collector_group_name) queryString.set("collector_group_name", params.collector_group_name);
  if (params.label_key) queryString.set("label_key", params.label_key);
  if (params.label_value) queryString.set("label_value", params.label_value);
  if (params.collector_id) queryString.set("collector_id", params.collector_id);
  const qs = queryString.toString();
  return useQuery({
    queryKey: ["devices", params],
    queryFn: () => apiGet<Device[]>(`/devices${qs ? `?${qs}` : ""}`),
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
    mutationFn: (data: { name: string; description?: string; category?: string }) =>
      apiPost<DeviceType>("/device-types", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-types"] });
    },
  });
}

export function useUpdateDeviceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string; category?: string } }) =>
      apiPut<DeviceType>(`/device-types/${id}`, data),
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

// ── Collector approval ─────────────────────────────────────

export function useApproveCollector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, group_id }: { id: string; group_id: string }) =>
      apiPost(`/collectors/${id}/approve`, { group_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collectors"] });
    },
  });
}

export function useRejectCollector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      apiPost(`/collectors/${id}/reject`, { reason }),
    onSuccess: () => {
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
      default_credential_id?: string;
      labels?: Record<string, string>;
    }) => apiPost<Device>("/devices", data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["devices"] });
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

export function useBulkDeleteDevices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceIds: string[]) =>
      apiPost<{ deleted: number }>("/devices/bulk-delete", { device_ids: deviceIds }),
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

// ── Interface Data ───────────────────────────────────────

export function useInterfaceLatest(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["interface-latest", deviceId],
    queryFn: () => apiGet<InterfaceRecord[]>(`/results/interfaces/${deviceId}/latest`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

export function useInterfaceHistory(
  deviceId: string | undefined,
  fromTs: string | null,
  toTs: string | null = null,
  ifIndex: number | null = null,
  limit = 2000,
) {
  return useQuery({
    queryKey: ["interface-history", deviceId, fromTs, toTs, ifIndex, limit],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        ...(fromTs ? { from_ts: fromTs } : {}),
        ...(toTs ? { to_ts: toTs } : {}),
        ...(ifIndex != null ? { if_index: String(ifIndex) } : {}),
      });
      return apiGet<InterfaceRecord[]>(`/results/interfaces/${deviceId}?${params}`);
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

export function useUpdateAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: {
      id: string;
      data: {
        schedule_type?: string;
        schedule_value?: string;
        config?: Record<string, unknown>;
        enabled?: boolean;
        app_version_id?: string;
        use_latest?: boolean;
      };
    }) => apiPut<{ id: string }>(`/apps/assignments/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
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
      use_latest?: boolean;
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

export function useUpdateMyTimezone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (timezone: string) =>
      apiPut<{ timezone: string }>("/users/me/timezone", { timezone }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
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

// ── Registration Tokens ─────────────────────────────────

export function useRegistrationTokens() {
  return useQuery({
    queryKey: ["registration-tokens"],
    queryFn: () => apiGet<RegistrationToken[]>("/registration-tokens"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateRegistrationToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      one_time?: boolean;
      cluster_id?: string;
      expires_at?: string;
    }) => apiPost<RegistrationToken>("/registration-tokens", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registration-tokens"] });
    },
  });
}

export function useDeleteRegistrationToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/registration-tokens/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registration-tokens"] });
    },
  });
}

// ── Credential Keys ─────────────────────────────────────

export function useCredentialKeys() {
  return useQuery({
    queryKey: ["credential-keys"],
    queryFn: () => apiGet<CredentialKey[]>("/credential-keys"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateCredentialKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      key_type: "plain" | "secret" | "enum";
      enum_values?: string[];
    }) => apiPost<CredentialKey>("/credential-keys", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-keys"] });
    },
  });
}

export function useUpdateCredentialKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: {
      id: string;
      data: { name?: string; description?: string; key_type?: string; enum_values?: string[] };
    }) => apiPut<CredentialKey>(`/credential-keys/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-keys"] });
    },
  });
}

export function useDeleteCredentialKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/credential-keys/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-keys"] });
    },
  });
}

// ── Credential mutations ────────────────────────────────

export function useCreateCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      template_id?: string;
      credential_type?: string;
      secret: Record<string, unknown>;
    }) => apiPost<Credential>("/credentials", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });
}

export function useUpdateCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: {
      id: string;
      data: { description?: string; credential_type?: string; secret?: Record<string, unknown> };
    }) => apiPut<Credential>(`/credentials/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });
}

export function useDeleteCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/credentials/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });
}

// ── Credential Templates ────────────────────────────────

export function useCredentialTemplates() {
  return useQuery({
    queryKey: ["credential-templates"],
    queryFn: () => apiGet<CredentialTemplate[]>("/credential-templates"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateCredentialTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string; fields: CredentialTemplateField[] }) =>
      apiPost<CredentialTemplate>("/credential-templates", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-templates"] });
    },
  });
}

export function useUpdateCredentialTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string; fields?: CredentialTemplateField[] } }) =>
      apiPut<CredentialTemplate>(`/credential-templates/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-templates"] });
    },
  });
}

export function useDeleteCredentialTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/credential-templates/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-templates"] });
    },
  });
}

// ── App mutations ───────────────────────────────────────

export function useCreateApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      app_type: string;
      config_schema?: Record<string, unknown>;
      target_table?: string;
    }) => apiPost<{ id: string; name: string }>("/apps", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useUpdateApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: {
      id: string;
      data: { name?: string; description?: string; app_type?: string; config_schema?: Record<string, unknown> };
    }) => apiPut<AppSummary>(`/apps/${id}`, data),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ["apps"] });
      qc.invalidateQueries({ queryKey: ["app-detail", id] });
    },
  });
}

export function useDeleteApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/apps/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useCreateAppVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, data }: {
      appId: string;
      data: { version: string; source_code: string; requirements?: string[]; entry_class?: string };
    }) => apiPost<{ id: string }>(`/apps/${appId}/versions`, data),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
      qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useSetLatestVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, versionId }: { appId: string; versionId: string }) =>
      apiPut<{ id: string }>(`/apps/${appId}/versions/${versionId}/set-latest`, {}),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
    },
  });
}

export function useUpdateAppVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, versionId, data }: {
      appId: string;
      versionId: string;
      data: { source_code?: string; requirements?: string[]; entry_class?: string };
    }) => apiPut<{ id: string }>(`/apps/${appId}/versions/${versionId}`, data),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
    },
  });
}

export function useDeleteAppVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, versionId }: { appId: string; versionId: string }) =>
      apiDelete(`/apps/${appId}/versions/${versionId}`),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
      qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

// ── Update Tenant (extended with metadata) ──────────────

export function useUpdateTenantFull() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; metadata?: Record<string, string> } }) =>
      apiPut<Tenant>(`/tenants/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

// ── System Settings ──────────────────────────────────────

export function useSystemSettings() {
  return useQuery({
    queryKey: ["system-settings"],
    queryFn: () => apiGet<SystemSettings>("/settings"),
    select: (res) => res.data,
  });
}

export function useUpdateSystemSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { settings: Record<string, string> }) =>
      apiPut<SystemSettings>("/settings", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-settings"] });
    },
  });
}

// ── TLS Certificates ─────────────────────────────────────

export function useTlsCertificate() {
  return useQuery({
    queryKey: ["tls-cert"],
    queryFn: () => apiGet<TlsCertificateInfo | null>("/settings/tls"),
    select: (res) => res.data,
  });
}

export function useGenerateTlsCert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { cn?: string }) =>
      apiPost<TlsCertificateInfo>("/settings/tls/generate", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tls-cert"] });
    },
  });
}

export function useUploadTlsCert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; cert_pem: string; key_pem: string }) =>
      apiPost<TlsCertificateInfo>("/settings/tls/upload", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tls-cert"] });
    },
  });
}

export function useDeployTlsCert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ deployed: boolean }>("/settings/tls/deploy", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tls-cert"] });
    },
  });
}

// ── Templates ────────────────────────────────────────────

export function useTemplates() {
  return useQuery({
    queryKey: ["templates"],
    queryFn: () => apiGet<Template[]>("/templates"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string; config: Record<string, unknown> }) =>
      apiPost<Template>("/templates", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

export function useUpdateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string; config?: Record<string, unknown> } }) =>
      apiPut<Template>(`/templates/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/templates/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

export function useApplyTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ templateId, deviceIds }: { templateId: string; deviceIds: string[] }) =>
      apiPost<{ applied: number }>(`/templates/${templateId}/apply`, { device_ids: deviceIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}

// ── Credential Detail ────────────────────────────────────

// ── System Health ────────────────────────────────────────

export function useSystemHealth() {
  return useQuery({
    queryKey: ["system-health"],
    queryFn: () => apiGet<SystemHealthReport>("/system/health"),
    select: (res) => res.data,
    refetchInterval: POLL_DETAIL,
  });
}

// ── Credential Detail ────────────────────────────────────

export function useCredentialDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["credential-detail", id],
    queryFn: () => apiGet<CredentialDetail>(`/credentials/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}
