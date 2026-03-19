// ── Generic API envelope ──────────────────────────────────

export interface ApiResponse<T> {
  status: string;
  data: T;
}

// ── Auth ──────────────────────────────────────────────────

export interface AuthUser {
  user_id: string;
  username: string;
  role: string;
  role_id?: string | null;
  role_name?: string | null;
  timezone: string;
  all_tenants?: boolean;
  tenant_ids?: string[] | null; // null = unrestricted, [] = see nothing, [ids] = specific
  permissions?: string[] | null; // null = admin (full access), ["resource:action", ...]
}

export interface LoginPayload {
  username: string;
  password: string;
}

// ── Device Types ──────────────────────────────────────────

export interface DeviceType {
  id: string;
  name: string;
  description: string | null;
  category: string;
  created_at: string;
}

// ── Tenants ───────────────────────────────────────────────

export interface Tenant {
  id: string;
  name: string;
  metadata: Record<string, string>;
  created_at: string;
}

// ── Registration Tokens ──────────────────────────────────

export interface RegistrationToken {
  id: string;
  name: string;
  short_code: string | null;
  one_time: boolean;
  used: boolean;
  cluster_id: string | null;
  expires_at: string | null;
  created_at: string;
  token?: string; // Legacy, only present on creation response
}

// ── Credential Keys ──────────────────────────────────────

export interface CredentialKey {
  id: string;
  name: string;
  description: string | null;
  key_type: "plain" | "secret" | "enum";
  is_secret: boolean;
  enum_values: string[] | null;
  created_at: string;
}

export interface CredentialValue {
  key_id: string;
  key_name: string;
  value: string;
  is_secret: boolean;
}

// ── Collector Groups ──────────────────────────────────────

export interface CollectorGroupHealth {
  status: "healthy" | "degraded" | "critical" | "empty";
  message: string;
}

export interface CollectorGroup {
  id: string;
  name: string;
  description: string | null;
  collector_count: number;
  health: CollectorGroupHealth;
  created_at: string;
}

// ── Devices ───────────────────────────────────────────────

