/** Row builders shared by the adapter tests. */

import type { HistoryRow, HistoryRowStatus } from './wire.ts'

/**
 * One ledger row.
 * @param lineIndex - Zero-based line.
 * @param type - Persisted class name.
 * @param data - Entry payload.
 * @param status - Ledger status from the server scan.
 * @param droppedBy - Line of the marker that invalidated the row.
 * @returns The row.
 */
export function row(
  lineIndex: number,
  type: string,
  data: Record<string, unknown>,
  status: HistoryRowStatus = 'active',
  droppedBy: number | null = null,
): HistoryRow {
  return { line_index: lineIndex, status, dropped_by: droppedBy, entry: { type, data } }
}

/** Local-time ISO stamp with Python's microsecond precision. */
export function stamp(offsetMs: number): string {
  const base = new Date(2026, 7, 30, 9, 15, 0, 0).getTime()
  const date = new Date(base + offsetMs)
  const two = (value: number) => String(value).padStart(2, '0')
  const three = (value: number) => String(value).padStart(3, '0')
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`
    + `T${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`
    + `.${three(date.getMilliseconds())}456`
}

/** Epoch ms for the same offset `stamp` encodes. */
export function stampMs(offsetMs: number): number {
  return new Date(2026, 7, 30, 9, 15, 0, 0).getTime() + offsetMs
}

/** A minimal persisted `Usage` payload. */
export function usage(fields: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    input_tokens: 1000,
    cached_tokens: 0,
    cache_write_tokens: 0,
    reasoning_tokens: 0,
    output_tokens: 100,
    model_name: 'claude-fable-5',
    provider: 'anthropic',
    created_at: stamp(0),
    ...fields,
  }
}
