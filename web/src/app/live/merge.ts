/**
 * Folding a `history.appended` notice back into the loaded ledger window.
 *
 * The WS event carries only a `line_count`, so the tail increment is pulled
 * over REST (`?after_line=…`) and appended. Two things make this more than a
 * concatenation:
 *
 * - **Markers rewrite the past.** A `CompactionEntry` or `RetractEntry` sets
 *   `status` on lines *above* it, so when one lands the statuses of rows
 *   already on screen are stale. They are re-read and replaced in place —
 *   `line_index` and `entry` are never touched, so React keys and the folded
 *   layout survive the refresh.
 * - **Paging.** A flush can be larger than one page, so the tail loop follows
 *   `has_more` (never `next_before_line`, which is `null` in `after_line` mode).
 */

import type { HistoryPage, HistoryRow } from '../../adapter/index.ts'

/** One history page request; mirrors `app/api.ts: HistoryQuery`. */
export interface HistoryPageQuery {
  readonly beforeLine?: number
  readonly afterLine?: number
  readonly limit?: number
}

/** The one server call this module needs, injected so tests can stub it. */
export type HistoryPageFetcher = (query: HistoryPageQuery) => Promise<HistoryPage>

/** The ledger window a trajectory page holds. */
export interface LoadedWindow {
  /** Rows ascending by `line_index`, contiguous. */
  readonly rows: readonly HistoryRow[]
  /** True when older rows exist above `rows[0]`. */
  readonly hasMore: boolean
  /** `before_line` for the next older page, or null. */
  readonly nextBeforeLine: number | null
}

/** Outcome of folding a tail increment into the window. */
export interface HistoryMergeResult {
  readonly window: LoadedWindow
  /** The rows this merge appended, in order. */
  readonly landed: readonly HistoryRow[]
  /** True when a marker forced a status re-read of the loaded window. */
  readonly refreshed: boolean
}

/** Entries whose arrival changes the status of lines above them. */
const MARKER_TYPES = new Set(['CompactionEntry', 'RetractEntry', 'RewindEntry'])

/** The server's own cap (`web_api.py: MAX_HISTORY_LIMIT`). */
const MAX_LIMIT = 2000

/** Tail pages fetched per merge before giving up on catching up. */
const MAX_TAIL_PAGES = 8

/** Pages read back when a marker forces a status refresh (2000 rows each). */
const MAX_REFRESH_PAGES = 4

function lastLine(rows: readonly HistoryRow[]): number | null {
  const last = rows[rows.length - 1]
  return last === undefined ? null : last.line_index
}

/**
 * Whether a batch of rows contains a marker that restates older statuses.
 * @param rows - Rows that just landed.
 * @returns True when the loaded window's statuses must be re-read.
 */
export function hasStatusMarker(rows: readonly HistoryRow[]): boolean {
  return rows.some(row => row.entry !== null && MARKER_TYPES.has(row.entry.type))
}

/**
 * Re-read the statuses of the loaded window and replace them in place.
 *
 * Reads backwards from the window's last line in pages of at most
 * `MAX_LIMIT`, so a window larger than one page still refreshes (the plan's
 * "two pages if larger"; four are allowed here). Rows the refresh did not
 * reach keep the status they had.
 * @param rows - The loaded window, ascending.
 * @param fetchPage - History page fetcher.
 * @returns The same rows with fresh `status` / `dropped_by`.
 */
export async function refreshRowStatuses(
  rows: readonly HistoryRow[],
  fetchPage: HistoryPageFetcher,
): Promise<readonly HistoryRow[]> {
  const end = lastLine(rows)
  if (end === null) return rows
  const fresh = new Map<number, HistoryRow>()
  let before = end + 1
  let remaining = rows.length
  for (let page = 0; page < MAX_REFRESH_PAGES && remaining > 0 && before > 0; page += 1) {
    const result = await fetchPage({ beforeLine: before, limit: Math.min(remaining, MAX_LIMIT) })
    const first = result.rows[0]
    if (first === undefined) break
    for (const row of result.rows) fresh.set(row.line_index, row)
    remaining -= result.rows.length
    before = first.line_index
    if (!result.has_more) break
  }
  if (fresh.size === 0) return rows
  return rows.map((row) => {
    const updated = fresh.get(row.line_index)
    if (updated === undefined) return row
    if (updated.status === row.status && updated.dropped_by === row.dropped_by) return row
    // Identity is the line number and the raw entry; only the scan's verdict
    // is allowed to change here.
    return { ...row, status: updated.status, dropped_by: updated.dropped_by }
  })
}

/**
 * Pull the tail increment announced by `history.appended` and fold it in.
 * @param window - The window currently on screen.
 * @param fetchPage - History page fetcher.
 * @param limit - Rows per request.
 * @returns The grown window, the rows it gained, and whether statuses were re-read.
 */
export async function mergeHistoryTail(
  window: LoadedWindow,
  fetchPage: HistoryPageFetcher,
  limit = 500,
): Promise<HistoryMergeResult> {
  const anchorLine = lastLine(window.rows)
  if (anchorLine === null) {
    // Nothing loaded yet (an empty session that just got its first rows):
    // `after_line=-1` would work but the tail page is the honest request.
    const page = await fetchPage({ limit })
    return {
      window: { rows: page.rows, hasMore: page.has_more, nextBeforeLine: page.next_before_line },
      landed: page.rows,
      refreshed: false,
    }
  }

  const landed: HistoryRow[] = []
  let anchor = anchorLine
  for (let page = 0; page < MAX_TAIL_PAGES; page += 1) {
    const result = await fetchPage({ afterLine: anchor, limit })
    const last = result.rows[result.rows.length - 1]
    if (last === undefined) break
    landed.push(...result.rows)
    anchor = last.line_index
    // `after_line` mode: has_more means rows exist beyond rows[-1].
    if (!result.has_more) break
  }
  if (landed.length === 0) return { window, landed, refreshed: false }

  let rows: readonly HistoryRow[] = [...window.rows, ...landed]
  const refreshed = hasStatusMarker(landed)
  if (refreshed) rows = await refreshRowStatuses(rows, fetchPage)
  // `hasMore` / `nextBeforeLine` describe the *older* edge, which a tail
  // increment cannot move.
  return {
    window: { rows, hasMore: window.hasMore, nextBeforeLine: window.nextBeforeLine },
    landed,
    refreshed,
  }
}
