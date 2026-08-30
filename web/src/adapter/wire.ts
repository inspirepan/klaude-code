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

/** One tool as `GET /api/web/sessions/{id}/system-context` reports it. */
export interface SystemContextTool {
  readonly name: string
  readonly description: string
  /** JSON Schema object for the arguments. */
  readonly parameters: Record<string, unknown>
}

/**
 * The allowlisted model knobs the system-context endpoint reports.
 *
 * `server/system_context.py` never dumps a config: every field here is named
 * explicitly there, so no credential can arrive by being added upstream. A
 * cold (rebuilt) session only knows `model` / `model_config_name` / `effort`;
 * the rest are `null`.
 */
export interface SystemContextModel {
  readonly provider?: string | null
  readonly protocol?: string | null
  readonly model?: string | null
  readonly model_config_name?: string | null
  readonly effort?: string | null
  readonly max_tokens?: number | null
  readonly context_limit?: number | null
  readonly temperature?: number | null
  readonly verbosity?: string | null
  readonly thinking?: Record<string, unknown> | null
  readonly fast_mode?: boolean | null
  readonly cache_retention?: string | null
  readonly supports_vision?: boolean | null
}

/**
 * `GET /api/web/sessions/{id}/system-context` response.
 *
 * `source: 'live'` is the loaded agent's own profile — the exact system prompt
 * and tools its next step would send. `source: 'rebuilt'` re-ran the builders
 * off the session meta, so it reflects **today's** prompt files and tool set
 * rather than what the session actually sent; the SYSTEM row says so.
 * `available: false` carries a `reason` and no payload (HTTP is still 200).
 */
export interface SystemContext {
  readonly available: boolean
  readonly source?: 'live' | 'rebuilt' | null
  readonly system_prompt?: string | null
  readonly tools?: readonly SystemContextTool[] | null
  readonly model?: SystemContextModel | null
  readonly reason?: string | null
}

/**
 * One hit from `GET /api/web/sessions/{id}/search`.
 *
 * `kind` is the **disk entity class name** (`UserMessage`, `ToolResultMessage`,
 * `LLMRequestEntry`, …), not the trajectory row kind; `status` is the same
 * ledger status a history row carries, so a discarded line still matches and
 * can be shown greyed out. `snippet` is a preview only (≤160 chars, ellipses
 * included) — the row itself renders from the `entry` the history page brings.
 */
export interface SessionSearchMatch {
  /** Zero-based `events.jsonl` line; the jump coordinate. */
  readonly line_index: number
  readonly turn_index: number
  readonly kind: string
  readonly status: HistoryRowStatus
  readonly snippet: string
}

/**
 * `GET /api/web/sessions/{id}/search?q=&limit=` response.
 *
 * `matches` are ascending by `line_index` and hold the **first** `limit` hits,
 * so the earliest match is always `matches[0]` even when `truncated`; `total`
 * counts them all. The server's searchable text is a subset of the client
 * index, so every hit here also matches the live filter once its row is loaded.
 */
export interface SessionSearchResult {
  readonly session_id: string
  readonly query: string
  /** The terms the server actually split `q` into (lowercased). */
  readonly terms: readonly string[]
  readonly matches: readonly SessionSearchMatch[]
  readonly total: number
  readonly truncated: boolean
}
