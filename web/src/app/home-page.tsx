/**
 * Placeholder landing page.
 *
 * The real session list (`GET /api/headless/sessions`, 5s polling, parent
 * grouping) is part 2 of M2; until then this page just opens a session by id
 * and lists whatever the endpoint already returns when it is reachable.
 */

import { useEffect, useState } from 'react'
import type { SessionListRow } from '../adapter/index.ts'
import { fetchSessions } from './api.ts'
import css from './home-page.module.css'

/** Session-id entry point plus a raw list preview. */
export function HomePage() {
  const [sessionId, setSessionId] = useState('')
  const [sessions, setSessions] = useState<readonly SessionListRow[]>([])
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const rows = await fetchSessions(50, controller.signal)
        if (!controller.signal.aborted) setSessions(rows)
      } catch (error) {
        if (controller.signal.aborted) return
        setFailure(error instanceof Error ? error.message : String(error))
      }
    })()
    return () => { controller.abort() }
  }, [])

  return (
    <div className={css.page}>
      <h1 className={css.heading}>klaude trajectory viewer</h1>
      <p className={css.note}>The session list page comes in part 2. Open a session by id:</p>
      <form
        className={css.form}
        onSubmit={(event) => {
          event.preventDefault()
          const id = sessionId.trim()
          if (id !== '') window.location.hash = `#/s/${id}`
        }}
      >
        <input
          className={css.input}
          value={sessionId}
          spellCheck={false}
          placeholder="session id"
          onChange={(event) => { setSessionId(event.target.value) }}
        />
        <button className={css.button} type="submit">Open</button>
      </form>
      {failure !== null && <p className={css.failure}>{failure}</p>}
      <ul className={css.list}>
        {sessions.map(row => (
          <li key={row.session_id}>
            <a className={css.link} href={`#/s/${row.session_id}`}>
              <span className={css.title}>{row.title ?? row.session_id}</span>
              <span className={css.meta}>{row.state ?? ''}</span>
              <span className={css.meta}>{row.model ?? ''}</span>
            </a>
          </li>
        ))}
      </ul>
      <p className={css.note}>
        <a className={css.link} href="#/fixture">Open the offline fixture trajectory</a>
      </p>
    </div>
  )
}
