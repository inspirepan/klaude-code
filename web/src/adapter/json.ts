/** Defensive readers for the opaque `entry.data` payloads. */

/** The string at `value`, or undefined when it is anything else. */
export function readString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

/** The finite number at `value`, or undefined. */
export function readNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/** The boolean at `value`, or undefined. */
export function readBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

/** The array at `value`, or an empty array. */
export function readArray(value: unknown): readonly unknown[] {
  return Array.isArray(value) ? (value as readonly unknown[]) : []
}

/** The plain object at `value`, or undefined (arrays and null excluded). */
export function readRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

/**
 * Epoch milliseconds for one persisted klaude timestamp.
 *
 * `session/codec.py` dumps `datetime` in ISO 8601 without a zone, so the value
 * is local wall-clock time; JS parses a zone-less date-time as local, which is
 * what we want. Python writes microseconds, which `Date.parse` is not required
 * to accept, so the fraction is truncated to milliseconds first.
 * @param value - ISO timestamp string from an entry payload.
 * @returns Epoch ms, or null when the value is absent or unparsable.
 */
export function readTime(value: unknown): number | null {
  const text = readString(value)
  if (text === undefined || text === '') return null
  const normalized = text.replace(/(\.\d{3})\d+/, '$1')
  const parsed = Date.parse(normalized)
  return Number.isFinite(parsed) ? parsed : null
}
