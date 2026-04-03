import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiGetRaw, apiPatch, apiPost, apiPostFormData, apiPut } from "@/api/client.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import type {
  AlertInstance,
  AlertLogEntry,
  AlertMetric,
  AppAlertDefinition,
  AppDetail,
  AppSummary,
  Assignment,
  Collector,
  CollectorGroup,
  ConfigKeysResponse,
  Credential,
  CredentialDetail,
  CredentialKey,
  CredentialTemplate,
  CredentialType,
  CredentialTemplateField,
  Device,
  DeviceAssignment,
  DeviceListParams,
  DeviceThresholdRow,
  ThresholdVariable,
  DisplayTemplate,
  DeviceResults,
  DeviceCategory,
  DeviceType,
  ExpressionValidation,
  HealthStatus,
  InterfaceMetadataRecord,
  InterfaceRecord,
  LabelKey,
  MonitoringConfig,
  NetworkStatus,
  PyPISearchResult,
  PythonModuleDetail,
  PythonModuleSummary,
  RegistrationToken,
  ResolveResult,
  ResourceActions,
  ResultRecord,
  Role,
  UserApiKey,
  UserApiKeyWithRaw,
  WheelUploadResult,
  SnmpOid,
  SystemHealthReport,
  SystemSettings,
  Template,
  Tenant,
  TlsCertificateInfo,
  User,
  UserWithTenants,
  ConnectorSummary,
  ConnectorDetail,
  MonitoringEvent,
  EventPolicy,
  Pack,
  PackDetail,
  PackImportPreview,
  PackImportResult,
  PerformanceAppSummary,
  PerformanceRecord,
  AvailableEntities,
  DockerHostInfo,
  DockerOverviewResponse,
  DockerSystemInfo,
  DockerContainerLog,
  DockerEventsResponse,
  DockerImagesResponse,
  ListParams,
  BulkUpdateAssignmentsRequest,
  ConfigChangeEntry,
  ConfigChangeTimestamp,
  ConfigCompareResult,
  DeviceRetentionEntry,
  RetentionDefaults,
  UpgradeStatus,
  UpgradePackageInfo,
  UpgradeJob,
  OsPackageInfo,
  OsUpdateByNode,
  OsCheckResult,
  OsCachedPkg,
  OsInstallResult,
  OsInstallJob,
  PackageInventoryItem,
  UpgradeBadge,
  DashboardSummary,
  DeviceCategoryListMeta,
  DeviceCategoryCounts,
  LogQueryResponse,
  LogFiltersResponse,
  CollectorWsStatus,
  CollectorWsConnection,
  AnalyticsTable,
  QueryResult,
  AnalyticsDashboardSummary,
  AnalyticsDashboard,
  Action,
  Automation,
  AutomationRun,
  TemplateBinding,
  ResolvedTemplateResult,
  EligibilityOidCheck,
  EligibilityRun,
  EligibilityDeviceResult,
  InterfaceRule,
  InterfaceRuleEvaluationSummary,
  InterfaceRulePreviewItem,
} from "@/types/api.ts";

