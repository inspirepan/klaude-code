/**
 * Wire shapes of `/api/sessions/{id}/ws` and the one function that normalizes
 * a received message into frames.
 *
 * Two frame families travel on the same socket (`server/routes/ws.py`):
 *
 * - **envelopes** — `{event_id, event_seq, session_id, …, event_type, event}`;
 *   the actual session events.
 * - **control frames** — a bare `{type: …}` object: `connection_info`,
 *   `session_info`, `usage.snapshot`, `replay_history`, `replay_complete`,
 *   `follow_ups_dequeued`, `error`.
 *
 * `_send_batched` sends a bare object for a single event and a **JSON array**
 * when several were coalesced, so every reader must accept both.
 */

/** One session event as it travels on the socket. */
export interface LiveEnvelope {
  readonly event_id?: string
  /**
   * Monotonic per server process. It restarts at 1 when the server restarts,
   * and attach-synthesized envelopes carry 0, so it is never a global
   * identity — this client only uses it to spot a replay gap, never to order.
   */
  readonly event_seq?: number
  readonly session_id: string
  readonly operation_id?: string
  readonly task_id?: string
  readonly causation_id?: string
  readonly event_type: string
  readonly durability?: string
  readonly timestamp?: number
  readonly event: Record<string, unknown>
}

/** A non-envelope control frame; `type` discriminates. */
export interface LiveControlFrame {
  readonly type: string
  readonly [key: string]: unknown
}

/** Either family, tagged so the reducer can switch once. */
export type LiveFrame =
  | { readonly kind: 'envelope'; readonly envelope: LiveEnvelope }
  | { readonly kind: 'control'; readonly frame: LiveControlFrame }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function toFrame(value: unknown): LiveFrame | null {
  if (!isRecord(value)) return null
  if (typeof value.event_type === 'string' && isRecord(value.event)
    && typeof value.session_id === 'string') {
    return { kind: 'envelope', envelope: value as unknown as LiveEnvelope }
  }
  if (typeof value.type === 'string') {
    return { kind: 'control', frame: value as LiveControlFrame }
  }
  return null
}

/**
 * Normalize one received WS message into zero or more frames.
 *
 * Accepts the already-parsed JSON value: a single frame object, or the array
 * the server sends when it batched a burst. Anything unrecognizable is
 * dropped rather than thrown — a viewer must survive a server that learned a
 * new frame type.
 * @param data - Parsed JSON payload of one `message` event.
 * @returns The frames it carried, in order.
 */
export function parseLiveFrames(data: unknown): readonly LiveFrame[] {
  if (Array.isArray(data)) {
    const frames: LiveFrame[] = []
    for (const item of data) {
      const frame = toFrame(item)
      if (frame !== null) frames.push(frame)
    }
    return frames
  }
  const frame = toFrame(data)
  return frame === null ? [] : [frame]
}

/**
 * Parse a raw `MessageEvent.data` string into frames.
 * @param raw - The socket payload; non-strings and bad JSON yield no frames.
 * @returns The frames it carried, in order.
 */
export function parseLiveMessage(raw: unknown): readonly LiveFrame[] {
  if (typeof raw !== 'string') return []
  try {
    return parseLiveFrames(JSON.parse(raw))
  } catch {
    return []
  }
}
