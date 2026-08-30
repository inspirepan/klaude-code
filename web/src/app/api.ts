/** Same-origin REST client for the klaude web endpoints. */

import type {
  HistoryPage, SessionListRow, SessionMeta, SystemContext,
} from '../adapter/index.ts'

/** Rows requested per history page (the server's own default). */
export const HISTORY_PAGE_LIMIT = 500

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    headers: { accept: 'application/json' },
    ...(signal === undefined ? {} : { signal }),
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${path}`)
  }
  return await response.json() as T
}

/**
 * Fetch one session's header facts.
 * @param sessionId - Session id.
 * @param signal - Abort signal for navigation away.
 * @returns The session meta record.
 */
export function fetchSessionMeta(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionMeta> {
  return getJson<SessionMeta>(
    `/api/web/sessions/${encodeURIComponent(sessionId)}/meta`,
    signal,
  )
}

/** One history page request. */
export interface HistoryQuery {
  /** Exclusive upper bound: returns the page immediately older than this line. */
  readonly beforeLine?: number
  /** Exclusive lower bound: returns rows appended after this line. */
  readonly afterLine?: number
  readonly limit?: number
}

/**
 * Fetch one page of ledger rows.
 * @param sessionId - Session id.
 * @param query - Paging bounds; omit both for the tail page.
 * @param signal - Abort signal for navigation away.
 * @returns The page, rows ascending by `line_index`.
 */
export function fetchHistoryPage(
  sessionId: string,
  query: HistoryQuery = {},
  signal?: AbortSignal,
): Promise<HistoryPage> {
  const params = new URLSearchParams()
  if (query.beforeLine !== undefined) params.set('before_line', String(query.beforeLine))
  if (query.afterLine !== undefined) params.set('after_line', String(query.afterLine))
  params.set('limit', String(query.limit ?? HISTORY_PAGE_LIMIT))
  return getJson<HistoryPage>(
    `/api/web/sessions/${encodeURIComponent(sessionId)}/history?${params.toString()}`,
    signal,
  )
}

/** Root sessions requested per list poll; children ride along on top. */
export const SESSION_LIST_LIMIT = 500

/**
 * Fetch the session list.
 *
 * Both flags matter: without `include_archived` most historical sessions are
 * hidden, and without `include_children` sub-agent sessions are. `limit`
 * counts root sessions only — their children are added on top.
 * @param limit - Maximum root sessions.
 * @param signal - Abort signal.
 * @returns The listed sessions, archived rows and children included.
 */
export async function fetchSessions(
  limit = SESSION_LIST_LIMIT,
  signal?: AbortSignal,
): Promise<readonly SessionListRow[]> {
  const page = await getJson<{ sessions?: readonly SessionListRow[] }>(
    `/api/headless/sessions?include_children=1&include_archived=1&limit=${limit}`,
    signal,
  )
  return page.sessions ?? []
}

/**
 * System prompt + tool catalogue behind the SYSTEM row, cached per page load.
 *
 * Tens of kilobytes that never change inside one session view, so the page
 * asks once and every later caller gets the same promise. The failure is
 * cached too — as an "unavailable" answer rather than a rejection — because a
 * missing SYSTEM row is not a reason to fail the trajectory. The server keeps
 * its own 30s cache, so a reload is cheap either way.
 */
const systemContextCache = new Map<string, Promise<SystemContext>>()

/** Drop the client-side system-context cache (tests). */
export function clearSystemContextCache(): void {
  systemContextCache.clear()
}

/**
 * Fetch one session's system context.
 * @param sessionId - Session id.
 * @returns The endpoint payload; `available: false` when it could not be built
 *   (including when the request itself failed).
 */
export function fetchSystemContext(sessionId: string): Promise<SystemContext> {
  const cached = systemContextCache.get(sessionId)
  if (cached !== undefined) return cached
  const pending = getJson<SystemContext>(
    `/api/web/sessions/${encodeURIComponent(sessionId)}/system-context`,
  ).catch((error: unknown): SystemContext => ({
    available: false,
    reason: error instanceof Error ? error.message : String(error),
  }))
  systemContextCache.set(sessionId, pending)
  return pending
}
