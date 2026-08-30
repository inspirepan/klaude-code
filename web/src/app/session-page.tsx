/**
 * Trajectory page: `#/s/{session_id}`.
 *
 * Opens on the tail history page (the server's default) and prepends older
 * pages on demand. Row identity is line-based, so a prepend never renumbers a
 * row that is already on screen; the snapshot is simply rebuilt from the longer
 * row list.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { HistoryRow, SessionMeta } from '../adapter/index.ts'
import { buildTrajectorySnapshot } from '../adapter/index.ts'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import type { TrajectoryOpenState, TrajectorySessionState } from '../trajectory/TrajectoryView.tsx'
import { t } from '../locale.ts'
import { fetchHistoryPage, fetchSessionMeta } from './api.ts'
import { useActualDuration } from './duration.ts'
import { renderImages } from './render-images.tsx'
import css from './session-page.module.css'

interface PageState {
  readonly rows: readonly HistoryRow[]
  readonly hasMore: boolean
  readonly nextBeforeLine: number | null
}

const EMPTY_PAGE: PageState = { rows: [], hasMore: false, nextBeforeLine: null }

function baseName(path: string | null): string | null {
  if (path === null || path === '') return null
  const parts = path.split('/').filter(part => part !== '')
  return parts[parts.length - 1] ?? path
}

/** Trajectory page for one session. */
export function SessionPage({ sessionId }: { sessionId: string }) {
  const [meta, setMeta] = useState<SessionMeta | null>(null)
  const [page, setPage] = useState<PageState>(EMPTY_PAGE)
  const [openState, setOpenState] = useState<TrajectoryOpenState>('loading')
  const [failure, setFailure] = useState<string | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [actualDuration, setActualDuration] = useActualDuration()
  const olderPending = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    setMeta(null)
    setPage(EMPTY_PAGE)
    setFailure(null)
    setOpenState('loading')
    olderPending.current = false
    void (async () => {
      try {
        const [sessionMeta, history] = await Promise.all([
          fetchSessionMeta(sessionId, controller.signal),
          fetchHistoryPage(sessionId, {}, controller.signal),
        ])
        if (controller.signal.aborted) return
        setMeta(sessionMeta)
        setPage({
          rows: history.rows,
          hasMore: history.has_more,
          nextBeforeLine: history.next_before_line,
        })
        setOpenState('open')
      } catch (error) {
        if (controller.signal.aborted) return
        setFailure(error instanceof Error ? error.message : String(error))
        setOpenState('error')
      }
    })()
    return () => { controller.abort() }
  }, [sessionId])

  const loadOlder = useCallback(async (): Promise<boolean> => {
    if (olderPending.current) return page.hasMore
    const before = page.nextBeforeLine
    if (before === null || !page.hasMore) return false
    olderPending.current = true
    setLoadingOlder(true)
    try {
      const older = await fetchHistoryPage(sessionId, { beforeLine: before })
      setPage(current => ({
        rows: [...older.rows, ...current.rows],
        hasMore: older.has_more,
        nextBeforeLine: older.next_before_line,
      }))
      return older.has_more
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
      return false
    } finally {
      olderPending.current = false
      setLoadingOlder(false)
    }
  }, [page.hasMore, page.nextBeforeLine, sessionId])

  const snapshot = useMemo(
    () => buildTrajectorySnapshot(page.rows, { sessionId }),
    [page.rows, sessionId],
  )
  const session: TrajectorySessionState = {
    openState,
    loadingOlder,
    hasMore: page.hasMore,
  }
  const directory = baseName(meta?.work_dir ?? null)

  return (
    <div className={css.page}>
      <header className={css.header}>
        <a className={css.home} href="#/" title="Sessions">klaude</a>
        <h1 className={css.title}>{meta?.title ?? sessionId}</h1>
        {directory !== null && <span className={css.badge}>{directory}</span>}
        {meta?.model != null && meta.model !== '' && (
          <span className={css.meta}>{meta.model}</span>
        )}
        {meta?.state != null && meta.state !== '' && (
          <span className={css.state} data-state={meta.state}>{meta.state}</span>
        )}
        {meta?.parent_session_id != null && meta.parent_session_id !== '' && (
          <a className={css.parent} href={`#/s/${meta.parent_session_id}`}>parent session</a>
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
