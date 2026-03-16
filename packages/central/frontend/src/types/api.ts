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
  created_at: string;
}

// ── Apps ──────────────────────────────────────────────────

export interface AppSummary {
  id: string;
  name: string;
  description: string | null;
  app_type: string;
  target_table: string;
}

export interface AppVersion {
  id: string;
  version: string;
  is_latest: boolean;
}

export interface AppDetail extends AppSummary {
  config_schema: Record<string, unknown> | null;
  versions: AppVersion[];
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

export interface ActiveAlert {
  id: string;
  rule_id: string;
  state: string;
  labels: Record<string, string>;
  started_at: string;
}

export interface AlertRule {
  id: string;
  name: string;
  rule_type: string;
  severity: string;
  enabled: boolean;
}

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