function buildListQs(params: ListParams): string {
  const qs = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== "") qs.set(key, String(val));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

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
  if (params.device_category) queryString.set("device_category", params.device_category);
  if (params.device_type_name) queryString.set("device_type_name", params.device_type_name);
  if (params.tenant_name) queryString.set("tenant_name", params.tenant_name);
  if (params.collector_group_name) queryString.set("collector_group_name", params.collector_group_name);
  if (params.label_key) queryString.set("label_key", params.label_key);
  if (params.label_value) queryString.set("label_value", params.label_value);
  if (params.collector_id) queryString.set("collector_id", params.collector_id);
  const qs = queryString.toString();
  return useQuery({
    queryKey: ["devices", params],
    queryFn: () => apiGet<Device[]>(`/devices${qs ? `?${qs}` : ""}`),
    placeholderData: keepPreviousData,
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

// ── Device Config Data (from config table) ──────────────

export function useDeviceConfigData(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["device-config-data", deviceId],
    queryFn: () =>
      apiGet<Record<string, unknown>[]>(`/results/latest?table=config&device_id=${deviceId}`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

export function useDeviceConfigTemplates(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["device-config-templates", deviceId],
    queryFn: () =>
      apiGet<Record<string, {
        app_name: string;
        version: string;
        display_template: { html: string; css: string | null; key_mappings: string[] } | null;
      }>>(`/apps/config-templates?device_id=${deviceId}`),
    select: (res) => res.data,
    enabled: !!deviceId,
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

export function useCollectors(params?: { group_id?: string }) {
  const qp = params?.group_id ? `?group_id=${params.group_id}` : "";
  return useQuery({
    queryKey: ["collectors", params?.group_id ?? null],
    queryFn: () => apiGet<Collector[]>(`/collectors${qp}`),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

// ── Assignments ──────────────────────────────────────────

export function useAssignments(params: ListParams = {}) {
  return useQuery({
    queryKey: ["assignments", params],
    queryFn: () => apiGet<Assignment[]>(`/apps/assignments${buildListQs(params)}`),
    placeholderData: keepPreviousData,
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

export function useCredentialTypes() {
  return useQuery({
    queryKey: ["credential-types"],
    queryFn: () => apiGet<CredentialType[]>("/credentials/types"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateCredentialType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiPost<CredentialType>("/credentials/types", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-types"] });
    },
  });
}

export function useUpdateCredentialType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name: string; description?: string } }) =>
      apiPut<CredentialType>(`/credentials/types/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-types"] });
      qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });
}

export function useDeleteCredentialType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/credentials/types/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-types"] });
    },
  });
}

// ── Alerts ───────────────────────────────────────────────

export function useActiveAlerts() {
  return useQuery({
    queryKey: ["alert-instances-active"],
    queryFn: () => apiGet<AlertInstance[]>("/alerts/instances/active"),
    select: (res) => res.data,
    refetchInterval: POLL_DETAIL,
  });
}

export function useAlertRules(params: ListParams = {}) {
  return useQuery({
    queryKey: ["alert-definitions", params],
    queryFn: () => apiGet<AppAlertDefinition[]>(`/alerts/definitions${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useAlertDefinitions(appId?: string) {
  const params = appId ? `?app_id=${appId}` : "";
  return useQuery({
    queryKey: ["alert-definitions", appId ?? "all"],
    queryFn: () => apiGet<AppAlertDefinition[]>(`/alerts/definitions${params}`),
    refetchInterval: POLL_LIST,
  });
}

export function useAlertDefinition(id: string) {
  return useQuery({
    queryKey: ["alert-definition", id],
    queryFn: () => apiGet<AppAlertDefinition & { instances: AlertInstance[] }>(`/alerts/definitions/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateAlertDefinition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      app_id: string;
      name: string;
      expression: string;
      window?: string;
      severity?: string;
      enabled?: boolean;
      description?: string;
      message_template?: string;
    }) => apiPost("/alerts/definitions", data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["alert-definitions"] });
      await qc.invalidateQueries({ queryKey: ["alert-instances-active"] });
    },
  });
}

export function useUpdateAlertDefinition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      apiPut(`/alerts/definitions/${id}`, data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["alert-definitions"] });
    },
  });
}

export function useDeleteAlertDefinition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/alerts/definitions/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["alert-definitions"] });
      await qc.invalidateQueries({ queryKey: ["alert-instances-active"] });
    },
  });
}

export function useInvertAlertDefinition() {
  return useMutation({
    mutationFn: (definitionId: string) =>
      apiPost<{
        suggested_name: string;
        inverted_expression: string;
        original_expression: string;
        window: string;
        severity: string;
        app_id: string;
      }>(`/alerts/definitions/${definitionId}/invert`, {}),
  });
}

export function useResolvedAlertInstances(params?: {
  severity?: string;
  device_id?: string;
  limit?: number;
}) {
  const search = new URLSearchParams();
  if (params?.severity) search.set("severity", params.severity);
  if (params?.device_id) search.set("device_id", params.device_id);
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return useQuery({
    queryKey: ["alert-instances-resolved", params ?? {}],
    queryFn: () => apiGet<AlertInstance[]>(`/alerts/instances/resolved${qs ? `?${qs}` : ""}`),
    select: (res) => ({ data: res.data, meta: (res as unknown as { meta?: { retention_days: number } }).meta }),
    refetchInterval: POLL_LIST,
  });
}

export function useAlertInstances(params?: {
  state?: string;
  device_id?: string;
  definition_id?: string;
  [key: string]: string | number | undefined;
}) {
  const search = new URLSearchParams();
  if (params) {
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== "") search.set(key, String(val));
    }
  }
  const qs = search.toString();
  return useQuery({
    queryKey: ["alert-instances", params ?? {}],
    queryFn: () => apiGet<AlertInstance[]>(`/alerts/instances${qs ? `?${qs}` : ""}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useUpdateAlertInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPut(`/alerts/instances/${id}`, { enabled }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["alert-instances"] });
      await qc.invalidateQueries({ queryKey: ["alert-instances-active"] });
      await qc.invalidateQueries({ queryKey: ["device-thresholds"] });
    },
  });
}

export function useValidateExpression() {
  return useMutation({
    mutationFn: (data: { expression: string; target_table: string }) =>
      apiPost<ExpressionValidation>("/alerts/validate-expression", data),
  });
}

// ── Alert Log (ClickHouse fire/clear history) ───────────

export function useAlertLog(params?: {
  definition_id?: string; entity_key?: string; device_id?: string;
  action?: string; from?: string; to?: string;
  limit?: number; offset?: number;
}) {
  return useQuery({
    queryKey: ["alert-log", params],
    queryFn: () => {
      const search = new URLSearchParams();
      if (params?.definition_id) search.set("definition_id", params.definition_id);
      if (params?.entity_key) search.set("entity_key", params.entity_key);
      if (params?.device_id) search.set("device_id", params.device_id);
      if (params?.action) search.set("action", params.action);
      if (params?.from) search.set("from", params.from);
      if (params?.to) search.set("to", params.to);
      if (params?.limit) search.set("limit", String(params.limit));
      if (params?.offset) search.set("offset", String(params.offset));
      return apiGet<AlertLogEntry[]>(`/alerts/log?${search.toString()}`);
    },
    placeholderData: keepPreviousData,
  });
}

export function useDeviceAlertLog(
  deviceId: string,
  params: ListParams = {},
  extra?: { action?: string },
) {
  return useQuery({
    queryKey: ["alert-log", "device", deviceId, params, extra],
    queryFn: () => {
      const search = new URLSearchParams();
      search.set("device_id", deviceId);
      if (extra?.action) search.set("action", extra.action);
      for (const [key, val] of Object.entries(params)) {
        if (val !== undefined && val !== "") search.set(key, String(val));
      }
      return apiGet<AlertLogEntry[]>(`/alerts/log?${search.toString()}`);
    },
    placeholderData: keepPreviousData,
    enabled: !!deviceId,
  });
}

export function useDeviceActiveEvents(
  deviceId: string,
  params: ListParams = {},
) {
  return useQuery({
    queryKey: ["events-active", "device", deviceId, params],
    queryFn: () => {
      const qs = buildListQs(params);
      const sep = qs.includes("?") ? "&" : "?";
      return apiGet<MonitoringEvent[]>(`/events/active${qs}${sep}device_id=${deviceId}`);
    },
    placeholderData: keepPreviousData,
    enabled: !!deviceId,
    refetchInterval: POLL_LIST,
  });
}

export function useDeviceClearedEvents(
  deviceId: string,
  params: ListParams = {},
) {
  return useQuery({
    queryKey: ["events-cleared", "device", deviceId, params],
    queryFn: () => {
      const qs = buildListQs(params);
      const sep = qs.includes("?") ? "&" : "?";
      return apiGet<MonitoringEvent[]>(`/events/cleared${qs}${sep}device_id=${deviceId}`);
    },
    placeholderData: keepPreviousData,
    enabled: !!deviceId,
    refetchInterval: POLL_LIST,
  });
}

export function useAlertMetrics(appId: string) {
  return useQuery({
    queryKey: ["alert-metrics", appId],
    queryFn: () => apiGet<AlertMetric[]>(`/apps/${appId}/alert-metrics`),
    select: (res) => res.data,
    enabled: !!appId,
  });
}

export function useDeviceThresholds(deviceId: string) {
  return useQuery({
    queryKey: ["device-thresholds", deviceId],
    queryFn: () => apiGet<DeviceThresholdRow[]>(`/devices/${deviceId}/thresholds`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_LIST,
  });
}

// ── App Threshold Variables ─────────────────────────────

export function useAppThresholds(appId: string) {
  return useQuery({
    queryKey: ["app-thresholds", appId],
    queryFn: () => apiGet<ThresholdVariable[]>(`/apps/${appId}/thresholds`),
    select: (res) => res.data,
    enabled: !!appId,
  });
}

export function useUpdateThresholdVariable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      appId, varId, ...data
    }: {
      appId: string; varId: string;
      default_value?: number; app_value?: number | null;
      clear_app_value?: boolean; display_name?: string;
      description?: string; unit?: string;
    }) =>
      apiPut(`/apps/${appId}/thresholds/${varId}`, data),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["app-thresholds", vars.appId] });
      qc.invalidateQueries({ queryKey: ["device-thresholds"] });
    },
  });
}

export function useCreateThresholdVariable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, ...data }: {
      appId: string; name: string; default_value: number;
      display_name?: string; unit?: string; description?: string
    }) => apiPost(`/apps/${appId}/thresholds`, data),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["app-thresholds", vars.appId] });
    },
  });
}

export function useDeleteThresholdVariable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, varId }: { appId: string; varId: string }) =>
      apiDelete(`/apps/${appId}/thresholds/${varId}`),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["app-thresholds", vars.appId] });
    },
  });
}

export function useCreateThresholdOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { variable_id: string; device_id: string; entity_key?: string; value: number }) =>
      apiPost("/alerts/overrides", data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["device-thresholds"] });
      await qc.invalidateQueries({ queryKey: ["app-thresholds"] });
    },
  });
}

export function useUpdateThresholdOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, value }: { id: string; value: number }) =>
      apiPut(`/alerts/overrides/${id}`, { value }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["device-thresholds"] });
    },
  });
}

export function useDeleteThresholdOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/alerts/overrides/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["device-thresholds"] });
    },
  });
}

// ── Performance Data ─────────────────────────────────────

export function usePerformanceSummary(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["performance-summary", deviceId],
    queryFn: () => apiGet<PerformanceAppSummary[]>(`/results/performance/${deviceId}/summary`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: 60_000,
  });
}

export function usePerformanceHistory(
  deviceId: string | undefined,
  fromTs: string | null,
  toTs: string | null = null,
  appId: string | null = null,
  componentType: string | null = null,
  components: string[] | null = null,
  limit = 5000,
) {
  return useQuery({
    queryKey: ["performance-history", deviceId, fromTs, toTs, appId, componentType, components, limit],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (fromTs) params.set("from_ts", fromTs);
      if (toTs) params.set("to_ts", toTs);
      if (appId) params.set("app_id", appId);
      if (componentType) params.set("component_type", componentType);
      if (components?.length) params.set("component", components.join(","));
      return apiGet<PerformanceRecord[]>(`/results/performance/${deviceId}?${params}`);
    },
    select: (res) => res.data,
    enabled: !!deviceId && !!fromTs,
    refetchInterval: POLL_DETAIL,
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

// ── Device Categories (groupings) ────────────────────────

export function useDeviceCategories() {
  return useQuery({
    queryKey: ["device-categories"],
    queryFn: () => apiGet<DeviceCategory[]>("/device-categories"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateDeviceCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string; category?: string; icon?: string }) =>
      apiPost<DeviceCategory>("/device-categories", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-categories"] });
    },
  });
}

export function useUpdateDeviceCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string; category?: string; icon?: string } }) =>
      apiPut<DeviceCategory>(`/device-categories/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-categories"] });
    },
  });
}

export function useDeleteDeviceCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/device-categories/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-categories"] });
    },
  });
}

export function useUploadDeviceCategoryIcon() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiPostFormData<DeviceCategory>(`/device-categories/${id}/icon`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-categories"] });
    },
  });
}

export function useDeleteDeviceCategoryIcon() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/device-categories/${id}/icon`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-categories"] });
    },
  });
}

