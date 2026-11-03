/**
 * Trajectory page: `#/s/{session_id}`.
 *
 * Opens on the tail history page (the server's default) and prepends older
 * pages on demand. Row identity is line-based, so a prepend never renumbers a
 * row that is already on screen; the snapshot is simply rebuilt from the longer
 * row list.
 *
 * Polls persisted metadata and history; never connects to an execution process.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { SessionMeta, SystemContext, TrajectoryLineFocus } from '../adapter/index.ts'
import { buildTrajectorySnapshot } from '../adapter/index.ts'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import type { TrajectoryOpenState, TrajectorySessionState } from '../trajectory/TrajectoryView.tsx'
import { t } from '../locale.ts'
import { fetchHistoryPage, fetchSessionMeta, fetchSystemContext } from './api.ts'
import { useActualDuration } from './duration.ts'
import type { LoadedWindow } from './history.ts'
import { mergeHistoryTail } from './history.ts'
import { renderImages } from './render-images.tsx'
import { SearchBar } from './SearchBar.tsx'
import { walkToLine, type SearchJumpOutcome } from './search.ts'
import { statusLabel } from './session-list-model.ts'
import css from './session-page.module.css'

const EMPTY_PAGE: LoadedWindow = { rows: [], hasMore: false, nextBeforeLine: null }

/** Refresh persisted metadata and history without subscribing to execution. */
const HISTORY_POLL_MS = 2_000

function baseName(path: string | null): string | null {
  if (path === null || path === '') return null
  const parts = path.split('/').filter(part => part !== '')
  return parts[parts.length - 1] ?? path
}

