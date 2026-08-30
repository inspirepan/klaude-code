/**
 * Trajectory page: `#/s/{session_id}`.
 *
 * Opens on the tail history page (the server's default) and prepends older
 * pages on demand. Row identity is line-based, so a prepend never renumbers a
 * row that is already on screen; the snapshot is simply rebuilt from the longer
 * row list.
 *
 * An **online** session also opens the WS channel (`app/live`). REST keeps
 * owning every landed row; the socket contributes only `partial` and
 * `runningCalls`, and tells the page when to pull the tail increment. A cold
 * session never connects — that would spin up an agent (decision #28).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { SessionMeta, SystemContext } from '../adapter/index.ts'
import { buildTrajectorySnapshot } from '../adapter/index.ts'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import type { TrajectoryOpenState, TrajectorySessionState } from '../trajectory/TrajectoryView.tsx'
import { t } from '../locale.ts'
import { fetchHistoryPage, fetchSessionMeta, fetchSystemContext } from './api.ts'
import { useActualDuration } from './duration.ts'
import type { LoadedWindow } from './live/index.ts'
import { mergeHistoryTail, spliceLiveSnapshot, useLiveSession } from './live/index.ts'
import { renderImages } from './render-images.tsx'
import css from './session-page.module.css'

const EMPTY_PAGE: LoadedWindow = { rows: [], hasMore: false, nextBeforeLine: null }

/** How often an offline page re-reads meta, watching for the session to wake. */
const OFFLINE_META_POLL_MS = 10_000

function baseName(path: string | null): string | null {
  if (path === null || path === '') return null
  const parts = path.split('/').filter(part => part !== '')
  return parts[parts.length - 1] ?? path
}

/**
 * Whether this session is worth a socket.
 *
 * `loaded` is the honest signal (an agent is in memory); the two live states
 * cover the window where the list already knows work is happening but the meta
 * read raced the actor's creation.
 */
function isOnline(meta: SessionMeta | null): boolean {
  if (meta === null) return false
  return meta.loaded || meta.state === 'running' || meta.state === 'waiting_input'
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

  const online = isOnline(meta)
  const { state: live, acknowledge } = useLiveSession(sessionId, online)

  // A cold session can wake up (someone types into it from the CLI). Nothing
  // pushes that fact to a viewer with no socket, so meta is re-read on a slow
  // timer until it reports an agent — then the socket takes over.
  useEffect(() => {
    if (meta === null || online) return
    const timer = setInterval(() => {
      if (document.hidden) return
      void (async () => {
        try {
          const fresh = await fetchSessionMeta(sessionId)
          setMeta(current => (current === null ? current : fresh))
        } catch {
          // Transient; the next tick tries again.
        }
      })()
    }, OFFLINE_META_POLL_MS)
    return () => { clearInterval(timer) }
  }, [meta, online, sessionId])

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
   * Fold the tail increment a `history.appended` announced, then retire the
   * in-flight rows it replaced. A marker in the increment also refreshes the
   * statuses of the rows already on screen (`live/merge.ts`).
   */
  const pullTail = useCallback(() => {
    void enqueue(async () => {
      if (!readyRef.current) return
      try {
        const result = await mergeHistoryTail(
          pageRef.current,
          query => fetchHistoryPage(sessionId, query),
        )
        if (result.landed.length === 0 && !result.refreshed) return
        commit(result.window)
        acknowledge(result.landed)
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error))
      }
    })
  }, [acknowledge, commit, enqueue, sessionId])

  // A flush landed on disk.
  useEffect(() => {
    if (live.appendedSeq === 0) return
    pullTail()
  }, [live.appendedSeq, pullTail])

  // A (re)connect: the socket was down for a while, so meta and the tail may
  // both have moved on.
  useEffect(() => {
    if (live.connectionEpoch === 0) return
    const controller = new AbortController()
    void (async () => {
      try {
        const fresh = await fetchSessionMeta(sessionId, controller.signal)
        if (!controller.signal.aborted) setMeta(fresh)
      } catch {
        // The socket is the live signal; a failed meta refresh is not fatal.
      }
    })()
    pullTail()
    return () => { controller.abort() }
  }, [live.connectionEpoch, pullTail, sessionId])

  const landed = useMemo(
    () => buildTrajectorySnapshot(page.rows, { sessionId, systemContext, translate: t }),
    [page.rows, sessionId, systemContext],
  )
  const snapshot = useMemo(() => spliceLiveSnapshot(landed, live), [landed, live])
  const session: TrajectorySessionState = {
    openState,
    loadingOlder,
    hasMore: page.hasMore,
  }
  const directory = baseName(meta?.work_dir ?? null)
  const state = (live.connected ? live.sessionState : null) ?? meta?.state ?? null
  const parent = meta?.parent_session_id ?? null

  return (
    <div className={css.page}>
      <header className={css.header}>
        <a className={css.home} href="#/" title="Sessions">klaude</a>
        <h1 className={css.title}>{meta?.title ?? sessionId}</h1>
        {directory !== null && <span className={css.badge}>{directory}</span>}
        {meta?.model != null && meta.model !== '' && (
          <span className={css.meta}>{meta.model}</span>
        )}
        {state !== null && state !== '' && (
          <span className={css.state} data-state={state}>{state}</span>
        )}
        {live.connected && (
          <span
            className={css.liveDot}
            data-replayed={live.replayed ? 'true' : undefined}
            title={live.replayed ? 'Live' : 'Connecting…'}
            role="status"
            aria-label={live.replayed ? 'Live' : 'Connecting'}
          />
        )}
        {parent !== null && parent !== '' && (
          <a className={css.parent} href={`#/s/${parent}`}>↑ parent</a>
        )}
        <span className={css.spacer} />
        <span className={css.meta}>{page.rows.length} / {meta?.line_count ?? '?'} lines</span>
      </header>
      {failure !== null && <p className={css.failure}>{failure}</p>}
      <div className={css.body}>
        <TrajectoryView
          snapshot={snapshot}
          session={session}
          actualDuration={actualDuration}
          setActualDuration={setActualDuration}
          loadOlder={loadOlder}
          renderImages={renderImages}
          t={t}
        />
      </div>
    </div>
  )
}
