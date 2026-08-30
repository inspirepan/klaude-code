/** Standalone entry: mounts the forked trajectory view over a fixture snapshot. */

import { StrictMode, useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import '../theme/base.css'
import '../theme/design-platform.css'
import '../theme/scrollbar.css'
import '../theme/shiki.css'
import './main.css'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import type { TrajectorySessionState } from '../trajectory/TrajectoryView.tsx'
import { t } from '../locale.ts'
import { FIXTURE_SNAPSHOT } from './fixture.ts'

const DURATION_KEY = 'dsh.trajectory.duration'

const SESSION: TrajectorySessionState = {
  openState: 'open',
  loadingOlder: false,
  hasMore: false,
}

/** Read the persisted duration preference; storage may be unavailable. */
function readActualDuration(): boolean {
  try {
    return window.localStorage.getItem(DURATION_KEY) === 'true'
  } catch {
    return false
  }
}

/** The image slot is unimplemented until the file endpoint lands. */
function renderImages(): null {
  return null
}

function App() {
  const [actualDuration, setStoredActualDuration] = useState(readActualDuration)
  const setActualDuration = useCallback((next: boolean) => {
    setStoredActualDuration(next)
    try {
      window.localStorage.setItem(DURATION_KEY, String(next))
    } catch {
      // A private window with storage blocked keeps the in-memory preference.
    }
  }, [])
  const loadOlder = useCallback(() => Promise.resolve(false), [])
  return (
    <TrajectoryView
      snapshot={FIXTURE_SNAPSHOT}
      session={SESSION}
      actualDuration={actualDuration}
      setActualDuration={setActualDuration}
      loadOlder={loadOlder}
      renderImages={renderImages}
      t={t}
    />
  )
}

const host = document.getElementById('root')
if (host === null) throw new Error('index.html lost its #root mount')
createRoot(host).render(<StrictMode><App /></StrictMode>)