export function useDeviceCategoryList(params: ListParams) {
  const qs = buildListQs(params);
  return useQuery<{ status: string; data: DeviceCategory[]; meta: DeviceCategoryListMeta }>({
    queryKey: ["device-categories", "list", params],
    queryFn: () => apiGetRaw(`/device-categories${qs}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useDeviceCategoryCounts(search?: string) {
  const qs = search ? `?search=${encodeURIComponent(search)}` : "";
  return useQuery({
    queryKey: ["device-categories", "categories", search ?? ""],
    queryFn: () => apiGet<DeviceCategoryCounts>(`/device-categories/categories${qs}`),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
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
      device_category?: string;
      tenant_id?: string;
      collector_group_id?: string;
      device_type_id?: string;
      credentials?: Record<string, string>;
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

export function useBulkPatchDevices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: import("@/types/api.ts").DeviceBulkPatchRequest) =>
      apiPost<import("@/types/api.ts").DeviceBulkPatchResult>("/devices/bulk-patch", body),
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
        device_category: string;
        device_type_id: string | null;
        tenant_id: string | null;
        collector_group_id: string | null;
        credentials: Record<string, string>;
        labels: Record<string, string>;
        retention_overrides: Record<string, string>;
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
  table?: string,
) {
  return useQuery({
    queryKey: ["device-history", deviceId, fromTs, toTs, limit, table],
    queryFn: () => {
      const params = new URLSearchParams({
        device_id: deviceId!,
        limit: String(limit),
        ...(table ? { table } : {}),
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

/**
 * Fetch history from the availability_latency table ONLY.
 * Used by the Overview tab's AvailabilityChart.
 */
export function useAvailabilityHistory(
  deviceId: string | undefined,
  fromTs: string | null,
  toTs: string | null = null,
  limit = 20000,
) {
  return useQuery({
    queryKey: ["availability-history", deviceId, fromTs, toTs, limit],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        ...(fromTs ? { from_ts: fromTs } : {}),
        ...(toTs ? { to_ts: toTs } : {}),
      });
      return apiGet<ResultRecord[]>(`/results/availability/${deviceId}?${params}`);
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
  interfaceId: string | null = null,
  limit = 2000,
) {
  return useQuery({
    queryKey: ["interface-history", deviceId, fromTs, toTs, interfaceId, limit],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        ...(fromTs ? { from_ts: fromTs } : {}),
        ...(toTs ? { to_ts: toTs } : {}),
        ...(interfaceId != null ? { interface_id: interfaceId } : {}),
      });
      return apiGet<InterfaceRecord[]>(`/results/interfaces/${deviceId}?${params}`);
    },
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

// ── Interface Metadata ───────────────────────────────────

export function useInterfaceMetadata(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["interface-metadata", deviceId],
    queryFn: () => apiGet<InterfaceMetadataRecord[]>(`/devices/${deviceId}/interface-metadata`),
    select: (res) => res.data,
    enabled: !!deviceId,
    refetchInterval: POLL_DETAIL,
  });
}

export function useUpdateInterfaceSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      interfaceId,
      data,
    }: {
      deviceId: string;
      interfaceId: string;
      data: { polling_enabled?: boolean; alerting_enabled?: boolean; poll_metrics?: string };
    }) => apiPatch(`/devices/${deviceId}/interface-metadata/${interfaceId}`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["interface-metadata", vars.deviceId] });
    },
  });
}

export function useBulkUpdateInterfaceSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      data,
    }: {
      deviceId: string;
      data: { interface_ids: string[]; polling_enabled?: boolean; alerting_enabled?: boolean; poll_metrics?: string };
    }) => apiPatch(`/devices/${deviceId}/interface-metadata`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["interface-metadata", vars.deviceId] });
    },
  });
}

export function useRefreshInterfaceMetadata() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) =>
      apiPost(`/devices/${deviceId}/interface-metadata/refresh`),
    onSuccess: (_res, deviceId) => {
      qc.invalidateQueries({ queryKey: ["interface-metadata", deviceId] });
    },
  });
}

// ── Interface Rules ──────────────────────────────────────

export function useDeviceInterfaceRules(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["interface-rules", deviceId],
    queryFn: () => apiGet<InterfaceRule[]>(`/devices/${deviceId}/interface-rules`),
    select: (res) => res.data,
    enabled: !!deviceId,
  });
}

export function useSetDeviceInterfaceRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, data }: {
      deviceId: string;
      data: { interface_rules: InterfaceRule[]; apply_now?: boolean };
    }) => apiPut(`/devices/${deviceId}/interface-rules`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["interface-rules", vars.deviceId] });
      qc.invalidateQueries({ queryKey: ["interface-metadata", vars.deviceId] });
    },
  });
}

export function useEvaluateInterfaceRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, force = false }: {
      deviceId: string;
      force?: boolean;
    }) => apiPost<InterfaceRuleEvaluationSummary>(`/devices/${deviceId}/interface-rules/evaluate`, { force }),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["interface-metadata", vars.deviceId] });
    },
  });
}

export function usePreviewInterfaceRules(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["interface-rules-preview", deviceId],
    queryFn: () => apiPost<InterfaceRulePreviewItem[]>(`/devices/${deviceId}/interface-rules/preview`),
    select: (res) => res.data,
    enabled: false, // manual trigger only
  });
}

export function useMultiInterfaceHistory(
  deviceId: string | undefined,
  fromTs: string | null,
  toTs: string | null = null,
  interfaceIds: string[] = [],
  limit = 2000,
) {
  return useQuery({
    queryKey: ["interface-history-multi", deviceId, fromTs, toTs, interfaceIds, limit],
    queryFn: async () => {
      const perIface = Math.max(200, Math.floor(limit / interfaceIds.length));
      const results = await Promise.all(
        interfaceIds.map((ifaceId) => {
          const params = new URLSearchParams({
            limit: String(perIface),
            ...(fromTs ? { from_ts: fromTs } : {}),
            ...(toTs ? { to_ts: toTs } : {}),
            interface_id: ifaceId,
          });
          return apiGet<InterfaceRecord[]>(`/results/interfaces/${deviceId}?${params}`);
        })
      );
      return results.map((r) => r.data);
    },
    enabled: !!deviceId && interfaceIds.length > 0,
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
        collector_id?: string | null;
        credential_id?: string | null;
        connector_bindings?: { alias: string; connector_id: string; connector_version_id: string; credential_id?: string | null; use_latest?: boolean; settings?: Record<string, unknown> }[];
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

export function useBulkUpdateAssignments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: BulkUpdateAssignmentsRequest) =>
      apiPut<{ updated: number }>("/apps/assignments/bulk-update", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assignments"] });
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
  });
}

export function useBulkDeleteAssignments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assignmentIds: string[]) =>
      apiPost<{ deleted: number }>("/apps/assignments/bulk-delete", { assignment_ids: assignmentIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assignments"] });
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
  });
}

// ── Apps list + app detail (for AddAssignmentDialog) ─────

export function useApps(params: ListParams = {}) {
  return useQuery({
    queryKey: ["apps", params],
    queryFn: () => apiGet<AppSummary[]>(`/apps${buildListQs(params)}`),
    placeholderData: keepPreviousData,
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
      credential_id?: string | null;
      connector_bindings?: { alias: string; connector_id: string; connector_version_id?: string | null; credential_id?: string | null; use_latest?: boolean; settings?: Record<string, unknown> }[];
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
      role_id?: string;
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
        role_id: string | null;
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

export function useUpdateMyDefaultPage() {
  return useMutation({
    mutationFn: (default_page: string) =>
      apiPut<{ default_page: string }>("/users/me/default-page", { default_page }),
  });
}

export function useUpdateMyIdleTimeout() {
  return useMutation({
    mutationFn: (data: { idle_timeout_minutes: number | null }) =>
      apiPut<{ idle_timeout_minutes: number | null }>("/users/me/idle-timeout", data),
  });
}

export function useChangeMyPassword() {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      apiPut<{ message: string }>("/users/me/password", data),
  });
}

export function useUpdateInterfacePreferences() {
  const { refresh } = useAuth();
  return useMutation({
    mutationFn: (data: {
      iface_status_filter?: "all" | "up" | "down" | "unmonitored";
      iface_traffic_unit?: "auto" | "kbps" | "mbps" | "gbps" | "pct";
      iface_chart_metric?: "traffic" | "errors" | "discards";
      iface_time_range?: "1h" | "6h" | "24h" | "7d" | "30d";
    }) => apiPut("/users/me/interface-preferences", data),
    onSuccess: async () => {
      await refresh();
    },
  });
}

export function useUpdateTablePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { table_page_size?: number; table_scroll_mode?: "paginated" | "infinite" }) =>
      apiPut<{ table_page_size: number; table_scroll_mode: string }>("/users/me/table-preferences", data),
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

// ── Roles (RBAC) ────────────────────────────────────────

export function useRoles() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: () => apiGet<Role[]>("/roles"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useRoleResources() {
  return useQuery({
    queryKey: ["role-resources"],
    queryFn: () => apiGet<ResourceActions>("/roles/resources"),
    select: (res) => res.data,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      permissions: { resource: string; action: string }[];
    }) => apiPost<Role>("/roles", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
    },
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: {
        name?: string;
        description?: string;
        permissions?: { resource: string; action: string }[];
      };
    }) => apiPut<Role>(`/roles/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
    },
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/roles/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
    },
  });
}

