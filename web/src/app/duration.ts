/**
 * Timeline duration preference (UX spec D7).
 *
 * Upstream keeps it in a zustand snapshot store under `dsh.trajectory.duration`;
 * this fork keeps the same key in `localStorage` and hands the view a plain
 * value plus a setter.
 */

import { useCallback, useState } from 'react'

const DURATION_KEY = 'dsh.trajectory.duration'

function readActualDuration(): boolean {
  try {
    return window.localStorage.getItem(DURATION_KEY) === 'true'
  } catch {
    return false
  }
}

/**
 * Read and persist the duration toggle.
 * @returns The current preference and its setter.
 */
export function useActualDuration(): readonly [boolean, (next: boolean) => void] {
  const [actualDuration, setValue] = useState(readActualDuration)
  const setActualDuration = useCallback((next: boolean) => {
    setValue(next)
    try {
      window.localStorage.setItem(DURATION_KEY, String(next))
    } catch {
      // A private window with storage blocked keeps the in-memory preference.
    }
  }, [])
  return [actualDuration, setActualDuration]
}
