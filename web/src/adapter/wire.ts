/**
 * Wire shapes served by the klaude web REST endpoints.
 *
 * `entry` is one raw `events.jsonl` line: `{"type": "<ClassName>", "data": {…}}`
 * (`session/codec.py`). The adapter never trusts the payload beyond `type`, so
 * `data` stays an opaque record and every field is read through `json.ts`.
 */

/** Ledger status computed by the server's single history scan. */
export type HistoryRowStatus =
  | 'active'
  | 'retracted'
  | 'compacted'
  | 'rewound'
  | 'unknown'
  | 'sidecar'

/** One decoded `events.jsonl` line, still in its persisted shape. */
export interface RawEntry {
  readonly type: string
  readonly data: Record<string, unknown>
}

/** One ledger row: a raw line plus the status the server's scan gave it. */
export interface HistoryRow {
  /** Zero-based `events.jsonl` line number; the stable ledger coordinate. */
  readonly line_index: number
  readonly status: HistoryRowStatus
  /** Line of the marker that invalidated this row, when one did. */
  readonly dropped_by: number | null
  /** Null when the line failed to decode (the row still holds its number). */
  readonly entry: RawEntry | null
}

/** `GET /api/web/sessions/{id}/history` response. */
export interface HistoryPage {
  readonly session_id: string
  readonly line_count: number
  readonly rows: readonly HistoryRow[]
  readonly has_more: boolean
  readonly next_before_line: number | null
}

/** `GET /api/web/sessions/{id}/meta` response. */
export interface SessionMeta {
  readonly session_id: string
  readonly title: string | null
  readonly work_dir: string | null
  readonly model: string | null
  readonly parent_session_id: string | null
  readonly created_at: string | null
  readonly updated_at: string | null
  readonly state: string | null
  readonly loaded: boolean
  readonly line_count: number
}

/** One row of `GET /api/headless/sessions`. */
export interface SessionListRow {
  readonly session_id: string
  readonly title?: string | null
  readonly work_dir?: string | null
  readonly model?: string | null
  readonly state?: string | null
  readonly updated_at?: string | null
  readonly parent_session_id?: string | null
}