// ── User API Keys ────────────────────────────────────────

export function useUserApiKeys() {
  return useQuery({
    queryKey: ["user-api-keys"],
    queryFn: () => apiGet<UserApiKey[]>("/user-api-keys"),
    select: (res) => res.data,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateUserApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; expires_at?: string | null }) =>
      apiPost<UserApiKeyWithRaw>("/user-api-keys", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-api-keys"] });
    },
  });
}

export function useDeleteUserApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/user-api-keys/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-api-keys"] });
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

export function useCollectorSetupContext() {
  return useQuery({
    queryKey: ["collector-setup-context"],
    queryFn: () => apiGet<{ collector_api_key: string; central_url: string }>("/collectors/setup-context"),
    select: (res) => res.data,
    enabled: false,
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
    mutationFn: (data: { name: string; credential_type?: string; description?: string; fields: CredentialTemplateField[] }) =>
      apiPost<CredentialTemplate>("/credential-templates", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credential-templates"] });
    },
  });
}

export function useUpdateCredentialTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; credential_type?: string; description?: string; fields?: CredentialTemplateField[] } }) =>
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
      data: { name?: string; description?: string; app_type?: string; config_schema?: Record<string, unknown>; vendor_oid_prefix?: string | null };
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

// ── App connector binding hooks ──────────────────────────────────────────

export function useAddAppConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, data }: {
      appId: string;
      data: { alias: string; connector_id: string; use_latest?: boolean; connector_version_id?: string | null; settings?: Record<string, unknown> };
    }) => apiPost(`/apps/${appId}/connectors`, data),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
    },
  });
}

export function useDeleteAppConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, alias }: { appId: string; alias: string }) =>
      apiDelete(`/apps/${appId}/connectors/${alias}`),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
    },
  });
}

export function useCreateAppVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, data }: {
      appId: string;
      data: { version: string; source_code: string; requirements?: string[]; entry_class?: string; display_template?: DisplayTemplate; volatile_keys?: string[]; eligibility_oids?: EligibilityOidCheck[] };
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
      data: { source_code?: string; requirements?: string[]; entry_class?: string; display_template?: DisplayTemplate | null; volatile_keys?: string[]; eligibility_oids?: EligibilityOidCheck[] };
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

export function useCloneAppVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, versionId }: { appId: string; versionId: string }) =>
      apiPost<{
        id: string;
        version: string;
        checksum: string;
        is_latest: boolean;
        cloned_from: { version_id: string; version: string };
      }>(`/apps/${appId}/versions/${versionId}/clone`, {}),
    onSuccess: (_res, { appId }) => {
      qc.invalidateQueries({ queryKey: ["app-detail", appId] });
      qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useAppConfigKeys(appId: string | undefined, versionId?: string) {
  return useQuery({
    queryKey: ["app-config-keys", appId, versionId],
    queryFn: () => {
      const params = versionId ? `?version_id=${versionId}` : "";
      return apiGet<ConfigKeysResponse>(`/apps/${appId}/config-keys${params}`);
    },
    select: (res) => res.data,
    enabled: !!appId,
  });
}

export function useStartEligibilityTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, mode = "instant" }: { appId: string; mode?: "instant" | "probe" }) =>
      apiPost<{ run_id: string; total_devices: number; mode: string }>(`/apps/${appId}/test-eligibility`, { mode }),
    onSuccess: (_d, { appId }) => {
      qc.invalidateQueries({ queryKey: ["eligibility-runs", appId] });
    },
  });
}

export function useEligibilityRuns(appId: string | undefined) {
  return useQuery({
    queryKey: ["eligibility-runs", appId],
    queryFn: () => apiGet<EligibilityRun[]>(`/apps/${appId}/eligibility-runs?limit=20`),
    select: (res) => res,
    enabled: !!appId,
    refetchInterval: 5000,
  });
}

export function useEligibilityRunDetail(appId: string | undefined, runId: string | undefined, eligibleFilter?: number, page = 1) {
  return useQuery({
    queryKey: ["eligibility-run-detail", appId, runId, eligibleFilter, page],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("limit", "25");
      params.set("offset", String((page - 1) * 25));
      if (eligibleFilter !== undefined) params.set("eligible_filter", String(eligibleFilter));
      return apiGet<{ run: EligibilityRun; devices: EligibilityDeviceResult[]; meta: { total: number; limit: number; offset: number } }>(
        `/apps/${appId}/eligibility-runs/${runId}?${params}`,
      );
    },
    enabled: !!appId && !!runId,
    refetchInterval: 5000,
  });
}

export function useAutoAssignEligible() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, runId, deviceIds }: { appId: string; runId: string; deviceIds?: string[] }) =>
      apiPost<{ created: number; skipped: number }>(
        `/apps/${appId}/auto-assign-eligible?run_id=${runId}`,
        deviceIds ? { device_ids: deviceIds } : {},
      ),
    onSuccess: (_d, { appId }) => {
      qc.invalidateQueries({ queryKey: ["eligibility-runs", appId] });
      qc.invalidateQueries({ queryKey: ["device-assignments"] });
    },
  });
}

// ── Python Modules ──────────────────────────────────────

