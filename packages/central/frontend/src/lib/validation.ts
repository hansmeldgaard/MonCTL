/**
 * Shared input validation for MonCTL frontend.
 * Each validator returns an error message string or null if valid.
 */

// ── Constants ──────────────────────────────────────────────

export const MAX_NAME_LENGTH = 255;
export const MAX_SHORT_NAME_LENGTH = 64;
export const MAX_DESCRIPTION_LENGTH = 2000;
export const MAX_LABEL_KEY_LENGTH = 64;
export const MAX_LABEL_VALUE_LENGTH = 255;

// ── Pattern validators ─────────────────────────────────────

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,126}[a-z0-9]$/;
const LABEL_KEY_RE = /^[a-z][a-z0-9_-]{0,62}[a-z0-9]$/;
const OID_RE = /^(\d+\.){2,}\d+$/;
const SEMVER_RE = /^\d+\.\d+(\.\d+)?$/;
const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
const HOSTNAME_RE = /^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$/;
const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const IPV6_RE = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/;
const ALERT_WINDOW_RE = /^\d+[smh]$/;
const USERNAME_RE = /^[a-zA-Z0-9._@-]+$/;
const TIMEZONE_RE = /^[A-Za-z_/]+$/;

// ── Generic validators ─────────────────────────────────────

export type ValidationResult = string | null;

export function required(
  value: string | undefined | null,
  fieldName = "This field",
): ValidationResult {
  if (!value || value.trim() === "") return `${fieldName} is required`;
  return null;
}

export function minLength(
  value: string,
  min: number,
  fieldName = "Value",
): ValidationResult {
  if (value.length < min)
    return `${fieldName} must be at least ${min} characters`;
  return null;
}

export function maxLength(
  value: string,
  max: number,
  fieldName = "Value",
): ValidationResult {
  if (value.length > max)
    return `${fieldName} must be at most ${max} characters`;
  return null;
}

export function lengthRange(
  value: string,
  min: number,
  max: number,
  fieldName = "Value",
): ValidationResult {
  return minLength(value, min, fieldName) ?? maxLength(value, max, fieldName);
}

export function numberRange(
  value: number,
  min: number,
  max: number,
  fieldName = "Value",
): ValidationResult {
  if (value < min) return `${fieldName} must be at least ${min}`;
  if (value > max) return `${fieldName} must be at most ${max}`;
  return null;
}

// ── Domain-specific validators ─────────────────────────────

export function validateName(
  value: string,
  fieldName = "Name",
): ValidationResult {
  return (
    required(value, fieldName) ??
    lengthRange(value.trim(), 1, MAX_NAME_LENGTH, fieldName)
  );
}

export function validateShortName(
  value: string,
  fieldName = "Name",
): ValidationResult {
  return (
    required(value, fieldName) ??
    lengthRange(value.trim(), 1, MAX_SHORT_NAME_LENGTH, fieldName)
  );
}

export function validateDescription(value: string): ValidationResult {
  if (value && value.length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be at most ${MAX_DESCRIPTION_LENGTH} characters`;
  }
  return null;
}

export function validateAddress(value: string): ValidationResult {
  const err = required(value, "Address");
  if (err) return err;
  const v = value.trim();
  if (v.length > 500) return "Address too long (max 500 characters)";

  if (IPV4_RE.test(v)) {
    const parts = v.split(".").map(Number);
    if (parts.every((p) => p >= 0 && p <= 255)) return null;
  }
  if (IPV6_RE.test(v)) return null;
  if (HOSTNAME_RE.test(v)) return null;
  if (v.startsWith("http://") || v.startsWith("https://")) return null;

  return "Must be a valid IPv4/IPv6 address, hostname, or URL";
}

export function validateUuid(
  value: string,
  fieldName = "ID",
): ValidationResult {
  if (!value) return `${fieldName} is required`;
  const uuidRe =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuidRe.test(value)) return `Invalid ${fieldName} format`;
  return null;
}

export function validateOid(value: string): ValidationResult {
  const err = required(value, "OID");
  if (err) return err;
  if (!OID_RE.test(value.trim()))
    return "Must be a dotted numeric OID (e.g. 1.3.6.1.2.1.1.1.0)";
  return null;
}

export function validateSemver(value: string): ValidationResult {
  const err = required(value, "Version");
  if (err) return err;
  if (!SEMVER_RE.test(value.trim()))
    return "Must be semver format (e.g. 1.0.0)";
  return null;
}

export function validateSlug(
  value: string,
  fieldName = "Slug",
): ValidationResult {
  const err = required(value, fieldName);
  if (err) return err;
  if (!SLUG_RE.test(value)) {
    return `${fieldName} must be 2-128 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphen`;
  }
  return null;
}

export function validateHexColor(value: string): ValidationResult {
  if (!value) return null;
  if (!HEX_COLOR_RE.test(value)) return "Must be hex color format (#RRGGBB)";
  return null;
}

export function validateLabelKey(value: string): ValidationResult {
  if (!value) return "Label key is required";
  if (!LABEL_KEY_RE.test(value)) {
    return "Must be 2-64 chars, lowercase, start with letter, only a-z, 0-9, hyphens, underscores";
  }
  return null;
}

export function validateEmail(value: string): ValidationResult {
  if (!value) return null;
  const v = value.trim();
  if (!v.includes("@") || !v.split("@").pop()?.includes(".")) {
    return "Invalid email format";
  }
  return null;
}

export function validateUsername(value: string): ValidationResult {
  const err = required(value, "Username");
  if (err) return err;
  if (value.length < 2) return "Username must be at least 2 characters";
  if (value.length > 150) return "Username must be at most 150 characters";
  if (!USERNAME_RE.test(value))
    return "Username can only contain letters, numbers, dots, underscores, @ and hyphens";
  return null;
}

export function validatePassword(value: string): ValidationResult {
  const err = required(value, "Password");
  if (err) return err;
  if (value.length < 6) return "Password must be at least 6 characters";
  if (value.length > 128) return "Password must be at most 128 characters";
  return null;
}

export function validateAlertWindow(value: string): ValidationResult {
  const err = required(value, "Window");
  if (err) return err;
  if (!ALERT_WINDOW_RE.test(value.trim())) return "Must be like 5m, 1h, or 30s";
  return null;
}

export function validateTimezone(value: string): ValidationResult {
  const err = required(value, "Timezone");
  if (err) return err;
  if (!TIMEZONE_RE.test(value)) return "Invalid timezone format";
  return null;
}

export function validateScheduleSeconds(value: number): ValidationResult {
  return numberRange(value, 10, 86400, "Schedule interval");
}

export function validateTimeout(value: number): ValidationResult {
  return numberRange(value, 1, 300, "Timeout");
}

// ── Composite: run multiple validators ─────────────────────

export function validate(
  value: string,
  ...validators: ((v: string) => ValidationResult)[]
): ValidationResult {
  for (const fn of validators) {
    const err = fn(value);
    if (err) return err;
  }
  return null;
}
