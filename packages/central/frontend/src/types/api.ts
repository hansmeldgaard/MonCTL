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
  table_page_size: number;
  table_scroll_mode: "paginated" | "infinite";
  idle_timeout_minutes: number;
  iface_status_filter: "all" | "up" | "down" | "unmonitored";
  iface_traffic_unit: "auto" | "kbps" | "mbps" | "gbps" | "pct";
  iface_chart_metric: "traffic" | "errors" | "discards";
  iface_time_range: "1h" | "6h" | "24h" | "7d" | "30d";
  default_page?: string;
  all_tenants?: boolean;
  tenant_ids?: string[] | null; // null = unrestricted, [] = see nothing, [ids] = specific
  permissions?: string[] | null; // null = admin (full access), ["resource:action", ...]
}

export interface LoginPayload {
  username: string;
  password: string;
}

// ── Device Categories (groupings like cisco-router, host) ─

export interface DeviceCategory {
  id: string;
  name: string;
  description: string | null;
  category: string;
  icon: string | null;
  has_custom_icon: boolean;
  pack_id: string | null;
  created_at: string;
}

// ── Device Types (specific hardware models with OID) ─────

export interface DeviceType {
  id: string;
  name: string;
  sys_object_id_pattern: string;
  device_category_id: string;
  device_category_name: string | null;
  vendor: string | null;
  model: string | null;
  os_family: string | null;
  description: string | null;
  priority: number;
  pack_id: string | null;
  created_at: string;
}

export interface DeviceCategoryListMeta {
  limit: number;
  offset: number;
  count: number;
  total: number;
  category_counts: Record<string, number>;
}

export interface DeviceCategoryCounts {
  categories: Record<string, number>;
  total: number;
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
  device_category: string;
  device_type_id: string | null;
  device_type_name: string | null;
  device_type_vendor: string | null;
  device_type_model: string | null;
  device_type_os_family: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  collector_group_id: string | null;
  collector_group_name: string | null;
  labels: Record<string, string>;
  is_enabled: boolean;
  credentials: Record<string, { id: string; name: string; credential_type: string }>;
  metadata: Record<string, unknown> | null;
  retention_overrides: Record<string, string>;
  interface_rules: InterfaceRule[] | null;
  created_at?: string;
  updated_at?: string;
}

export interface DeviceBulkPatchRequest {
  device_ids: string[];
  is_enabled?: boolean;
  collector_group_id?: string;
  tenant_id?: string;
}

export interface DeviceBulkPatchResult {
  updated: number;
  skipped: number;
}

export interface ListParams {
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  [key: string]: string | number | undefined;
}

export interface BulkUpdateAssignmentsRequest {
  assignment_ids: string[];
  schedule_type?: string | null;
  schedule_value?: string | null;
  credential_id?: string | null;
  enabled?: boolean | null;
  app_version_id?: string | null;
  use_latest?: boolean | null;
}

export interface DeviceListParams {
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  name?: string;
  address?: string;
  device_category?: string;
  device_type_name?: string;
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
  metric_names?: string[];
  metric_values?: number[];
}

export interface DeviceResults {
  device_id: string;
  device_name: string;
  device_address: string;
  device_category: string;
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
  log_level_filter?: string;
  ws_connected?: boolean;
  ws_connection?: CollectorWsConnection | null;
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
  device_category: string;
  device_type_name?: string | null;
  collector_group_name?: string | null;
}

export interface Assignment {
  id: string;
  app: AppInfo;
  device: DeviceInfo | null;
  collector_id: string | null;
  collector_name: string | null;
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
  updated_at?: string | null;
}