export function usePythonModules(params: ListParams = {}) {
  return useQuery({
    queryKey: ["python-modules", params],
    queryFn: () => apiGet<PythonModuleSummary[]>(`/python-modules${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function usePythonModuleDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["python-module", id],
    queryFn: () => apiGet<PythonModuleDetail>(`/python-modules/${id}`),
    select: (res) => res.data,
    enabled: !!id,
    refetchInterval: POLL_DETAIL,
  });
}

export function useNetworkStatus() {
  return useQuery({
    queryKey: ["python-modules-network"],
    queryFn: () => apiGet<NetworkStatus>("/python-modules/network-status"),
    select: (res) => res.data,
  });
}

export function useUploadWheel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiPostFormData<WheelUploadResult>("/python-modules/upload-wheel", fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
    },
  });
}

export function useUploadWheelsBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      return apiPostFormData<WheelUploadResult[]>("/python-modules/upload-wheels-batch", fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
    },
  });
}

export function useImportFromPyPI() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { package_name: string; version?: string }) =>
      apiPost<WheelUploadResult>("/python-modules/import-pypi", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
    },
  });
}

export function useResolveDependencies() {
  return useMutation({
    mutationFn: (data: { requirements: string[] }) =>
      apiPost<ResolveResult>("/python-modules/resolve", data),
  });
}

export function useAutoResolve() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { module_id?: string; max_depth?: number }) =>
      apiPost<{ imported: { name: string; version: string; filename: string }[]; failed: { name: string; error: string }[]; still_missing: string[] }>("/python-modules/auto-resolve", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
      qc.invalidateQueries({ queryKey: ["python-module"] });
    },
  });
}

export function useToggleModuleApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_approved }: { id: string; is_approved: boolean }) =>
      apiPut<PythonModuleSummary>(`/python-modules/${id}/approve`, { is_approved }),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
      qc.invalidateQueries({ queryKey: ["python-module", id] });
    },
  });
}

export function useToggleModuleVerify() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ moduleId, versionId, is_verified }: { moduleId: string; versionId: string; is_verified: boolean }) =>
      apiPut<{ id: string }>(`/python-modules/${moduleId}/versions/${versionId}/verify`, { is_verified }),
    onSuccess: (_res, { moduleId }) => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
      qc.invalidateQueries({ queryKey: ["python-module", moduleId] });
    },
  });
}

export function useDeletePythonModule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/python-modules/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
    },
  });
}

export function useDeleteModuleVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ moduleId, versionId }: { moduleId: string; versionId: string }) =>
      apiDelete(`/python-modules/${moduleId}/versions/${versionId}`),
    onSuccess: (_res, { moduleId }) => {
      qc.invalidateQueries({ queryKey: ["python-modules"] });
      qc.invalidateQueries({ queryKey: ["python-module", moduleId] });
    },
  });
}

export function useSearchPyPI(query: string) {
  return useQuery({
    queryKey: ["pypi-search", query],
    queryFn: () => apiGet<PyPISearchResult[]>(`/python-modules/search-pypi?q=${encodeURIComponent(query)}`),
    select: (res) => res.data,
    enabled: query.length >= 2,
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
    mutationFn: (data: { cn?: string; san_ips?: string[]; san_dns?: string[]; validity_days?: number }) =>
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
    mutationFn: () => apiPost<{ deployed: boolean; written: boolean; message: string }>("/settings/tls/deploy", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tls-cert"] });
    },
  });
}

// ── Templates ────────────────────────────────────────────

export function useTemplates(params: ListParams = {}) {
  return useQuery({
    queryKey: ["templates", params],
    queryFn: () => apiGet<Template[]>(`/templates${buildListQs(params)}`),
    placeholderData: keepPreviousData,
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

// ── Template Bindings ────────────────────────────────────

export function useCategoryTemplateBindings(categoryId: string | undefined) {
  return useQuery({
    queryKey: ["template-bindings-category", categoryId],
    queryFn: () => apiGet<TemplateBinding[]>(`/templates/bindings/category/${categoryId}`),
    enabled: !!categoryId,
  });
}

export function useDeviceTypeTemplateBindings(deviceTypeId: string | undefined) {
  return useQuery({
    queryKey: ["template-bindings-device-type", deviceTypeId],
    queryFn: () => apiGet<TemplateBinding[]>(`/templates/bindings/device-type/${deviceTypeId}`),
    enabled: !!deviceTypeId,
  });
}

export function useBindCategoryTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { device_category_id: string; template_id: string; step?: number }) =>
      apiPost<TemplateBinding>("/templates/bindings/category", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["template-bindings-category"] });
    },
  });
}

export function useUnbindCategoryTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (bindingId: string) => apiDelete(`/templates/bindings/category/${bindingId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["template-bindings-category"] });
    },
  });
}

export function useBindDeviceTypeTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { device_type_id: string; template_id: string; step?: number }) =>
      apiPost<TemplateBinding>("/templates/bindings/device-type", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["template-bindings-device-type"] });
    },
  });
}

export function useUnbindDeviceTypeTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (bindingId: string) => apiDelete(`/templates/bindings/device-type/${bindingId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["template-bindings-device-type"] });
    },
  });
}

export function useResolveTemplates() {
  return useMutation({
    mutationFn: (deviceIds: string[]) =>
      apiPost<ResolvedTemplateResult[]>("/templates/resolve", { device_ids: deviceIds }),
  });
}

export function useAutoApplyTemplates() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceIds: string[]) =>
      apiPost<{ applied: number; details: ResolvedTemplateResult[] }>("/templates/auto-apply", { device_ids: deviceIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["assignments"] });
    },
  });
}

// ── Label Keys ───────────────────────────────────────────

export function useLabelKeys() {
  return useQuery({
    queryKey: ["label-keys"],
    queryFn: () => apiGet<LabelKey[]>("/label-keys"),
    select: (res) => res.data,
  });
}

export function useLabelValues(keyName: string | null) {
  return useQuery({
    queryKey: ["label-values", keyName],
    queryFn: () => apiGet<string[]>(`/label-keys/values/${keyName}`),
    select: (res) => res.data,
    enabled: !!keyName,
  });
}

export function useCreateLabelKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      key: string;
      description?: string;
      color?: string;
      show_description?: boolean;
      predefined_values?: string[];
    }) => apiPost<LabelKey>("/label-keys", data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["label-keys"] });
    },
  });
}

export function useUpdateLabelKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<{ description: string; color: string; show_description: boolean; predefined_values: string[] }>;
    }) => apiPut<LabelKey>(`/label-keys/${id}`, data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["label-keys"] });
    },
  });
}

export function useDeleteLabelKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/label-keys/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["label-keys"] });
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

export function useCollectorErrors(collectorName: string | null, hours = 1) {
  return useQuery({
    queryKey: ["collector-errors", collectorName, hours],
    queryFn: () => apiGet<import("@/types/api").CollectorErrorAnalytics>(
      `/system/collector-errors/${encodeURIComponent(collectorName!)}?hours=${hours}`
    ),
    select: (res) => res.data,
    enabled: !!collectorName,
    staleTime: 30_000,
  });
}

export function usePatroniSwitchover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { leader: string; candidate: string }) =>
      apiPost<{ message: string }>("/system/patroni/switchover", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-health"] });
    },
  });
}

export function useSystemHealthStatus() {
  return useQuery({
    queryKey: ["system-health-status"],
    queryFn: () => apiGet<{ overall_status: string; checked_at: string | null }>("/system/health/status"),
    select: (res) => res.data,
    refetchInterval: 30_000,
    retry: false,
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

// ── Connectors ──────────────────────────────────────────

export function useConnectors(params: ListParams = {}) {
  return useQuery({
    queryKey: ["connectors", params],
    queryFn: () => apiGet<ConnectorSummary[]>(`/connectors${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useConnectorDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["connector-detail", id],
    queryFn: () => apiGet<ConnectorDetail>(`/connectors/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string; connector_type: string }) =>
      apiPost<ConnectorSummary>("/connectors", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

export function useUpdateConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string } }) =>
      apiPut<ConnectorDetail>(`/connectors/${id}`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-detail", vars.id] });
    },
  });
}

export function useDeleteConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/connectors/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

export function useCreateConnectorVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ connectorId, data }: {
      connectorId: string;
      data: { version: string; source_code?: string; requirements?: string[]; entry_class?: string };
    }) => apiPost(`/connectors/${connectorId}/versions`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["connector-detail", vars.connectorId] });
    },
  });
}

export function useUpdateConnectorVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ connectorId, versionId, data }: {
      connectorId: string;
      versionId: string;
      data: { source_code?: string; requirements?: string[]; entry_class?: string };
    }) => apiPut(`/connectors/${connectorId}/versions/${versionId}`, data),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["connector-detail", vars.connectorId] });
    },
  });
}

export function useDeleteConnectorVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ connectorId, versionId }: { connectorId: string; versionId: string }) =>
      apiDelete(`/connectors/${connectorId}/versions/${versionId}`),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["connector-detail", vars.connectorId] });
    },
  });
}

export function useSetConnectorLatest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ connectorId, versionId }: { connectorId: string; versionId: string }) =>
      apiPut(`/connectors/${connectorId}/versions/${versionId}/set-latest`, {}),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["connector-detail", vars.connectorId] });
    },
  });
}

export function useCloneConnectorVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ connectorId, versionId }: { connectorId: string; versionId: string }) =>
      apiPost<{
        id: string;
        version: string;
        checksum: string;
        is_latest: boolean;
        cloned_from: { version_id: string; version: string };
      }>(`/connectors/${connectorId}/versions/${versionId}/clone`, {}),
    onSuccess: (_res, { connectorId }) => {
      qc.invalidateQueries({ queryKey: ["connector-detail", connectorId] });
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

// ── Events ───────────────────────────────────────────────

export function useActiveEvents(params: ListParams = {}) {
  return useQuery({
    queryKey: ["events-active", params],
    queryFn: () => apiGet<MonitoringEvent[]>(`/events/active${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useClearedEvents(params: ListParams = {}) {
  return useQuery({
    queryKey: ["events-cleared", params],
    queryFn: () => apiGet<MonitoringEvent[]>(`/events/cleared${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useAcknowledgeEvents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (eventIds: string[]) =>
      apiPost("/events/acknowledge", { event_ids: eventIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events-active"] });
      qc.invalidateQueries({ queryKey: ["events-cleared"] });
    },
  });
}

export function useClearEvents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (eventIds: string[]) =>
      apiPost("/events/clear", { event_ids: eventIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events-active"] });
      qc.invalidateQueries({ queryKey: ["events-cleared"] });
    },
  });
}

// ── Event Policies ───────────────────────────────────────

export function useEventPolicies(params: ListParams = {}) {
  const qs = buildListQs(params);
  return useQuery({
    queryKey: ["event-policies", params],
    queryFn: () => apiGetRaw<{ status: string; data: EventPolicy[]; meta: { limit: number; offset: number; count: number; total: number } }>(`/events/policies${qs}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateEventPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      definition_id: string;
      mode?: string;
      fire_count_threshold?: number;
      window_size?: number;
      event_severity?: string;
      message_template?: string;
      auto_clear_on_resolve?: boolean;
    }) => apiPost("/events/policies", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["event-policies"] });
    },
  });
}

export function useUpdateEventPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      apiPut(`/events/policies/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["event-policies"] });
    },
  });
}

export function useDeleteEventPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/events/policies/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["event-policies"] });
    },
  });
}

// ── Packs ─────────────────────────────────────────────────

export function usePacks(params: ListParams = {}) {
  return useQuery({
    queryKey: ["packs", params],
    queryFn: () => apiGet<Pack[]>(`/packs${buildListQs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function usePackDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["packs", id],
    queryFn: () => apiGet<PackDetail>(`/packs/${id}`),
    select: (res) => res.data,
    enabled: !!id,
    refetchInterval: POLL_DETAIL,
  });
}

