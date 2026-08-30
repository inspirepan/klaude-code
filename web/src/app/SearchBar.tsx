/**
 * The one line the server search adds to the trajectory page.
 *
 * The vendored toolbar filters the rows already loaded; this bar reports the
 * matches sitting *above* that window and loads down to the oldest one. It is
 * rendered only when it has something to say — a non-empty query, older
 * history on disk, and at least one hit the loaded rows cannot show — so an
 * ordinary filter over a fully loaded session never sees it.
 *
 * Every failure (422 on an empty query, an offline server, an aborted request)
 * degrades to "no bar": the local filter is the product, this is the extra.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { SessionSearchResult } from '../adapter/index.ts'
import type { TrajectoryTranslate } from '../locale.ts'
import { HISTORY_PAGE_LIMIT, searchSession } from './api.ts'
import {
  MAX_JUMP_PAGES, createSearchRunner, pagesToReachLine, partitionSearchMatches,
  type SearchJumpOutcome, type SearchRunner,
} from './search.ts'
import css from './SearchBar.module.css'

/** What the page supplies to the server-search bar. */
export interface SearchBarProps {
  readonly sessionId: string
  /** The vendored toolbar's live-filter query, mirrored out of the view. */
  readonly query: string
  /** Oldest loaded row's `line_index`; null while the window is empty. */
  readonly firstLoadedLine: number | null
  /** True when older rows still exist above the window. */
  readonly hasMore: boolean
  /** Walk older pages until `line` is loaded, then focus it. */
  readonly onLoadUntilLine: (line: number) => Promise<SearchJumpOutcome>
  readonly t: TrajectoryTranslate
}

/**
 * Render the server-search bar, or nothing.
 * @param props - Session, query, window bounds and the loader.
 * @returns The bar element, or null when it has nothing to report.
 */
export function SearchBar({
  sessionId, query, firstLoadedLine, hasMore, onLoadUntilLine, t,
}: SearchBarProps) {
  const [result, setResult] = useState<SessionSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [capped, setCapped] = useState(false)
  const runnerRef = useRef<SearchRunner | null>(null)

  // One runner per session: it owns the debounce timer, the abort controller
  // and the stale-answer guard.
  useEffect(() => {
    setResult(null)
    const runner = createSearchRunner<SessionSearchResult>({
      run: (text, signal) => searchSession(sessionId, text, { signal }),
      onResult: (_text, value) => { setResult(value) },
    })
    runnerRef.current = runner
    return () => {
      runner.dispose()
      runnerRef.current = null
    }
  }, [sessionId])

  // Nothing older on disk means nothing to look for: an empty request cancels
  // the runner instead of asking the server a question with no consumer.
  const trimmed = query.trim()
  const wanted = hasMore ? trimmed : ''
  useEffect(() => {
    runnerRef.current?.request(wanted)
  }, [sessionId, wanted])

  const partition = useMemo(
    () => partitionSearchMatches(result?.matches ?? [], firstLoadedLine),
    [firstLoadedLine, result],
  )
  const target = partition.earliestUnloadedLine
  // Best case, and worth saying out loud: a match a dozen pages back is a
  // several-second wait, not an instant jump.
  const pages = target === null
    ? 0
    : pagesToReachLine(firstLoadedLine, target, HISTORY_PAGE_LIMIT)

  const jump = useCallback(async () => {
    if (target === null) return
    setCapped(false)
    setLoading(true)
    try {
      const outcome = await onLoadUntilLine(target)
      setCapped(!outcome.reached)
    } finally {
      setLoading(false)
    }
  }, [onLoadUntilLine, target])

  // The bar answers for the query on screen only. A result for the previous
  // query is held (not cleared) while the next request is in flight, but it is
  // not shown — the counts would be about text the user already replaced.
  if (trimmed === '' || !hasMore || result === null || result.query !== trimmed) return null
  if (partition.unloaded.length === 0) return null

  return (
    <div className={css.bar} aria-label={t('klaude.search.aria')}>
      <span className={css.text} role="status" aria-live="polite">
        {loading
          ? t('klaude.search.loading', { line: firstLoadedLine ?? 0 })
          : t('klaude.search.unloaded', {
            count: partition.unloaded.length,
            total: result.total,
          })}
      </span>
      {pages > 1 && !loading && (
        <span className={css.note}>{t('klaude.search.pages', { pages })}</span>
      )}
      {result.truncated && !loading && (
        <span className={css.note}>
          {t('klaude.search.truncated', { limit: result.matches.length })}
        </span>
      )}
      {capped && !loading && (
        <span className={css.note}>{t('klaude.search.capped', { pages: MAX_JUMP_PAGES })}</span>
      )}
      <span className={css.spacer} />
      <button
        type="button"
        className={css.action}
        disabled={loading}
        onClick={() => { void jump() }}
      >
        {capped ? t('klaude.search.more') : t('klaude.search.jump')}
      </button>
    </div>
  )
}