/** Device-scoped assignment (from GET /v1/apps/assignments?device_id=...) */
export interface DeviceAssignment {
  id: string;
  app: AppInfo;
  app_version_id: string;
  collector_id: string | null;
  collector_name: string | null;
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

export interface EligibilityRun {
  run_id: string;
  app_id: string;
  app_name: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  total_devices: number;
  tested: number;
  eligible: number;
  ineligible: number;
  unreachable: number;
  triggered_by: string;
}

export interface EligibilityDeviceResult {
  device_id: string;
  device_name: string;
  device_address: string;
  eligible: 0 | 1 | 2;
  already_assigned: number;
  oid_results?: string;
  reason?: string;
}

export interface EligibilityOidCheck {
  oid: string;
  check: "exists" | "equals";
  value?: string;
}

export interface AppSummary {
  id: string;
  name: string;
  description: string | null;
  app_type: string;
  target_table: string;
  vendor_oid_prefix?: string | null;
  connector_bindings?: { alias: string; connector_id: string; connector_name: string }[];
}

export interface AppVersion {
  id: string;
  version: string;
  is_latest: boolean;
  eligibility_oids?: EligibilityOidCheck[];
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

export interface CredentialType {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

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
  credential_type: string;
  description: string | null;
  fields: CredentialTemplateField[];
  created_at: string;
  updated_at: string;
}

// ── Alerts ────────────────────────────────────────────────

export interface AlertDefinition {
  id: string;
  app_id: string;
  name: string;
  description: string | null;
  expression: string;
  window: string;
  enabled: boolean;
  message_template: string | null;
  pack_origin: string | null;
  created_at: string;
  updated_at: string;
  instance_count?: number;
  firing_count?: number;
}

/** @deprecated Use AlertDefinition */
export type AppAlertDefinition = AlertDefinition;

export interface AlertEntity {
  id: string;
  definition_id: string;
  assignment_id: string;
  device_id: string | null;
  enabled: boolean;
  state: "ok" | "firing" | "resolved";
  display_state: "active" | "cleared" | null;
  current_value: number | null;
  fire_count: number;
  fire_history: boolean[];
  last_evaluated_at: string | null;
  started_firing_at: string | null;
  last_cleared_at: string | null;
  entity_key: string;
  entity_labels: Record<string, string>;
  metric_values: Record<string, number | null>;
  threshold_values: Record<string, number>;
  created_at: string;
  definition_name?: string;
  definition_expression?: string;
  app_name?: string;
  device_name?: string;
}

/** @deprecated Use AlertEntity */
export type AlertInstance = AlertEntity;

export interface AlertLogEntry {
  id: string;
  definition_id: string;
  definition_name: string;
  entity_key: string;
  action: "fire" | "clear";
  severity: string;
  current_value: number;
  threshold_value: number;
  expression: string;
  device_id: string;
  device_name: string;
  app_name: string;
  entity_labels: Record<string, string>;
  fire_count: number;
  message: string;
  metric_values: Record<string, number | null>;
  threshold_values: Record<string, number>;
  occurred_at: string;
}

export interface ThresholdVariable {
  id: string;
  app_id: string;
  name: string;
  display_name: string | null;
  description: string | null;
  default_value: number;
  app_value: number | null;
  unit: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThresholdOverride {
  id: string;
  variable_id: string;
  device_id: string;
  entity_key: string;
  value: number;
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
  errors: string[];
  warnings: string[];
  error: string | null;  // backward compat
  referenced_metrics: string[];
  threshold_params: { name: string; default_value: number | string; param_key?: string }[];
  has_aggregation: boolean;
  has_arithmetic: boolean;
  has_division: boolean;
  threshold_refs: {
    name: string;
    is_named: boolean;
    inline_value: number | null;
  }[];
}

export interface DeviceThresholdRow {
  variable_id: string;
  name: string;
  display_name: string | null;
  unit: string | null;
  app_name: string;
  expression_default: number;
  app_value: number | null;
  device_value: number | null;
  effective_value: number;
  device_override_id: string | null;
  entity_overrides: {
    override_id: string;
    entity_key: string;
    entity_labels: Record<string, string>;
    value: number;
  }[];
  used_by_definitions: {
    definition_id: string;
    definition_name: string;
  }[];
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
  metric_types: string[];
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
export type ActiveAlert = AlertEntity;
export type AlertRule = AlertDefinition;

// ── Health ────────────────────────────────────────────────

export interface HealthStatus {
  status: string;
  version: string;
  instance_id: string;
}

// ── System Health ────────────────────────────────────────

export type SubsystemStatus = "healthy" | "degraded" | "critical" | "unknown" | "unconfigured";

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
  system_resources: {
    cpu_load: number[];
    cpu_count: number;
    memory_total_mb: number;
    memory_used_mb: number;
    disk_total_gb: number;
    disk_used_gb: number;
  } | null;
  capacity_status: "ok" | "warning" | "critical";
  capacity_warnings: string[] | null;
  weight: number | null;
}

export interface CollectorErrorAnalytics {
  collector_name: string;
  hours: number;
  top_errors: { message: string; count: number; category: string }[];
  app_errors: { app: string; errors: number; total: number }[];
  category_counts: Record<string, number>;
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
  counter_bits: number;
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
  rules_managed: boolean;
  updated_at: string | null;
}

// ── Interface Rules ──────────────────────────────────────

export interface InterfaceRuleStringMatch {
  pattern: string;
  type: "glob" | "regex" | "exact";
}

export interface InterfaceRuleNumericMatch {
  op: "eq" | "gt" | "lt" | "gte" | "lte";
  value: number;
}

export interface InterfaceRuleMatch {
  if_alias?: InterfaceRuleStringMatch;
  if_name?: InterfaceRuleStringMatch;
  if_descr?: InterfaceRuleStringMatch;
  if_speed_mbps?: InterfaceRuleNumericMatch;
}

export interface InterfaceRuleSettings {
  polling_enabled?: boolean;
  alerting_enabled?: boolean;
  poll_metrics?: string;
}

export interface InterfaceRule {
  name: string;
  match: InterfaceRuleMatch;
  settings: InterfaceRuleSettings;
  priority: number;
}

export interface InterfaceRuleEvaluationSummary {
  total: number;
  matched: number;
  changed: number;
  skipped_manual: number;
  unmatched: number;
}

export interface InterfaceRulePreviewItem {
  interface_id: string;
  if_name: string;
  if_alias: string;
  if_descr: string;
  if_speed_mbps: number;
  rules_managed: boolean;
  matched_rule: string | null;
  current_settings: InterfaceRuleSettings;
  proposed_settings: InterfaceRuleSettings;
  would_change: boolean;
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
  san_list: string[];
  fingerprint: string;
}

// ── Templates ────────────────────────────────────────────

export interface TemplateMonitoringCheck {
  app_name: string;
  config: Record<string, unknown>;
  interval_seconds: number;
  credential_id?: string | null; // UUID or "device_default"
}

export interface TemplateMonitoringConfig {
  availability?: TemplateMonitoringCheck | null;
  latency?: TemplateMonitoringCheck | null;
  interface?: TemplateMonitoringCheck | null;
}

export interface TemplateAppEntry {
  app_name: string;
  schedule_type: string;
  schedule_value: string;
  config: Record<string, unknown>;
  role?: string;
  credential_id?: string | null; // UUID or "device_default"
}

export interface TemplateConfig {
  monitoring?: TemplateMonitoringConfig;
  apps?: TemplateAppEntry[];
  credentials?: Record<string, string>;
  default_collector_group_id?: string;
  labels?: Record<string, string>;
  interface_rules?: InterfaceRule[];
}

export interface Template {
  id: string;
  name: string;
  description: string | null;
  config: TemplateConfig;
  created_at: string;
  updated_at: string;
}

// ── Template Bindings ────────────────────────────────────

export interface TemplateBinding {
  id: string;
  device_category_id?: string;
  device_category_name?: string;
  device_type_id?: string;
  device_type_name?: string;
  template_id: string;
  template_name: string;
  step: number;
  created_at: string;
}

export interface TemplateSourceInfo {
  template_id: string;
  template_name: string;
  level: "category" | "device_type";
  category_name?: string;
  device_type_name?: string;
  step: number;
}

export interface ResolvedTemplateResult {
  device_id: string;
  device_name: string;
  device_address: string;
  resolved_config: TemplateConfig;
  source_templates: TemplateSourceInfo[];
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
  status: "new" | "conflict" | "unchanged" | "info" | "upgrade";
  existing_pack: string | null;
  current_version?: string | null;
  incoming_version?: string | null;
  has_changes?: boolean;
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

export interface DockerContainerStats {
  name: string;
  image?: string;
  status: string;
  health: string | null;
  cpu_pct: number | null;
  mem_usage_bytes: number | null;
  mem_limit_bytes: number | null;
  mem_pct: number | null;
  net_rx_bytes: number | null;
  net_tx_bytes: number | null;
  restart_count: number;
  started_at?: string;
  block_read_bytes?: number | null;
  block_write_bytes?: number | null;
  pids?: number | null;
}

export interface DockerOverviewHost {
  label: string;
  tier?: "central" | "worker";
  status: "ok" | "degraded" | "unreachable" | "stale" | "unknown";
  container_count?: number;
  total_containers?: number;
  unhealthy_count?: number;
  last_seen?: string | null;
  data: DockerSystemInfo | null;
  error?: string;
}

export interface DockerOverviewResponse {
  configured: boolean;
  hosts: DockerOverviewHost[];
}

// ── Config History ─────────────────────────────────────────

export interface ConfigChangeEntry {
  device_id: string;
  device_name: string;
  app_id: string;
  app_name: string;
  component_type: string;
  component: string;
  config_key: string;
  config_value: string;
  config_hash: string;
  executed_at: string;
}

export interface ConfigChangeTimestamp {
  change_time: string;
  change_count: number;
  changed_keys: string[];
}

export interface ConfigDiffEntry {
  component_type: string;
  component: string;
  config_key: string;
  value_a: string | null;
  value_b: string | null;
  change_type: "added" | "removed" | "modified" | "unchanged";
}

export interface ConfigCompareResult {
  time_a: string;
  time_b: string;
  changes: ConfigDiffEntry[];
  unchanged: ConfigDiffEntry[];
  total_keys_a: number;
  total_keys_b: number;
}

export interface DeviceRetentionEntry {
  app_id: string;
  app_name: string;
  data_type: string;
  retention_days: number;
  source: "global_default" | "device_override";
  override_id: string | null;
}

export interface RetentionDefaults {
  config: number;
  performance: number;
  availability_latency: number;
  interface: number;
}

// ── Upgrades ─────────────────────────────────────────────────────────────

export interface SystemVersionNode {
  id: string;
  hostname: string;
  role: string;
  ip: string;
  monctl_version: string | null;
  os_version: string | null;
  kernel_version: string | null;
  python_version: string | null;
  reboot_required: boolean;
  group_name: string | null;
  last_reported_at: string | null;
}

export interface UpgradePackageInfo {
  id: string;
  version: string;
  package_type: string;
  filename: string;
  file_size: number;
  sha256_hash: string;
  changelog: string | null;
  contains_central: boolean;
  contains_collector: boolean;
  uploaded_by: string | null;
  created_at: string;
}

export interface UpgradeStatus {
  nodes: SystemVersionNode[];
  packages: UpgradePackageInfo[];
}

export interface UpgradeJobStep {
  id: string;
  step_order: number;
  node_hostname: string;
  node_role: string;
  node_ip: string;
  action: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  output_log: string | null;
  error_message: string | null;
}

export interface UpgradeJob {
  id: string;
  target_version: string;
  scope: string;
  strategy: string;
  status: string;
  started_by: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  steps: UpgradeJobStep[];
}

export interface OsPackageInfo {
  id: string;
  package_name: string;
  version: string;
  architecture: string;
  filename: string;
  file_size: number;
  severity: string;
  source: string;
  is_downloaded: boolean;
}

// ── OS Updates ──────────────────────────────────────────

export interface OsUpdateEntry {
  id: string;
  package: string;
  current: string;
  new: string;
  severity: string;
  is_downloaded: boolean;
  checked_at: string;
}

export interface OsUpdateByNode {
  [hostname: string]: OsUpdateEntry[];
}

export interface OsCheckResult {
  [hostname: string]: {
    status: string;
    update_count?: number;
    updates?: Array<{ package: string; current: string; new: string; severity: string }>;
    error?: string;
  };
}

export interface OsCachedPkg {
  id: string;
  package: string;
  version: string;
  architecture: string;
  filename: string;
  file_size: number;
  sha256: string;
  source: string;
  created_at: string;
}

export interface OsInstallResult {
  output: string;
  returncode: number;
  success: boolean;
  error?: string;
}

export interface OsInstallJobStep {
  id: string;
  step_order: number;
  node_hostname: string;
  node_role: string;
  node_ip: string;
  action: string;
  status: string;
  is_test_node: boolean;
  started_at: string | null;
  completed_at: string | null;
  output_log: string | null;
  error_message: string | null;
}

export interface OsInstallJob {
  id: string;
  package_names: string[];
  scope: string;
  target_nodes: string[] | null;
  strategy: string;
  restart_policy: string;
  status: string;
  started_by: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string | null;
  steps: OsInstallJobStep[];
}

export interface PackageNodeStatus {
  hostname: string;
  role: string;
  current_version: string;
  status: "installed" | "pending" | "unknown";
}

export interface PackageInventoryItem {
  package_name: string;
  new_version: string;
  severity: string;
  requires_reboot: boolean;
  downloaded: boolean;
  total_nodes: number;
  installed_count: number;
  nodes: PackageNodeStatus[];
}

export interface UpgradeBadge {
  os_update_count: number;
}

// ── Dashboard Summary ───────────────────────────────────────────────────────

export interface DashboardAlertSummary {
  total_firing: number;
  recent: DashboardRecentAlert[];
}

export interface DashboardRecentAlert {
  id: string;
  definition_name: string;
  device_name: string;
  device_id: string | null;
  entity_key: string;
  current_value: number | null;
  fire_count: number;
  started_at: string | null;
}

export interface DashboardDeviceHealth {
  total: number;
  up: number;
  down: number;
  degraded: number;
  worst: DashboardWorstDevice[];
}

export interface DashboardWorstDevice {
  device_id: string;
  device_name: string;
  device_address: string;
  reason: "down" | "degraded";
  firing_alerts: number;
}

export interface DashboardCollectorStatus {
  total: number;
  online: number;
  offline: number;
  pending: number;
  stale: DashboardStaleCollector[];
}

export interface DashboardStaleCollector {
  collector_id: string;
  name: string;
  last_seen: string | null;
  stale_seconds: number | null;
}

export interface DashboardTopNEntry {
  device_id: string;
  device_name: string;
  component?: string;
  interface?: string;
  value: number;
  unit: string;
  in_rate_bps?: number;
  out_rate_bps?: number;
  speed_mbps?: number;
  executed_at: string | null;
}

export interface DashboardPerformanceTopN {
  cpu: DashboardTopNEntry[];
  memory: DashboardTopNEntry[];
  bandwidth: DashboardTopNEntry[];
}

export interface DashboardSummary {
  alert_summary: DashboardAlertSummary;
  device_health: DashboardDeviceHealth;
  collector_status: DashboardCollectorStatus;
  performance_top_n: DashboardPerformanceTopN;
}

// ── Logs (ClickHouse) ─────────────────────────────────────

export interface LogEntry {
  timestamp: string;
  collector_id: string;
  collector_name: string;
  host_label: string;
  source_type: string;
  container_name: string;
  image_name: string;
  level: string;
  stream: string;
  message: string;
}

export interface LogQueryResponse {
  data: LogEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface LogFiltersResponse {
  collectors: string[];
  containers: string[];
  hosts: string[];
  levels: string[];
  source_types: string[];
}

// ── WebSocket Status ──────────────────────────────────────

export interface CollectorWsConnection {
  collector_id: string;
  name: string;
  connected_at: string;
  last_seen_at: string;
}

export interface CollectorWsStatus {
  connected: boolean;
  connection: CollectorWsConnection | null;
}

// ── Analytics ────────────────────────────────────────────────────────────────

export interface AnalyticsTableColumn {
  name: string;
  type: string;
}

export interface AnalyticsTable {
  name: string;
  engine: string;
  total_rows: number;
  total_bytes: number;
  columns: AnalyticsTableColumn[];
}

export interface QueryResultColumn {
  name: string;
  type: string;
}

export interface QueryResult {
  columns: QueryResultColumn[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  execution_time_ms: number;
  query: string;
}

// ── Custom Dashboards ────────────────────────────────────────────────────────

export interface DashboardVariable {
  name: string;
  type: string;
  default_value: string;
}

export interface AnalyticsWidgetConfig {
  sql: string;
  chart_type: "table" | "line" | "bar" | "area" | "pie";
  x_column?: string;
  y_columns?: string[];
  group_by?: string;
  refresh_seconds?: number;
  publishes?: { column: string; variable: string };
}

export interface AnalyticsWidgetLayout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface AnalyticsWidget {
  id: string;
  title: string;
  config: AnalyticsWidgetConfig;
  layout: AnalyticsWidgetLayout;
}

export interface AnalyticsDashboard {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  owner_name: string;
  widgets: AnalyticsWidget[];
  variables?: DashboardVariable[];
  created_at: string;
  updated_at: string;
}

export interface AnalyticsDashboardSummary {
  id: string;
  name: string;
  description: string;
  owner_name: string;
  widget_count: number;
  updated_at: string;
}

// ── Automations ───────────────────────────────────────────

export interface Action {
  id: string;
  name: string;
  description: string | null;
  target: "collector" | "central";
  source_code: string;
  credential_type: string | null;
  credential_id: string | null;
  timeout_seconds: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AutomationStep {
  id: string;
  action_id: string;
  action_name: string;
  action_target: "collector" | "central";
  step_order: number;
  credential_type_override: string | null;
  timeout_override: number | null;
}

export interface Automation {
  id: string;
  name: string;
  description: string | null;
  trigger_type: "event" | "cron";
  event_severity_filter: string | null;
  event_policy_ids: string[] | null;
  event_label_filter: Record<string, string> | null;
  cron_expression: string | null;
  cron_device_label_filter: Record<string, string> | null;
  cron_device_ids: string[] | null;
  device_ids: string[] | null;
  device_label_filter: Record<string, string> | null;
  cooldown_seconds: number;
  enabled: boolean;
  steps: AutomationStep[];
  created_at: string;
  updated_at: string;
}

export interface AutomationRunStepResult {
  step: number;
  action_id: string;
  action_name: string;
  target: "collector" | "central";
  status: "success" | "failed" | "timeout" | "skipped";
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
  output_data: Record<string, unknown>;
}

export interface AutomationRun {
  run_id: string;
  automation_id: string;
  automation_name: string;
  trigger_type: "event" | "cron" | "manual";
  event_id: string;
  event_severity: string;
  event_message: string;
  device_id: string;
  device_name: string;
  device_ip: string;
  collector_id: string;
  collector_name: string;
  status: "running" | "success" | "failed" | "timeout";
  total_steps: number;
  completed_steps: number;
  failed_step: number;
  step_results: AutomationRunStepResult[];
  shared_data: Record<string, unknown>;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  triggered_by: string;
}