export function useAvailableEntities(enabled = false) {
  return useQuery({
    queryKey: ["packs", "available-entities"],
    queryFn: () => apiGet<AvailableEntities>("/packs/available-entities"),
    select: (res) => res.data,
    enabled,
  });
}

export function useCreatePack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      pack_uid: string;
      name: string;
      version: string;
      description?: string;
      author?: string;
      entity_ids: Record<string, string[]>;
    }) => apiPost<{ id: string; pack_uid: string }>("/packs", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["packs"] });
    },
  });
}

export function useExportPack() {
  return useMutation({
    mutationFn: (packId: string) =>
      apiGet<Record<string, unknown>>(`/packs/${packId}/export`),
  });
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: (packData: Record<string, unknown>) =>
      apiPost<PackImportPreview>("/packs/preview", { pack_data: packData }),
  });
}

export function useImportPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      pack_data: Record<string, unknown>;
      resolutions: Record<string, string>;
    }) => apiPost<PackImportResult>("/packs/import", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["packs"] });
      qc.invalidateQueries({ queryKey: ["apps"] });
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["snmp-oids"] });
      qc.invalidateQueries({ queryKey: ["templates"] });
      qc.invalidateQueries({ queryKey: ["device-categories"] });
      qc.invalidateQueries({ queryKey: ["label-keys"] });
      qc.invalidateQueries({ queryKey: ["credential-templates"] });
    },
  });
}

export function useDeletePack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/packs/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["packs"] });
    },
  });
}

// ── Docker Infrastructure ───────────────────────────────────

export function useDockerHosts() {
  return useQuery({
    queryKey: ["docker-infra", "hosts"],
    queryFn: () => apiGet<DockerHostInfo[]>("/docker-infra/hosts"),
  });
}

export function useDockerOverview() {
  return useQuery({
    queryKey: ["docker-infra", "overview"],
    queryFn: () => apiGet<DockerOverviewResponse>("/docker-infra/overview"),
    refetchInterval: 30_000,
  });
}

export function useDockerHostStats(hostLabel: string) {
  return useQuery({
    queryKey: ["docker-infra", "stats", hostLabel],
    queryFn: () => apiGet<Record<string, unknown>>(`/docker-infra/hosts/${hostLabel}/stats`),
    refetchInterval: 15_000,
    enabled: !!hostLabel,
  });
}

export function useDockerHostSystem(hostLabel: string) {
  return useQuery({
    queryKey: ["docker-infra", "system", hostLabel],
    queryFn: () => apiGet<DockerSystemInfo>(`/docker-infra/hosts/${hostLabel}/system`),
    refetchInterval: 30_000,
    enabled: !!hostLabel,
  });
}

export function useDockerContainerLogs(hostLabel: string, container: string, tail = 100) {
  return useQuery({
    queryKey: ["docker-infra", "logs", hostLabel, container, tail],
    queryFn: () =>
      apiGet<DockerContainerLog>(
        `/docker-infra/hosts/${hostLabel}/logs?container=${encodeURIComponent(container)}&tail=${tail}`
      ),
    refetchInterval: 5_000,
    enabled: !!hostLabel && !!container,
  });
}

export function useDockerEvents(hostLabel: string, since = 0, limit = 100) {
  return useQuery({
    queryKey: ["docker-infra", "events", hostLabel, since],
    queryFn: () =>
      apiGet<DockerEventsResponse>(
        `/docker-infra/hosts/${hostLabel}/events?since=${since}&limit=${limit}`
      ),
    refetchInterval: 10_000,
    enabled: !!hostLabel,
  });
}

export function useDockerImages(hostLabel: string) {
  return useQuery({
    queryKey: ["docker-infra", "images", hostLabel],
    queryFn: () => apiGet<DockerImagesResponse>(`/docker-infra/hosts/${hostLabel}/images`),
    enabled: !!hostLabel,
  });
}

// ── Config History ───────────────────────────────────────────────────────────

export function useConfigChangelog(
  deviceId: string,
  params: {
    app_id?: string;
    config_key?: string;
    from_ts?: string;
    to_ts?: string;
    limit?: number;
    offset?: number;
  } = {}
) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const q = qs.toString();
  return useQuery({
    queryKey: ["config-changelog", deviceId, params],
    queryFn: () =>
      apiGet<ConfigChangeEntry[]>(
        `/devices/${deviceId}/config/changelog${q ? `?${q}` : ""}`
      ),
    enabled: !!deviceId,
  });
}

export function useConfigSnapshot(deviceId: string, appId?: string) {
  const qs = appId ? `?app_id=${appId}` : "";
  return useQuery({
    queryKey: ["config-snapshot", deviceId, appId],
    queryFn: () =>
      apiGet<ConfigChangeEntry[]>(`/devices/${deviceId}/config/snapshot${qs}`),
    enabled: !!deviceId,
  });
}

export function useConfigDiff(
  deviceId: string,
  configKey: string,
  appId?: string,
  limit = 20
) {
  const qs = new URLSearchParams({ config_key: configKey, limit: String(limit) });
  if (appId) qs.set("app_id", appId);
  return useQuery({
    queryKey: ["config-diff", deviceId, configKey, appId],
    queryFn: () =>
      apiGet<ConfigChangeEntry[]>(
        `/devices/${deviceId}/config/diff?${qs.toString()}`
      ),
    enabled: !!deviceId && !!configKey,
  });
}

export function useConfigChangeTimestamps(
  deviceId: string,
  params: { app_id?: string; from_ts?: string; to_ts?: string } = {}
) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const q = qs.toString();
  return useQuery({
    queryKey: ["config-change-timestamps", deviceId, params],
    queryFn: () =>
      apiGet<ConfigChangeTimestamp[]>(
        `/devices/${deviceId}/config/change-timestamps${q ? `?${q}` : ""}`
      ),
    enabled: !!deviceId,
  });
}

