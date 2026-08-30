/** Entry point: hash routing over the forked trajectory view. */

import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import '../theme/base.css'
import '../theme/design-platform.css'
import '../theme/gradient-shadow-text.css' // klaude: defines the --dsw-font-* composites the trajectory CSS consumes
import '../theme/scrollbar.css'
import '../theme/shiki.css'
import './main.css'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import type { TrajectorySessionState } from '../trajectory/TrajectoryView.tsx'
import { t } from '../locale.ts'
import { FIXTURE_SNAPSHOT } from './fixture.ts'
import { SessionList } from './SessionList.tsx'
import { SessionPage } from './session-page.tsx'
import { useActualDuration } from './duration.ts'
import { renderImages } from './render-images.tsx'

type Route =
  | { readonly name: 'home' }
  | { readonly name: 'session'; readonly sessionId: string }
  | { readonly name: 'fixture' }

const FIXTURE_SESSION: TrajectorySessionState = {
  openState: 'open',
  loadingOlder: false,
  hasMore: false,
}

function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '')
  const session = /^\/s\/([^/?#]+)/.exec(path)
  if (session?.[1] !== undefined) {
    return { name: 'session', sessionId: decodeURIComponent(session[1]) }
  }
  if (path === '/fixture') return { name: 'fixture' }
  return { name: 'home' }
}

function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onChange = () => { setRoute(parseRoute(window.location.hash)) }
    window.addEventListener('hashchange', onChange)
    return () => { window.removeEventListener('hashchange', onChange) }
  }, [])
  return route
}

/** The hand-written snapshot, so the ledger renders with no server running. */
function FixturePage() {
  const [actualDuration, setActualDuration] = useActualDuration()
  return (
    <TrajectoryView
      snapshot={FIXTURE_SNAPSHOT}
      session={FIXTURE_SESSION}
      actualDuration={actualDuration}
      setActualDuration={setActualDuration}
      loadOlder={() => Promise.resolve(false)}
      renderImages={renderImages}
      t={t}
    />
  )
}

function App() {
  const route = useRoute()
  if (route.name === 'session') return <SessionPage key={route.sessionId} sessionId={route.sessionId} />
  if (route.name === 'fixture') return <FixturePage />
  return <SessionList />
}

const host = document.getElementById('root')
if (host === null) throw new Error('index.html lost its #root mount')
createRoot(host).render(<StrictMode><App /></StrictMode>)
