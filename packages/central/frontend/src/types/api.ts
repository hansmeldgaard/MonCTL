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
  all_tenants?: boolean;
  tenant_ids?: string[] | null; // null = unrestricted, [] = see nothing, [ids] = specific
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
  created_at: string;
}

// ── Tenants ───────────────────────────────────────────────

export interface Tenant {
  id: string;
  name: string;
  created_at: string;
}

// ── Collector Groups ──────────────────────────────────────

export interface CollectorGroup {
  id: string;
  name: string;
  description: string | null;
  collector_count: number;
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
  created_at?: string;
  updated_at?: string;
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
  created_at: string;
}

/** Device-scoped assignment (from GET /v1/apps/assignments?device_id=...) */
export interface DeviceAssignment {
  id: string;
  app: AppInfo;
  collector_id: string | null;
  schedule_type: string;
  schedule_value: string;
  schedule_human: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

// ── Apps ──────────────────────────────────────────────────

export interface AppSummary {
  id: string;
  name: string;
  description: string | null;
  app_type: string;
}

export interface AppVersion {
  id: string;
  version: string;
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

// ── Users ─────────────────────────────────────────────────

export interface User {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  role: string;
  all_tenants: boolean;
  is_active: boolean;
  created_at: string;
  tenant_count?: number;
}

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
  app_type: string | null;
  port: number | null;
  oid: string | null;
  credential_name: string | null;
  interval_seconds: number;
}

export interface MonitoringConfig {
  availability: MonitoringCheckConfig | null;
  latency: MonitoringCheckConfig | null;
}