export function useConfigCompare(
  deviceId: string,
  timeA: string | null,
  timeB: string | null,
  appId?: string
) {
  const qs = new URLSearchParams();
  if (timeA) qs.set("time_a", timeA);
  if (timeB) qs.set("time_b", timeB);
  if (appId) qs.set("app_id", appId);
  return useQuery({
    queryKey: ["config-compare", deviceId, timeA, timeB, appId],
    queryFn: () =>
      apiGet<ConfigCompareResult>(
        `/devices/${deviceId}/config/compare?${qs.toString()}`
      ),
    select: (res) => res.data,
    enabled: !!deviceId && !!timeA && !!timeB,
  });
}

// ── Retention ───────────────────────────────────────────────────────────

export function useRetentionDefaults() {
  return useQuery({
    queryKey: ["retention-defaults"],
    queryFn: () => apiGet<RetentionDefaults>("/retention/defaults"),
    select: (res) => res.data,
  });
}

export function useSetRetentionDefault() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { data_type: string; retention_days: number }) =>
      apiPut("/retention/defaults", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retention-defaults"] });
      qc.invalidateQueries({ queryKey: ["device-retention"] });
    },
  });
}

export function useDeviceRetention(deviceId: string) {
  return useQuery({
    queryKey: ["device-retention", deviceId],
    queryFn: () => apiGet<DeviceRetentionEntry[]>(`/devices/${deviceId}/retention`),
    select: (res) => res.data,
    enabled: !!deviceId,
  });
}

export function useSetDeviceRetention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, ...data }: {
      deviceId: string; app_id: string; data_type: string; retention_days: number;
    }) => apiPut(`/devices/${deviceId}/retention`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-retention"] });
    },
  });
}

export function useDeleteDeviceRetention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, overrideId }: { deviceId: string; overrideId: string }) =>
      apiDelete(`/devices/${deviceId}/retention/${overrideId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-retention"] });
    },
  });
}

// ── Upgrades ─────────────────────────────────────────────────────────────

export function useUpgradeStatus() {
  return useQuery({
    queryKey: ["upgrade-status"],
    queryFn: () => apiGet<UpgradeStatus>("/upgrades/status"),
    select: (res) => res.data,
    refetchInterval: POLL_DETAIL,
  });
}

export function useUploadUpgradeBundle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      return apiPostFormData<UpgradePackageInfo>("/upgrades/upload", (() => { const fd = new FormData(); fd.append("file", file); return fd; })());
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["upgrade-status"] }),
  });
}

export function useDeleteUpgradePackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (packageId: string) => apiDelete(`/upgrades/packages/${packageId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["upgrade-status"] }),
  });
}

export function useStartUpgrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { upgrade_package_id: string; scope: string; strategy: string }) =>
      apiPost<UpgradeJob>("/upgrades/execute", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["upgrade-status"] });
      qc.invalidateQueries({ queryKey: ["upgrade-jobs"] });
    },
  });
}

export function useUpgradeJobs() {
  return useQuery({
    queryKey: ["upgrade-jobs"],
    queryFn: () => apiGet<UpgradeJob[]>("/upgrades/jobs"),
    select: (res) => res.data,
    refetchInterval: 5_000,
  });
}

export function useUpgradeJob(jobId: string | null) {
  return useQuery({
    queryKey: ["upgrade-job", jobId],
    queryFn: () => apiGet<UpgradeJob>(`/upgrades/jobs/${jobId}`),
    select: (res) => res.data,
    enabled: !!jobId,
    refetchInterval: 3_000,
  });
}

export function useCancelUpgradeJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiPost(`/upgrades/jobs/${jobId}/cancel`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["upgrade-jobs"] }),
  });
}

export function useCheckOsUpdates() {
  return useMutation({
    mutationFn: () => apiPost<Record<string, unknown>>("/upgrades/os/check", {}),
  });
}

export function useOsPackages() {
  return useQuery({
    queryKey: ["os-packages"],
    queryFn: () => apiGet<OsPackageInfo[]>("/upgrades/os/packages"),
    select: (res) => res.data,
  });
}

// ── OS Updates ──────────────────────────────────────────

export function useOsUpdates() {
  return useQuery({
    queryKey: ["os-updates"],
    queryFn: () => apiGet<OsUpdateByNode>("/upgrades/os-updates"),
    select: (r) => r.data,
    refetchInterval: 30_000,
  });
}

export function useCheckOsUpdatesNew() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<OsCheckResult>("/upgrades/check-os", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["os-updates"] });
      qc.invalidateQueries({ queryKey: ["upgrade-badge"] });
    },
  });
}

export function useDownloadOsPackages() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (packageNames: string[]) =>
      apiPost("/upgrades/prepare-archive", { package_names: packageNames }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["package-inventory"] });
    },
  });
}

export function useUploadOsPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiPostFormData("/upgrades/os-upload", fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["os-cached-packages"] }),
  });
}

export function useOsCachedPackages() {
  return useQuery({
    queryKey: ["os-cached-packages"],
    queryFn: () => apiGet<OsCachedPkg[]>("/upgrades/os-packages"),
    select: (r) => r.data,
  });
}

export function useInstallOsOnNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { node_hostname: string; package_names: string[] }) =>
      apiPost<OsInstallResult>("/upgrades/os-install", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["os-updates"] });
      qc.invalidateQueries({ queryKey: ["upgrade-badge"] });
    },
  });
}

export function useOsInstallJobs() {
  return useQuery({
    queryKey: ["os-install-jobs"],
    queryFn: () => apiGet<OsInstallJob[]>("/upgrades/os-install-jobs"),
    select: (res) => res.data,
    refetchInterval: POLL_DETAIL,
  });
}

export function useStartOsInstallJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      package_names: string[];
      scope: string;
      target_nodes?: string[];
      strategy?: string;
      restart_policy?: string;
    }) => apiPost<OsInstallJob>("/upgrades/os-install-job", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["os-install-jobs"] });
      qc.invalidateQueries({ queryKey: ["os-updates"] });
    },
  });
}

export function useApproveOsInstallJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiPost(`/upgrades/os-install-jobs/${jobId}/approve`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["os-install-jobs"] }),
  });
}

export function useCancelOsInstallJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiPost(`/upgrades/os-install-jobs/${jobId}/cancel`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["os-install-jobs"] }),
  });
}

