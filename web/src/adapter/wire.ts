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
  /**
   * Absolute 1-based human-turn ordinal from `session/ledger.py`, counted over
   * the whole file (0 ahead of the first human message). Absent on servers
   * older than the ledger scan; the adapter then counts within the window.
   */
  readonly turn_index?: number | null
  /** 1-based assistant step inside the turn; `null` off `AssistantMessage` lines. */
  readonly step_index?: number | null
  /** Set on `UserMessage` lines only: true when the runtime wrote the message. */
  readonly auto?: boolean | null
  /** Null when the line failed to decode (the row still holds its number). */
  readonly entry: RawEntry | null
}

/** `GET /api/web/sessions/{id}/history` response. */
export interface HistoryPage {
  readonly session_id: string
  readonly line_count: number
  /** Human turns in the whole file; absent before the ledger scan landed. */
  readonly turn_count?: number
  readonly rows: readonly HistoryRow[]
  readonly has_more: boolean
  readonly next_before_line: number | null
}

/**
 * `GET /api/web/sessions/{id}/meta` response.
 *
 * `created_at` / `updated_at` are epoch **seconds** (Python floats), not ISO
 * strings — `web_api.py: _optional_float` reads them straight off the meta file.
 */
export interface SessionMeta {
  readonly session_id: string
  readonly title: string | null
  readonly work_dir: string | null
  readonly model: string | null
  readonly parent_session_id: string | null
  readonly created_at: number | null
  readonly updated_at: number | null
  readonly state: string | null
  /** True when an agent is in memory, i.e. when the WS channel is worth opening. */
  readonly loaded: boolean
  readonly line_count: number
}

/** The six states `server/routes/headless.py` reports for a session. */
export type SessionState =
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'idle'
  | 'completed'
  | 'failed'

/**
 * One row of `GET /api/headless/sessions` (`routes/headless.py: _serialize_row`).
 *
 * The identity field is `id`, not `session_id`; timestamps are epoch seconds.
 */
export interface SessionListRow {
  readonly id: string
  readonly name?: string | null
  readonly group?: string | null
  readonly agent_type?: string | null
  readonly spawn_kind?: string | null
  readonly parent_session_id?: string | null
  readonly state?: string | null
  readonly model?: string | null
  readonly work_dir?: string | null
  readonly title?: string | null
  readonly created_at?: number | null
  readonly updated_at?: number | null
  readonly archived?: boolean
  /** Free-text activity line the headless API renders in `ps`. */
  readonly activity?: string | null
  readonly pending?: boolean
}
