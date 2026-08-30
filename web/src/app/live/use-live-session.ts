/**
 * The one impure piece of the live channel: socket, backoff and the frame
 * coalescer that keeps a long stream from re-rendering React per delta.
 *
 * Frames land in a ref and are published on a timer, so a burst of a hundred
 * `assistant.text.delta` events costs one render instead of a hundred. The
 * reducer itself (`reducer.ts`) stays pure and is tested without any of this.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { HistoryRow } from '../../adapter/index.ts'
import { parseLiveMessage } from './frames.ts'
import type { LiveState } from './reducer.ts'
import {
  applyLandedRows, initialLiveState, liveSocketClosed, liveSocketOpened, reduceLiveFrames,
} from './reducer.ts'

/** Publish window. Long enough to batch a stream, short enough to feel live. */
const COALESCE_MS = 50

/** Reconnect backoff bounds. */
const RETRY_BASE_MS = 1000
const RETRY_MAX_MS = 30_000

/**
 * Same-origin WS URL for one session.
 *
 * `replay=1` gets the attach tape (so a reconnect recovers whatever is still
 * streaming); `peek=1` marks the connection read-only, which keeps the viewer
 * out of the server's "someone is at a prompt" accounting (decision #8).
 * @param sessionId - Session id.
 * @returns The absolute socket URL.
 */
export function liveSocketUrl(sessionId: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}`
    + `/api/sessions/${encodeURIComponent(sessionId)}/ws?replay=1&peek=1`
}

/** Handle returned by `useLiveSession`. */
export interface LiveSession {
  readonly state: LiveState
  /**
   * Retire the in-flight rows a batch of landed ledger rows replaced.
   * Call it right after folding a `history.appended` tail increment.
   */
  readonly acknowledge: (rows: readonly HistoryRow[]) => void
}

/**
 * Follow one session's live stream.
 *
 * The socket is opened only while `enabled` is true — a cold session has no
 * agent in memory and connecting would spin one up (decision #28).
 * @param sessionId - Session to follow.
 * @param enabled - Whether the session is loaded (or listed as running).
 * @returns The published live state plus the acknowledge hook.
 */
export function useLiveSession(sessionId: string, enabled: boolean): LiveSession {
  const stateRef = useRef<LiveState>(initialLiveState(sessionId))
  const [published, setPublished] = useState<LiveState>(stateRef.current)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const apply = useCallback((next: LiveState) => {
    if (next === stateRef.current) return
    stateRef.current = next
    if (timerRef.current !== null) return
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      setPublished(stateRef.current)
    }, COALESCE_MS)
  }, [])

  const acknowledge = useCallback((rows: readonly HistoryRow[]) => {
    apply(applyLandedRows(stateRef.current, rows))
  }, [apply])

  useEffect(() => {
    const fresh = initialLiveState(sessionId)
    stateRef.current = fresh
    setPublished(fresh)
    if (!enabled) return

    let disposed = false
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    let attempt = 0

    const connect = () => {
      if (disposed) return
      const next = new WebSocket(liveSocketUrl(sessionId))
      socket = next
      next.onopen = () => {
        attempt = 0
        apply(liveSocketOpened(stateRef.current))
      }
      next.onmessage = (event: MessageEvent<unknown>) => {
        apply(reduceLiveFrames(stateRef.current, parseLiveMessage(event.data)))
      }
      next.onerror = () => { next.close() }
      next.onclose = () => {
        if (disposed || socket !== next) return
        socket = null
        apply(liveSocketClosed(stateRef.current))
        const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** attempt)
        attempt += 1
        retry = setTimeout(connect, delay)
      }
    }
    connect()

    return () => {
      disposed = true
      if (retry !== null) clearTimeout(retry)
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      const open = socket
      socket = null
      open?.close()
    }
  }, [apply, enabled, sessionId])

  return { state: published, acknowledge }
}