export function useDeleteOsInstallJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiDelete(`/upgrades/os-install-jobs/${jobId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["os-install-jobs"] }),
  });
}

export function usePackageInventory() {
  return useQuery({
    queryKey: ["package-inventory"],
    queryFn: () => apiGet<PackageInventoryItem[]>("/upgrades/package-inventory"),
    select: (res) => res.data,
    refetchInterval: 30_000,
  });
}

export function useCollectInventory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/upgrades/collect-inventory", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["package-inventory"] }),
  });
}

export function useRestartNodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { node_hostnames: string[]; strategy?: string }) =>
      apiPost<OsInstallJob>("/upgrades/os-restart-nodes", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["os-install-jobs"] });
      qc.invalidateQueries({ queryKey: ["upgrade-status"] });
    },
  });
}

export function useUpgradeBadge() {
  return useQuery({
    queryKey: ["upgrade-badge"],
    queryFn: () => apiGet<UpgradeBadge>("/upgrades/badge"),
    select: (r) => r.data,
    refetchInterval: 60_000,
  });
}

// ── Dashboard ────────────────────────────────────────────────────────────────

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => apiGet<DashboardSummary>("/dashboard/summary"),
    select: (res) => res.data,
    refetchInterval: 15_000,
  });
}

// ── Device Types (specific hardware models with OID) ────

export function useDeviceTypes(params: ListParams = {}) {
  const qs = buildListQs(params);
  return useQuery({
    queryKey: ["device-types", params],
    queryFn: () => apiGetRaw<{ status: string; data: DeviceType[]; meta: { limit: number; offset: number; count: number; total: number } }>(`/device-types${qs}`),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_LIST,
  });
}

export function useCreateDeviceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      sys_object_id_pattern: string;
      device_category_id: string;
      vendor?: string;
      model?: string;
      os_family?: string;
      description?: string;
      priority?: number;
    }) => apiPost<DeviceType>("/device-types", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device-types"] });
    },
  });
}

export function useUpdateDeviceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
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

export function useDiscoverDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) =>
      apiPost(`/devices/${deviceId}/discover`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device"] });
    },
  });
}

// ── Logs (ClickHouse) ───────────────────────────────────────────────────────

export interface LogQueryParams {
  collector_name?: string;
  container_name?: string;
  host_label?: string;
  level?: string;
  source_type?: string;
  search?: string;
  from_ts?: string;
  to_ts?: string;
  page?: number;
  page_size?: number;
  sort_field?: string;
  sort_dir?: string;
}

export function useLogs(params: LogQueryParams, enabled = true) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      searchParams.set(k, String(v));
    }
  });

  return useQuery({
    queryKey: ["logs", params],
    queryFn: () => apiGet<LogQueryResponse>(`/logs?${searchParams.toString()}`),
    enabled,
    refetchInterval: false,
  });
}

export function useLogFilters() {
  return useQuery({
    queryKey: ["log-filters"],
    queryFn: () => apiGet<LogFiltersResponse>("/logs/filters"),
    staleTime: 60_000,
  });
}

export function useLogsTail(params: LogQueryParams, enabled = false) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      searchParams.set(k, String(v));
    }
  });
  searchParams.set("sort_field", "timestamp");
  searchParams.set("sort_dir", "desc");
  searchParams.set("page", "1");
  searchParams.set("page_size", "200");

  return useQuery({
    queryKey: ["logs-tail", params],
    queryFn: () => apiGet<LogQueryResponse>(`/logs?${searchParams.toString()}`),
    enabled,
    refetchInterval: 2_000,
  });
}

// ── WebSocket status ────────────────────────────────────────────────────────

export function useCollectorWsStatus(collectorId: string) {
  return useQuery({
    queryKey: ["collector-ws-status", collectorId],
    queryFn: () => apiGet<CollectorWsStatus>(`/collectors/${collectorId}/ws-status`),
    refetchInterval: 15_000,
    enabled: !!collectorId,
  });
}

export function useWsConnections() {
  return useQuery({
    queryKey: ["ws-connections"],
    queryFn: () =>
      apiGet<{ connections: CollectorWsConnection[] }>("/collectors/ws-connections"),
    refetchInterval: 15_000,
  });
}

// ── Analytics ────────────────────────────────────────────

export function useAnalyticsTables() {
  return useQuery({
    queryKey: ["analytics-tables"],
    queryFn: () => apiGet<AnalyticsTable[]>("/analytics/tables"),
    select: (res) => res.data,
    staleTime: 5 * 60_000,
  });
}

export function useExecuteQuery() {
  return useMutation({
    mutationFn: (data: { sql: string; limit?: number }) =>
      apiPost<QueryResult>("/analytics/query", data),
  });
}

// ── Custom Dashboards ────────────────────────────────────

export function useAnalyticsDashboards() {
  return useQuery({
    queryKey: ["analytics-dashboards"],
    queryFn: () => apiGet<AnalyticsDashboardSummary[]>("/analytics/dashboards"),
    select: (res) => res.data,
  });
}

export function useAnalyticsDashboard(id: string) {
  return useQuery({
    queryKey: ["analytics-dashboard", id],
    queryFn: () => apiGet<AnalyticsDashboard>(`/analytics/dashboards/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateAnalyticsDashboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiPost<{ id: string }>("/analytics/dashboards", data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["analytics-dashboards"] }); },
  });
}

export function useUpdateAnalyticsDashboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      apiPut(`/analytics/dashboards/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analytics-dashboards"] });
      qc.invalidateQueries({ queryKey: ["analytics-dashboard"] });
    },
  });
}

export function useAppendDashboardWidget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ dashboardId, ...data }: { dashboardId: string; title: string; config: Record<string, unknown>; layout: Record<string, number> }) =>
      apiPost(`/analytics/dashboards/${dashboardId}/widgets`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analytics-dashboards"] });
      qc.invalidateQueries({ queryKey: ["analytics-dashboard"] });
    },
  });
}

export function useDeleteAnalyticsDashboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/analytics/dashboards/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["analytics-dashboards"] }); },
  });
}

// ── Actions ──────────────────────────────────────────────

export function useActions(params?: {
  search?: string;
  target?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: string;
}) {
  const query = new URLSearchParams();
  if (params?.search) query.set("search", params.search);
  if (params?.target) query.set("target", params.target);
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));
  if (params?.sort_by) query.set("sort_by", params.sort_by);
  if (params?.sort_dir) query.set("sort_dir", params.sort_dir);
  const qs = query.toString();
  return useQuery({
    queryKey: ["actions", qs],
    queryFn: () => apiGetRaw<{ data: Action[]; total: number }>(`/automations/actions${qs ? `?${qs}` : ""}`),
    refetchInterval: POLL_LIST,
  });
}

export function useAction(id: string) {
  return useQuery({
    queryKey: ["action", id],
    queryFn: () => apiGet<Action>(`/automations/actions/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      target: string;
      source_code?: string;
      credential_type?: string;
      credential_id?: string | null;
      timeout_seconds?: number;
    }) => apiPost("/automations/actions", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["actions"] }),
  });
}

export function useUpdateAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      apiPut(`/automations/actions/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["actions"] });
      qc.invalidateQueries({ queryKey: ["action"] });
    },
  });
}

export function useDeleteAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/automations/actions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["actions"] }),
  });
}

// ── Automations ──────────────────────────────────────────

export function useAutomations(params?: {
  search?: string;
  trigger_type?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: string;
}) {
  const query = new URLSearchParams();
  if (params?.search) query.set("search", params.search);
  if (params?.trigger_type) query.set("trigger_type", params.trigger_type);
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));
  if (params?.sort_by) query.set("sort_by", params.sort_by);
  if (params?.sort_dir) query.set("sort_dir", params.sort_dir);
  const qs = query.toString();
  return useQuery({
    queryKey: ["automations", qs],
    queryFn: () => apiGetRaw<{ data: Automation[]; total: number }>(`/automations/automations${qs ? `?${qs}` : ""}`),
    refetchInterval: POLL_LIST,
  });
}

export function useAutomation(id: string) {
  return useQuery({
    queryKey: ["automation", id],
    queryFn: () => apiGet<Automation>(`/automations/automations/${id}`),
    select: (res) => res.data,
    enabled: !!id,
  });
}

export function useCreateAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiPost("/automations/automations", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automations"] }),
  });
}

export function useUpdateAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      apiPut(`/automations/automations/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automations"] });
      qc.invalidateQueries({ queryKey: ["automation"] });
    },
  });
}

export function useDeleteAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/automations/automations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automations"] }),
  });
}

export function useTriggerAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, device_ids }: { id: string; device_ids: string[] }) =>
      apiPost(`/automations/automations/${id}/trigger`, { device_ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automation-runs"] }),
  });
}

// ── Automation Runs ──────────────────────────────────────

export function useAutomationRuns(params?: {
  automation_id?: string;
  device_id?: string;
  event_id?: string;
  status?: string;
  page?: number;
  page_size?: number;
}) {
  const query = new URLSearchParams();
  if (params?.automation_id) query.set("automation_id", params.automation_id);
  if (params?.device_id) query.set("device_id", params.device_id);
  if (params?.event_id) query.set("event_id", params.event_id);
  if (params?.status) query.set("status", params.status);
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));
  const qs = query.toString();
  return useQuery({
    queryKey: ["automation-runs", qs],
    queryFn: () => apiGetRaw<{ data: AutomationRun[]; total: number }>(`/automations/runs${qs ? `?${qs}` : ""}`),
    refetchInterval: POLL_LIST,
  });
}

export function useAutomationRun(runId: string) {
  return useQuery({
    queryKey: ["automation-run", runId],
    queryFn: () => apiGet<AutomationRun>(`/automations/runs/${runId}`),
    select: (res) => res.data,
    enabled: !!runId,
  });
}
