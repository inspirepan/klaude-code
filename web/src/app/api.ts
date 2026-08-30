/** Same-origin REST client for the klaude web endpoints. */

import type { HistoryPage, SessionListRow, SessionMeta } from '../adapter/index.ts'

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

/**
 * Fetch the session list (the list page itself lands in part 2).
 * @param limit - Maximum rows.
 * @param signal - Abort signal.
 * @returns The listed sessions, children included.
 */
export async function fetchSessions(
  limit = 50,
  signal?: AbortSignal,
): Promise<readonly SessionListRow[]> {
  const page = await getJson<{ sessions?: readonly SessionListRow[] }>(
    `/api/headless/sessions?include_children=1&limit=${limit}`,
    signal,
  )
  return page.sessions ?? []
}
