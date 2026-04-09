/**
 * Parse structured validation errors from API responses
 * and map them to field-level error messages.
 */

export interface FieldErrors {
  [fieldName: string]: string[];
}

export function parseApiFieldErrors(error: unknown): FieldErrors | null {
  if (error instanceof Error && "response" in error) {
    const resp = (error as Record<string, unknown>).response;
    if (resp && typeof resp === "object" && "error" in resp) {
      const errObj = (resp as Record<string, unknown>).error;
      if (errObj && typeof errObj === "object" && "details" in errObj) {
        const details = (errObj as Record<string, unknown>).details;
        if (details && typeof details === "object" && "fields" in details) {
          return (details as { fields: FieldErrors }).fields;
        }
      }
    }
  }
  // Try parsing from the detail string (HTTPException)
  if (error instanceof Error) {
    try {
      const parsed = JSON.parse(error.message);
      if (parsed?.details?.fields) return parsed.details.fields;
    } catch {
      // Not structured
    }
  }
  return null;
}

export function getFieldError(
  errors: FieldErrors | null,
  field: string,
): string | undefined {
  if (!errors) return undefined;
  const msgs = errors[field];
  return msgs?.[0];
}