/** Trajectory page for one session. */
export function SessionPage({ sessionId }: { sessionId: string }) {
  const [meta, setMeta] = useState<SessionMeta | null>(null)
  const [page, setPage] = useState<LoadedWindow>(EMPTY_PAGE)
  const [openState, setOpenState] = useState<TrajectoryOpenState>('loading')
  const [failure, setFailure] = useState<string | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [actualDuration, setActualDuration] = useActualDuration()
  // The system prompt and tool catalogue are not in `events.jsonl`; they are
  // fetched once (and cached in `api.ts`) and become the SYSTEM row plus the
  // tool inspector's Schema tab.
  const [systemContext, setSystemContext] = useState<SystemContext | undefined>(undefined)
  // The live filter's query, mirrored out of the vendored toolbar: the server
  // search bar needs it, and nothing else in the page does.
  const [searchQuery, setSearchQuery] = useState('')
  // One-shot "scroll to this line" command handed to the view after a jump.
  const [focusLine, setFocusLine] = useState<TrajectoryLineFocus | null>(null)

  // The window every async job reads: `page` in a ref, so a job that started
  // before a prepend still sees the current rows when it runs.
  const pageRef = useRef<LoadedWindow>(EMPTY_PAGE)
  // History requests are serialized: a tail merge and a prepend both rewrite
  // the same window, and interleaving them would lose one of the two.
  const queueRef = useRef<Promise<unknown>>(Promise.resolve())
  // False until the opening page landed: a `history.appended` that beats the
  // initial load must not race it into the same window.
  const readyRef = useRef(false)

  const enqueue = useCallback(<T,>(job: () => Promise<T>): Promise<T> => {
    const next = queueRef.current.then(job, job)
    queueRef.current = next.then(() => undefined, () => undefined)
    return next
  }, [])

  const commit = useCallback((window: LoadedWindow) => {
    pageRef.current = window
    setPage(window)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setMeta(null)
    commit(EMPTY_PAGE)
    setFailure(null)
    setOpenState('loading')
    // A jump belongs to the session it was issued in.
    setFocusLine(null)
    readyRef.current = false
    void (async () => {
      try {
        const [sessionMeta, history] = await Promise.all([
          fetchSessionMeta(sessionId, controller.signal),
          fetchHistoryPage(sessionId, {}, controller.signal),
        ])
        if (controller.signal.aborted) return
        setMeta(sessionMeta)
        commit({
          rows: history.rows,
          hasMore: history.has_more,
          nextBeforeLine: history.next_before_line,
        })
        readyRef.current = true
        setOpenState('open')
      } catch (error) {
        if (controller.signal.aborted) return
        setFailure(error instanceof Error ? error.message : String(error))
        setOpenState('error')
      }
    })()
    return () => { controller.abort() }
  }, [commit, sessionId])

  useEffect(() => {
    let live = true
    setSystemContext(undefined)
    void fetchSystemContext(sessionId).then((context) => {
      if (live) setSystemContext(context)
    })
    return () => { live = false }
  }, [sessionId])

  const loadOlder = useCallback(async (): Promise<boolean> => enqueue(async () => {
    const window = pageRef.current
    const before = window.nextBeforeLine
    if (before === null || !window.hasMore) return false
    setLoadingOlder(true)
    try {
      const older = await fetchHistoryPage(sessionId, { beforeLine: before })
      commit({
        rows: [...older.rows, ...pageRef.current.rows],
        hasMore: older.has_more,
        nextBeforeLine: older.next_before_line,
      })
      return older.has_more
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
      return false
    } finally {
      setLoadingOlder(false)
    }
  }), [commit, enqueue, sessionId])

  /**
   * Walk older pages until `line` is inside the window, then focus its row.
   *
   * Every page goes through `loadOlder` — same request, same promise queue,
   * same prepend — so row identity and `line_index` keys are untouched and a
   * concurrent tail merge cannot interleave. The walk is capped: a match
   * thousands of pages back becomes a "continue" button rather than a loop
   * that holds the page hostage.
   * @param line - The ledger line to bring into the window.
   * @returns Whether the line landed, and how many pages it took.
   */
  const loadUntilLine = useCallback((line: number): Promise<SearchJumpOutcome> => {
    // The command is issued *before* the walk on purpose. It resolves to
    // nothing until the target's page lands, and then resolves inside the same
    // commit that rebuilt the table's rows — the only commit the vendored
    // scroll effect re-runs on. Setting it afterwards would arrive one commit
    // too late and never scroll.
    setFocusLine({ line })
    return walkToLine({ targetLine: line, window: () => pageRef.current, loadOlder })
  }, [loadOlder])

  /**
   * Fold the tail increment a `history.appended` announced, then retire the
   * in-flight rows it replaced. A marker in the increment also refreshes the
   * statuses of the rows already on screen (`history.ts`).
   */
  const pullTail = useCallback(() => {
    return enqueue(async () => {
      if (!readyRef.current) return
      try {
        const result = await mergeHistoryTail(
          pageRef.current,
          query => fetchHistoryPage(sessionId, query),
        )
        if (result.landed.length === 0 && !result.refreshed) return
        commit(result.window)
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error))
      }
    })
  }, [commit, enqueue, sessionId])

  useEffect(() => {
    let active = true
    let pending = false
    const poll = async () => {
      if (pending || document.hidden || !readyRef.current) return
      pending = true
      try {
        const [fresh] = await Promise.all([fetchSessionMeta(sessionId), pullTail()])
        if (active) setMeta(fresh)
      } catch {
        // Retry on the next poll.
      } finally {
        pending = false
      }
    }
    const timer = setInterval(() => { void poll() }, HISTORY_POLL_MS)
    return () => { active = false; clearInterval(timer) }
  }, [pullTail, sessionId])

  const landed = useMemo(
    () => buildTrajectorySnapshot(page.rows, { sessionId, systemContext, translate: t }),
    [page.rows, sessionId, systemContext],
  )
  const snapshot = landed
  const session: TrajectorySessionState = {
    openState,
    loadingOlder,
    hasMore: page.hasMore,
  }
  const directory = baseName(meta?.work_dir ?? null)
  const status = meta?.status ?? null
  const parent = meta?.parent_session_id ?? null

  return (
    <div className={css.page}>
      <header className={css.header}>
        <a className={css.back} href="#/" title={t('klaude.sessionPage.back')} aria-label={t('klaude.sessionPage.back')}>‹ {t('klaude.sessionPage.backShort')}</a>
        <h1 className={css.title}>{meta?.title ?? sessionId}</h1>
        {directory !== null && <span className={css.badge}>{directory}</span>}
        {meta?.model != null && meta.model !== '' && (
          <span className={css.meta}>{meta.model}</span>
        )}
        {status !== null && (
          <span className={css.state} data-state={status.category}>{statusLabel(status)}</span>
        )}
        {parent !== null && parent !== '' && (
          <a className={css.parent} href={`#/s/${parent}`}>↑ parent</a>
        )}
        <span className={css.spacer} />
        <span className={css.meta}>{page.rows.length} / {meta?.line_count ?? '?'} lines</span>
      </header>
      {failure !== null && <p className={css.failure}>{failure}</p>}
      <SearchBar
        sessionId={sessionId}
        query={searchQuery}
        firstLoadedLine={page.rows[0]?.line_index ?? null}
        hasMore={page.hasMore}
        onLoadUntilLine={loadUntilLine}
        t={t}
      />
      <div className={css.body}>
        <TrajectoryView
          snapshot={snapshot}
          session={session}
          actualDuration={actualDuration}
          setActualDuration={setActualDuration}
          loadOlder={loadOlder}
          renderImages={renderImages}
          t={t}
          onSearchQueryChange={setSearchQuery}
          focusRecordLine={focusLine}
        />
      </div>
    </div>
  )
}