export interface Device {
  id: string;
  name: string;
  address: string;
  device_type: string;
  tenant_id: string | null;
  tenant_name: string | null;
  collector_group_id: string | null;
  collector_group_name: string | null;
  labels: Record<string, string>;
  default_credential_id: string | null;
  default_credential_name: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DeviceListParams {
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  name?: string;
  address?: string;
  device_type?: string;
  tenant_name?: string;
  collector_group_name?: string;
  label_key?: string;
  label_value?: string;
  collector_id?: string;
}

export interface PaginatedResponse<T> {
  status: string;
  data: T[];
  meta: {
    limit: number;
    offset: number;
    count: number;
    total: number;
  };
}

// ── Results ───────────────────────────────────────────────

export interface CheckResult {
  assignment_id: string;
  collector_id: string | null;
  app_name: string;
  state: number;
  state_name: string;
  output: string;
  reachable: boolean;
  rtt_ms: number | null;
  response_time_ms: number | null;
  status_code: number | null;
  performance_data: Record<string, unknown> | null;
  executed_at: string;
  execution_time_ms: number | null;
  started_at: string | null;
  collector_name: string | null;
}

export interface DeviceResults {
  device_id: string;
  device_name: string;
  device_address: string;
  device_type: string;
  tenant_id: string | null;
  up: boolean;
  checks: CheckResult[];
}

export interface ResultRecord {
  id?: string;
  assignment_id: string;
  collector_id?: string;
  device_id: string;
  device_name?: string;
  app_name?: string;
  role: string | null;
  state: number;
  state_name: string;
  output: string;
  reachable: boolean;
  rtt_ms: number | null;
  response_time_ms: number | null;
  status_code: number | null;
  performance_data: Record<string, unknown> | null;
  executed_at: string;
  execution_time_ms: number | null;
  started_at: string | null;
  collector_name: string | null;
}

// ── Collectors ────────────────────────────────────────────

export interface Collector {
  id: string;
  name: string;
  hostname: string;
  status: string;
  labels: Record<string, string>;
  ip_addresses: string[] | null;
  last_seen_at: string | null;
  group_id: string | null;
  group_name: string | null;
  fingerprint: string | null;
  approved_at: string | null;
  approved_by: string | null;
  rejected_reason: string | null;
  registered_at: string | null;
}

// ── Assignments ───────────────────────────────────────────

export interface AppInfo {
  id: string;
  name: string;
  version: string;
}

export interface DeviceInfo {
  id: string;
  name: string;
  address: string;
  device_type: string;
}

export interface Assignment {
  id: string;
  app: AppInfo;
  device: DeviceInfo | null;
  collector_id: string;
  schedule_type: string;
  schedule_value: number;
  schedule_human: string;
  config: Record<string, unknown>;
  enabled: boolean;
  use_latest: boolean;
  credential_id: string | null;
  credential_name: string | null;
  credential_overrides?: { alias: string; credential_id: string; credential_name: string }[];
  device_default_credential_name: string | null;
  created_at: string;
}

/** Device-scoped assignment (from GET /v1/apps/assignments?device_id=...) */
export interface DeviceAssignment {
  id: string;
  app: AppInfo;
  app_version_id: string;
  collector_id: string | null;
  schedule_type: string;
  schedule_value: string;
  schedule_human: string;
  config: Record<string, unknown>;
  enabled: boolean;
  use_latest: boolean;
  role: string | null;
  credential_id: string | null;
  credential_name: string | null;
  credential_overrides?: { alias: string; credential_id: string; credential_name: string }[];
  device_default_credential_name: string | null;
  connector_bindings?: ConnectorBindingInfo[];
  created_at: string;
}

// ── Apps ──────────────────────────────────────────────────

export interface AppSummary {
  id: string;
  name: string;
  description: string | null;
  app_type: string;
  target_table: string;
  connector_bindings?: { alias: string; connector_id: string; connector_name: string }[];
}

export interface AppVersion {
  id: string;
  version: string;
  is_latest: boolean;
}

export interface AppConnectorBindingInfo {
  alias: string;
  connector_id: string;
  connector_name: string;
  use_latest: boolean;
  connector_version_id: string | null;
  settings: Record<string, unknown>;
}

export interface AppDetail extends AppSummary {
  config_schema: Record<string, unknown> | null;
  versions: AppVersion[];
  connector_bindings?: AppConnectorBindingInfo[];
}

export interface DisplayTemplate {
  html: string;
  css?: string;
  key_mappings: string[];
}

export interface ConfigKeysResponse {
  source_code_keys: string[];
  clickhouse_keys: string[];
  all_keys: string[];
}

// ── Credentials ───────────────────────────────────────────

export interface Credential {
  id: string;
  name: string;
  description: string;
  credential_type: string;
  template_id: string | null;
  created_at: string;
  updated_at: string;
}

// ── Credential Templates ─────────────────────────────────

export interface CredentialTemplateField {
  key_name: string;
  required: boolean;
  default_value: string | null;
  display_order: number;
}

export interface CredentialTemplate {
  id: string;
  name: string;
  description: string | null;
  fields: CredentialTemplateField[];
  created_at: string;
  updated_at: string;
}

// ── Alerts ────────────────────────────────────────────────

export interface AppAlertDefinition {
  id: string;
  app_id: string;
  app_version_id: string;
  name: string;
  description: string | null;
  expression: string;
  window: string;
  severity: "info" | "warning" | "critical" | "emergency" | "recovery";
  enabled: boolean;
  message_template: string | null;
  notification_channels: Record<string, unknown>[];
  pack_origin: string | null;
  created_at: string;
  updated_at: string;
  instance_count?: number;
  firing_count?: number;
}

export interface AlertInstance {
  id: string;
  definition_id: string;
  assignment_id: string;
  device_id: string | null;
  enabled: boolean;
  state: "ok" | "firing" | "resolved";
  current_value: number | null;
  fire_count: number;
  fire_history: boolean[];
  last_evaluated_at: string | null;
  started_at: string | null;
  resolved_at: string | null;
  event_created: boolean;
  entity_key: string;
  entity_labels: Record<string, string>;
  created_at: string;
  definition_name?: string;
  definition_severity?: string;
  definition_expression?: string;
  app_name?: string;
  device_name?: string;
}

export interface ThresholdOverride {
  id: string;
  definition_id: string;
  device_id: string;
  entity_key: string;
  overrides: Record<string, number | string>;
  created_at: string;
  updated_at: string;
}

export interface AlertMetric {
  name: string;
  type: "numeric" | "string";
  description: string;
}

export interface ExpressionValidation {
  valid: boolean;
  error: string | null;
  referenced_metrics: string[];
  threshold_params: { name: string; default_value: number | string }[];
  has_aggregation: boolean;
}

export interface DeviceThresholdRow {
  definition_id: string;
  name: string;
  app_name: string;
  expression: string;
  severity: string;
  default_thresholds: { name: string; default: number | string }[];
  override: { id: string; overrides: Record<string, number | string> } | null;
  instance_id: string | null;
  instance_enabled: boolean | null;
  instance_state: string | null;
}

// ── Performance Data ─────────────────────────────────────

export interface PerformanceRecord {
  assignment_id: string;
  app_id: string;
  app_name: string;
  device_id: string;
  component: string;
  component_type: string;
  state: number;
  metrics: Record<string, number>;
  metric_names: string[];
  metric_values: number[];
  executed_at: string;
  collector_name: string | null;
}

export interface PerformanceComponentType {
  components: string[];
  metric_names: string[];
}

export interface PerformanceAppSummary {
  app_id: string;
  app_name: string;
  assignment_id: string;
  component_types: Record<string, PerformanceComponentType>;
}

// ── Events ────────────────────────────────────────────────

export interface MonitoringEvent {
  id: string;
  event_type: string;
  definition_id: string;
  definition_name: string;
  policy_id: string;
  policy_name: string;
  collector_id: string;
  device_id: string;
  app_id: string;
  source: string;
  severity: string;
  message: string;
  data: Record<string, unknown>;
  state: string;
  occurred_at: string;
  received_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  cleared_at: string | null;
  cleared_by: string | null;
  collector_name: string;
  device_name: string;
  app_name: string;
}

export interface EventPolicy {
  id: string;
  name: string;
  description: string | null;
  definition_id: string;
  definition_name: string;
  mode: "consecutive" | "cumulative";
  fire_count_threshold: number;
  window_size: number;
  event_severity: string;
  message_template: string | null;
  auto_clear_on_resolve: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

// Legacy aliases for backward compat with DashboardPage
export type ActiveAlert = AlertInstance;
export type AlertRule = AppAlertDefinition;

// ── Health ────────────────────────────────────────────────

export interface HealthStatus {
  status: string;
  version: string;
  instance_id: string;
}

// ── System Health ────────────────────────────────────────

export type SubsystemStatus = "healthy" | "degraded" | "critical" | "unknown";

export interface SubsystemHealth {
  status: SubsystemStatus;
  latency_ms: number | null;
  details: Record<string, unknown>;
}

export interface SystemHealthReport {
  overall_status: SubsystemStatus;
  instance_id: string;
  version: string;
  checked_at: string;
  subsystems: Record<string, SubsystemHealth>;
}

export interface CollectorHealthDetail {
  id: string;
  name: string;
  hostname: string | null;
  status: string;
  last_seen_at: string | null;
  total_jobs: number;
  worker_count: number;
  load_score: number;
  effective_load: number;
  deadline_miss_rate: number;
  group_name: string | null;
  ip_addresses: Record<string, string[]> | null;
  labels: Record<string, string> | null;
  container_states: Record<string, string> | null;
  queue_stats: {
    pending_results: number;
    jobs_overdue: number;
    jobs_errored_last_hour: number;
    avg_execution_ms: number;
    max_execution_ms: number;
  } | null;
}

// ── Users ─────────────────────────────────────────────────

export interface User {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  role: string;
  role_id: string | null;
  role_name: string | null;
  all_tenants: boolean;
  is_active: boolean;
  created_at: string;
  tenant_count?: number;
}

// ── Roles (RBAC) ─────────────────────────────────────────

export interface Permission {
  id: string;
  resource: string;
  action: string;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: Permission[];
  created_at: string;
  updated_at: string;
}

export type ResourceActions = Record<string, string[]>;

export interface UserWithTenants extends User {
  tenants: { id: string; name: string }[];
}

// ── User API Keys ────────────────────────────────────────

export interface UserApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  expires_at: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface UserApiKeyWithRaw extends UserApiKey {
  raw_key: string;
}

// ── SNMP OIDs ─────────────────────────────────────────────

export interface SnmpOid {
  id: string;
  name: string;
  oid: string;
  description: string | null;
}

// ── Monitoring Config ──────────────────────────────────────

export interface MonitoringCheckConfig {
  app_name: string | null;
  config: Record<string, unknown>;
  interval_seconds: number;
}

export interface MonitoringConfig {
  availability: MonitoringCheckConfig | null;
  latency: MonitoringCheckConfig | null;
  interface: MonitoringCheckConfig | null;
}

// ── Interface Results ─────────────────────────────────

export interface InterfaceRecord {
  assignment_id: string;
  collector_id: string;
  app_id: string;
  device_id: string;
  interface_id: string;
  if_index: number;
  if_name: string;
  if_alias: string;
  if_speed_mbps: number;
  if_admin_status: string;
  if_oper_status: string;
  in_octets: number;
  out_octets: number;
  in_errors: number;
  out_errors: number;
  in_discards: number;
  out_discards: number;
  in_unicast_pkts: number;
  out_unicast_pkts: number;
  in_rate_bps: number;
  out_rate_bps: number;
  in_utilization_pct: number;
  out_utilization_pct: number;
  poll_interval_sec: number;
  state: number;
  executed_at: string;
  collector_name: string;
  device_name: string;
  app_name: string;
  tenant_id: string;
}

export interface InterfaceRollupRecord {
  device_id: string;
  interface_id: string;
  hour?: string;
  day?: string;
  in_rate_min: number;
  in_rate_max: number;
  in_rate_avg: number;
  in_rate_p95: number;
  out_rate_min: number;
  out_rate_max: number;
  out_rate_avg: number;
  out_rate_p95: number;
  in_utilization_max: number;
  in_utilization_avg: number;
  out_utilization_max: number;
  out_utilization_avg: number;
  in_octets_total: number;
  out_octets_total: number;
  in_errors_total: number;
  out_errors_total: number;
  availability_pct: number;
  sample_count: number;
  if_speed_mbps: number;
  if_name: string;
}

export interface InterfaceMetadataRecord {
  id: string;
  device_id: string;
  if_name: string;
  current_if_index: number;
  if_descr: string;
  if_alias: string;
  if_speed_mbps: number;
  polling_enabled: boolean;
  alerting_enabled: boolean;
  poll_metrics: string;
  updated_at: string | null;
}

// ── Label Keys ───────────────────────────────────────────

export interface LabelKey {
  id: string;
  key: string;
  description: string | null;
  color: string | null;
  show_description: boolean;
  predefined_values: string[];
  created_at: string;
}

// ── System Settings ──────────────────────────────────────

export interface SystemSettings {
  [key: string]: string;
}

// ── TLS Certificates ─────────────────────────────────────

export interface TlsCertificateInfo {
  id: string;
  name: string;
  is_self_signed: boolean;
  subject_cn: string;
  valid_from: string;
  valid_to: string;
  is_active: boolean;
  created_at: string;
}

// ── Templates ────────────────────────────────────────────

export interface Template {
  id: string;
  name: string;
  description: string | null;
  config: {
    apps?: { app_id: string; schedule_type: string; schedule_value: string; config: Record<string, unknown>; role?: string }[];
    default_credential_id?: string;
    labels?: Record<string, string>;
  };
  created_at: string;
  updated_at: string;
}

// ── Credential Detail ────────────────────────────────────

export interface CredentialDetail extends Credential {
  values: { key_name: string; is_secret: boolean; value: string | null }[];
}

// ── Python Modules ──────────────────────────────────────

export interface PythonModuleSummary {
  id: string;
  name: string;
  description: string | null;
  homepage_url: string | null;
  is_approved: boolean;
  version_count: number;
  wheel_count: number;
  dep_total: number;
  dep_missing: number;
  dep_missing_names: string[];
  is_dependency_of: string[];
  created_at: string;
}

export interface WheelFileInfo {
  id: string;
  filename: string;
  sha256_hash: string;
  file_size: number;
  python_tag: string;
  abi_tag: string;
  platform_tag: string;
}

export interface PythonModuleVersionDetail {
  id: string;
  version: string;
  dependencies: string[];
  python_requires: string | null;
  is_verified: boolean;
  wheel_files: WheelFileInfo[];
  dep_missing: string[];
  dep_resolved: string[];
  created_at: string;
}

export interface PythonModuleDetail {
  id: string;
  name: string;
  description: string | null;
  homepage_url: string | null;
  is_approved: boolean;
  created_at: string;
  versions: PythonModuleVersionDetail[];
}

export interface MissingDependency {
  name: string;
  version_spec: string;
  registered: boolean;
}

export interface DependencyWarning {
  package: string;
  message: string;
  severity: "error" | "warning" | "info";
}

export interface ResolveResult {
  requirements: string[];
  all_dependencies: string[];
  missing_dependencies: MissingDependency[];
  warnings: DependencyWarning[];
}

export interface WheelUploadResult {
  module_id: string;
  module_name: string;
  version: string;
  wheel_filename: string;
  file_size: number;
  sha256: string;
  missing_dependencies: MissingDependency[];
}

export interface NetworkStatus {
  mode: "offline" | "proxy" | "direct";
  proxy_configured: boolean;
}

export interface PyPISearchResult {
  name: string;
  summary: string | null;
  latest_version: string;
  registered: boolean;
}

// ── Connectors ────────────────────────────────────────────

export interface ConnectorSummary {
  id: string;
  name: string;
  description: string | null;
  connector_type: string;
  is_builtin: boolean;
  version_count: number;
  latest_version: string | null;
  latest_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorVersionDetail {
  id: string;
  version: string;
  source_code: string | null;
  requirements: string[] | null;
  entry_class: string;
  is_latest: boolean;
  checksum: string | null;
  created_at: string;
}

export interface ConnectorDetail {
  id: string;
  name: string;
  description: string | null;
  connector_type: string;
  is_builtin: boolean;
  versions: { id: string; version: string; is_latest: boolean }[];
  created_at: string;
  updated_at: string;
}

export interface ConnectorBindingInfo {
  id: string;
  alias: string;
  connector_id: string;
  connector_version_id: string;
  credential_id: string | null;
  use_latest: boolean;
  settings: Record<string, unknown>;
}

// ── Packs ────────────────────────────────────────────────

export interface Pack {
  id: string;
  pack_uid: string;
  name: string;
  description: string | null;
  author: string | null;
  current_version: string;
  installed_at: string;
  updated_at: string;
  entity_counts: Record<string, number>;
}

export interface PackVersion {
  id: string;
  version: string;
  manifest: Record<string, string[]>;
  changelog: string | null;
  imported_at: string;
}

export interface PackDetail extends Pack {
  versions: PackVersion[];
}

export interface PackImportPreviewEntity {
  section: string;
  name: string;
  status: "new" | "conflict" | "unchanged";
  existing_pack: string | null;
}

export interface PackImportPreview {
  pack_uid: string;
  name: string;
  version: string;
  is_upgrade: boolean;
  current_version?: string;
  entities: PackImportPreviewEntity[];
}

export interface AvailableEntity {
  id: string;
  name: string;
  description: string | null;
  pack_id: string | null;
}

export type AvailableEntities = Record<string, AvailableEntity[]>;

export interface PackImportResult {
  pack_id: string;
  version: string;
  created: number;
  updated: number;
  skipped: number;
}

// ── Docker Infrastructure types ──────────────────────────────────────────────

export interface DockerHostInfo {
  label: string;
  url: string;
}

export interface DockerSystemInfo {
  hostname: string;
  docker: {
    version: string;
    api_version: string;
    storage_driver: string;
    os: string;
    kernel: string;
    architecture: string;
    cpus: number;
    memory_bytes: number;
  };
  host: {
    load_avg: { "1m": number; "5m": number; "15m": number } | null;
    cpu_count: number;
    mem_total_bytes: number | null;
    mem_available_bytes: number | null;
    mem_free_bytes: number | null;
    mem_buffers_bytes: number | null;
    mem_cached_bytes: number | null;
    swap_total_bytes: number | null;
    swap_free_bytes: number | null;
    uptime_seconds: number | null;
    disk_total_bytes: number | null;
    disk_used_bytes: number | null;
    disk_free_bytes: number | null;
  };
  containers: {
    running: number;
    paused: number;
    stopped: number;
    total: number;
  };
}

export interface DockerContainerLog {
  container: string;
  lines: string[];
  count: number;
  buffer_size: number;
}

export interface DockerEvent {
  time: number;
  time_iso: string;
  type: string;
  action: string;
  actor_id: string;
  actor_name: string;
  actor_image: string;
  exit_code: string | null;
}

export interface DockerEventsResponse {
  events: DockerEvent[];
  count: number;
  buffer_size: number;
  oldest_ts: number | null;
}

export interface DockerImageInfo {
  id: string;
  tags: string[];
  size_bytes: number;
  created: string;
  dangling: boolean;
}

export interface DockerVolumeInfo {
  name: string;
  driver: string;
  mountpoint: string;
  created: string;
}

export interface DockerImagesResponse {
  images: DockerImageInfo[];
  volumes: DockerVolumeInfo[];
  space_summary: {
    images_total_bytes: number;
    images_reclaimable_bytes: number;
    volumes_total_bytes: number;
    build_cache_bytes: number;
  } | null;
  image_count: number;
  dangling_count: number;
  volume_count: number;
}

export interface DockerOverviewHost {
  label: string;
  status: "ok" | "unreachable";
  data: DockerSystemInfo | null;
  error?: string;
}

export interface DockerOverviewResponse {
  configured: boolean;
  hosts: DockerOverviewHost[];
}
