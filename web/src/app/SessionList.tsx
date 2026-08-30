/**
 * Session list page: `#/`.
 *
 * One poll of `GET /api/headless/sessions` every 5 s (decision #24), paused
 * while the tab is hidden so a backgrounded viewer costs nothing. Rows are
 * grouped by `parent_session_id`: sub-agent sessions are real sessions with
 * their own ledger (decision #10), so they nest under their parent rather than
 * being folded into its trajectory.
 *
 * Everything below the fetch is pure and lives in `session-list-model.ts`.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { SessionListRow } from '../adapter/index.ts'
import { SESSION_LIST_LIMIT, fetchSessions } from './api.ts'
import type { SessionTreeNode } from './session-list-model.ts'
import {
  buildSessionTree, filterSessionRows, flattenSessionTree, isLiveState, relativeUpdated,
  rowState, rowTitle, workDirName,
} from './session-list-model.ts'
import css from './SessionList.module.css'

/** Poll period (decision #24). */
const POLL_MS = 5000

function collectParentIds(nodes: readonly SessionTreeNode[], into: Set<string>): Set<string> {
  for (const node of nodes) {
    if (node.children.length === 0) continue
    into.add(node.row.id)
    collectParentIds(node.children, into)
  }
  return into
}

/** One list row: a disclosure toggle plus the link that opens the trajectory. */
function SessionRow({
  node, expanded, onToggle, now,
}: {
  readonly node: SessionTreeNode
  readonly expanded: boolean
  readonly onToggle: (id: string) => void
  readonly now: number
}) {
  const { row } = node
  const state = rowState(row)
  const directory = workDirName(row.work_dir)
  const hasChildren = node.children.length > 0
  return (
    <li
      className={css.row}
      data-archived={row.archived === true ? 'true' : undefined}
      data-live={isLiveState(state) ? 'true' : undefined}
      style={{ paddingLeft: `${8 + node.depth * 18}px` }}
    >
      {hasChildren
        ? (
          <button
            type="button"
            className={css.toggle}
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse sub-agent sessions' : 'Expand sub-agent sessions'}
            onClick={() => { onToggle(row.id) }}
          >
            <span className={css.chevron} data-open={expanded ? 'true' : undefined}>›</span>
          </button>
        )
        : <span className={css.toggleSpacer} />}
      <a className={css.link} href={`#/s/${row.id}`}>
        <span className={css.title}>{rowTitle(row)}</span>
        {directory !== null && <span className={css.dir}>{directory}</span>}
        <span className={css.state} data-state={state}>
          {isLiveState(state) && <span className={css.dot} />}
          {state}
        </span>
        {hasChildren && !expanded && (
          <span className={css.count}>+{node.descendants}</span>
        )}
        {node.orphanParent !== null && (
          <span className={css.orphan}>child of {node.orphanParent.slice(0, 8)}</span>
        )}
        <span className={css.spacer} />
        {row.model != null && row.model !== '' && <span className={css.model}>{row.model}</span>}
        <span className={css.time}>{relativeUpdated(row.updated_at, now)}</span>
      </a>
      {node.orphanParent !== null && (
        <a className={css.parentLink} href={`#/s/${node.orphanParent}`} title="Open the parent session">↑</a>
      )}
    </li>
  )
}

/** The `#/` landing page. */
export function SessionList() {
  const [rows, setRows] = useState<readonly SessionListRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [stale, setStale] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [query, setQuery] = useState('')
  // Parents the reader opened. Default is collapsed, so this starts empty.
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set())

  useEffect(() => {
    let disposed = false
    let controller: AbortController | null = null
    let timer: ReturnType<typeof setInterval> | null = null

    const poll = () => {
      controller?.abort()
      const current = new AbortController()
      controller = current
      setNow(Date.now())
      void (async () => {
        try {
          const list = await fetchSessions(SESSION_LIST_LIMIT, current.signal)
          if (disposed || current.signal.aborted) return
          setRows(list)
          setStale(false)
          setLoaded(true)
        } catch {
          if (disposed || current.signal.aborted) return
          // Keep the rows we already have; the badge says they are old.
          setStale(true)
          setLoaded(true)
        }
      })()
    }
    const start = () => { if (timer === null) timer = setInterval(poll, POLL_MS) }
    const stop = () => {
      if (timer === null) return
      clearInterval(timer)
      timer = null
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else {
        poll()
        start()
      }
    }

    poll()
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      disposed = true
      stop()
      controller?.abort()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  const filtered = useMemo(() => filterSessionRows(rows, query), [rows, query])
  const tree = useMemo(() => buildSessionTree(filtered), [filtered])
  // While a filter is active every parent opens, or a match could hide inside
  // a collapsed one.
  const expanded = useMemo(
    () => (query.trim() === '' ? opened : collectParentIds(tree, new Set<string>())),
    [opened, query, tree],
  )
  const visible = useMemo(() => flattenSessionTree(tree, expanded), [tree, expanded])

  const onToggle = useCallback((id: string) => {
    setOpened((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  return (
    <div className={css.page}>
      <header className={css.header}>
        <span className={css.brand}>klaude</span>
        <span className={css.headerCount}>
          {visible.length === filtered.length
            ? `${filtered.length} sessions`
            : `${filtered.length} sessions · ${visible.length} shown`}
        </span>
        {stale && <span className={css.stale} title="The last poll failed; showing the previous snapshot">stale</span>}
        <span className={css.spacer} />
        <input
          className={css.filter}
          type="search"
          value={query}
          spellCheck={false}
          placeholder="filter title / dir / model"
          aria-label="Filter sessions"
          onChange={(event) => { setQuery(event.target.value) }}
        />
      </header>
      <ul className={css.list}>
        {visible.map(node => (
          <SessionRow
            key={node.row.id}
            node={node}
            expanded={expanded.has(node.row.id)}
            onToggle={onToggle}
            now={now}
          />
        ))}
      </ul>
      {loaded && visible.length === 0 && (
        <p className={css.empty}>
          {rows.length === 0 ? 'No sessions on this server.' : 'No session matches the filter.'}
        </p>
      )}
      {!loaded && <p className={css.empty}>Loading sessions…</p>}
      <footer className={css.footer}>
        <a className={css.footerLink} href="#/fixture">offline fixture trajectory</a>
      </footer>
    </div>
  )
}
