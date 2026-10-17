/**
 * Utility for generating and validating RFC 4122 v4 UUIDs for Idempotency-Key headers.
 */

const UUID_V4_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Generates an RFC 4122 v4 compliant UUID.
 * Uses crypto.randomUUID() when available with fallback.
 */
export function generateIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  // Fallback for environments lacking crypto.randomUUID
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Validates whether a given string is a valid UUID.
 */
export function isValidUUID(val: string): boolean {
  if (!val || typeof val !== 'string') {
    return false;
  }
  return UUID_V4_REGEX.test(val.trim());
}
