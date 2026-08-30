/**
 * Pure live-state reducer for one session's WS stream.
 *
 * The snapshot model splits a trajectory in three: `eventNodes` (rows that
 * landed in `events.jsonl`, owned by REST), `partial` (the assistant response
 * currently streaming) and `runningCalls` (tool calls with no result yet).
 * This module owns only the last two. It never reconstructs history: the
 * `replay_history` frame is deliberately dropped, because REST already served
 * those rows with their ledger statuses.
 *
 * Everything here is a pure function of (state, frame). Sockets, timers and
 * React live in `use-live-session.ts`.
 */

import type { AssistantBlock } from '../../contract/index.ts'
import type { HistoryRow } from '../../adapter/index.ts'
import type { LiveEnvelope, LiveFrame } from './frames.ts'

/** A tool call seen on the wire whose `tool.result` has not arrived. */
export interface LiveToolCall {
  readonly callId: string
  readonly name: string
  /** Raw JSON arguments; empty while only `tool.call.start` has been seen. */
  readonly argsRaw: string
  /** Epoch ms the call event carried. */
  readonly time: number
}

/**
 * The streaming assistant response.
 *
 * `turn` / `step` are deliberately absent: the wire carries no absolute turn
 * ordinal, so `splice.ts` derives them from the landed rows instead.
 */
export interface LivePartial {
  /** Blocks in emission order; deltas extend the trailing one. */
  readonly blocks: readonly AssistantBlock[]
  /** `response_id` of the streaming response; null when the provider sent none. */
  readonly responseId: string | null
  /** Which trailing block deltas may extend; null after an `…end` event. */
  readonly openBlock: 'text' | 'reasoning' | null
  /** Set by `step.start`: the next delta opens a fresh response. */
  readonly stale: boolean
  /** Epoch ms of the first event of this response; null before one arrived. */
  readonly startedAt: number | null
  /**
   * `stop_reason` of the text block the final `AssistantMessage` closed.
   *
   * Only such a block carries one: a block cut short by a tool call has no
   * `stop_reason` key at all (and neither does an old tape), which is why an
   * absent value leaves this null instead of recording one.
   */
  readonly stopReason: string | null
  /** Epoch ms the stop reason arrived. */
  readonly stopReasonAt: number | null
}

/** Everything the viewer learns from one session's socket. */
export interface LiveState {
  /** Session that owns this socket. Envelopes for any other id are ignored. */
  readonly sessionId: string
  /** True between `open` and `close` on the underlying socket. */
  readonly connected: boolean
  /** True once `replay_complete` landed: from here on the stream is live. */
  readonly replayed: boolean
  /** True between `task.start` and `task.finish`. */
  readonly running: boolean
  readonly partial: LivePartial | null
  readonly runningCalls: readonly LiveToolCall[]
  /**
   * The session's state as the socket reports it: seeded by the attach
   * `session_info` frame, then kept current by `task.start` / `task.finish`.
   * Null until the first of those arrives, when `meta.state` is the fallback.
   */
  readonly sessionState: string | null
  /** `line_count` from the newest `history.appended`, or null. */
  readonly appendedLineCount: number | null
  /** Bumped by every `history.appended`, so an effect can depend on it. */
  readonly appendedSeq: number
  /** Bumped by every successful socket open, so an effect can refetch. */
  readonly connectionEpoch: number
  /** Message of the newest `error` frame, cleared on reconnect. */
  readonly error: string | null
}

/**
 * The zero state for one session.
 * @param sessionId - Session the socket belongs to.
 * @returns A disconnected, empty live state.
 */
export function initialLiveState(sessionId: string): LiveState {
  return {
    sessionId,
    connected: false,
    replayed: false,
    running: false,
    partial: null,
    runningCalls: [],
    sessionState: null,
    appendedLineCount: null,
    appendedSeq: 0,
    connectionEpoch: 0,
    error: null,
  }
}

/**
 * State for a freshly opened socket.
 *
 * Everything the previous connection accumulated is dropped: the new socket
 * asks for `replay=1`, so the tape re-delivers whatever is still in flight.
 * The two counters survive so effects keyed on them still see a change.
 * @param state - The state of the connection that just ended.
 * @returns The state to start the new connection from.
 */
export function liveSocketOpened(state: LiveState): LiveState {
  return {
    ...initialLiveState(state.sessionId),
    connected: true,
    appendedSeq: state.appendedSeq,
    connectionEpoch: state.connectionEpoch + 1,
  }
}

/**
 * Mark the socket closed.
 *
 * The in-flight projection is dropped with it: a partial nobody is streaming
 * any more would otherwise sit on screen forever.
 * @param state - Current state.
 * @returns State with the connection and its in-flight rows cleared.
 */
export function liveSocketClosed(state: LiveState): LiveState {
  if (!state.connected && state.partial === null && state.runningCalls.length === 0) return state
  return { ...state, connected: false, replayed: false, partial: null, runningCalls: [] }
}

function readString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function readNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** Envelope timestamps are Python epoch **seconds**. */
function envelopeTime(envelope: LiveEnvelope): number {
  const seconds = readNumber(envelope.timestamp)
  return seconds === null ? Date.now() : seconds * 1000
}

const EMPTY_PARTIAL: LivePartial = {
  blocks: [], responseId: null, openBlock: null, stale: false,
  startedAt: null, stopReason: null, stopReasonAt: null,
}

/**
 * Open (or keep) the partial the incoming response event belongs to.
 *
 * A different `response_id`, or a `step.start` since the last delta, starts a
 * fresh response; a null id on the wire just extends whatever is open.
 */
function openResponse(partial: LivePartial | null, responseId: string | null): LivePartial {
  if (partial === null) return { ...EMPTY_PARTIAL, responseId }
  if (partial.stale) return { ...EMPTY_PARTIAL, responseId }
  if (responseId !== null && partial.responseId !== null && partial.responseId !== responseId) {
    return { ...EMPTY_PARTIAL, responseId }
  }
  return partial.responseId === null && responseId !== null
    ? { ...partial, responseId }
    : partial
}

/**
 * `openResponse`, plus the start stamp a fresh response has not got yet.
 * @param partial - Current partial, or null when none is open.
 * @param responseId - `response_id` the incoming event carried, or null.
 * @param envelope - The event, for its timestamp.
 * @returns The partial the event belongs to, with `startedAt` filled in.
 */
function opened(
  partial: LivePartial | null,
  responseId: string | null,
  envelope: LiveEnvelope,
): LivePartial {
  const next = openResponse(partial, responseId)
  return next.startedAt === null ? { ...next, startedAt: envelopeTime(envelope) } : next
}

/** Append delta text to the trailing block of `kind`, or start one. */
function extend(
  partial: LivePartial,
  kind: 'text' | 'reasoning',
  text: string,
): LivePartial {
  if (text === '') return partial.openBlock === kind ? partial : { ...partial, openBlock: kind }
  const last = partial.blocks[partial.blocks.length - 1]
  if (partial.openBlock === kind && last !== undefined && last.kind === kind) {
    const merged: AssistantBlock = { kind, text: last.text + text }
    return { ...partial, blocks: [...partial.blocks.slice(0, -1), merged], openBlock: kind }
  }
  return { ...partial, blocks: [...partial.blocks, { kind, text }], openBlock: kind }
}

/** Register (or complete) a running call, newest write wins on name/args. */
function upsertCall(
  calls: readonly LiveToolCall[],
  call: LiveToolCall,
): readonly LiveToolCall[] {
  const index = calls.findIndex(entry => entry.callId === call.callId)
  if (index === -1) return [...calls, call]
  const existing = calls[index]
  if (existing === undefined) return [...calls, call]
  const merged: LiveToolCall = {
    callId: call.callId,
    name: call.name === '' ? existing.name : call.name,
    argsRaw: call.argsRaw === '' ? existing.argsRaw : call.argsRaw,
    time: existing.time,
  }
  return [...calls.slice(0, index), merged, ...calls.slice(index + 1)]
}

function withoutCall(
  calls: readonly LiveToolCall[],
  callId: string,
): readonly LiveToolCall[] {
  return calls.some(call => call.callId === callId)
    ? calls.filter(call => call.callId !== callId)
    : calls
}

/** Drop everything in flight; used by task boundaries and interrupts. */
function cleared(state: LiveState, running: boolean): LiveState {
  const sessionState = running ? 'running' : 'idle'
  if (
    state.partial === null && state.runningCalls.length === 0
    && state.running === running && state.sessionState === sessionState
  ) return state
  return { ...state, partial: null, runningCalls: [], running, sessionState }
}

function reduceEnvelope(state: LiveState, envelope: LiveEnvelope): LiveState {
  // Sub-agent events ride the parent's socket (`ws.py: _forward_events`); each
  // child has its own page and its own socket, so they are not ours.
  if (envelope.session_id !== state.sessionId) return state
  const event = envelope.event
  const responseId = readString(event.response_id)

  switch (envelope.event_type) {
    case 'thinking.start':
      return { ...state, partial: { ...opened(state.partial, responseId, envelope), openBlock: 'reasoning', stale: false } }
    case 'assistant.text.start':
      return { ...state, partial: { ...opened(state.partial, responseId, envelope), openBlock: 'text', stale: false } }
    case 'thinking.delta':
      return {
        ...state,
        partial: extend(
          { ...opened(state.partial, responseId, envelope), stale: false },
          'reasoning',
          readString(event.content) ?? '',
        ),
      }
    case 'assistant.text.delta':
      return {
        ...state,
        partial: extend(
          { ...opened(state.partial, responseId, envelope), stale: false },
          'text',
          readString(event.content) ?? '',
        ),
      }
    case 'assistant.text.end': {
      // The one event that reports why generation stopped — and only when the
      // block was closed by the final AssistantMessage. `splice.ts` turns it
      // into the same request status a landed `stop_reason` produces.
      if (state.partial === null) return state
      const stopReason = readString(event.stop_reason)
      if (stopReason === null && state.partial.openBlock === null) return state
      return {
        ...state,
        partial: {
          ...state.partial,
          openBlock: null,
          ...(stopReason === null
            ? {}
            : { stopReason, stopReasonAt: envelopeTime(envelope) }),
        },
      }
    }
    case 'thinking.end':
    case 'response.complete':
      return state.partial === null || state.partial.openBlock === null
        ? state
        : { ...state, partial: { ...state.partial, openBlock: null } }

    case 'tool.call.start': {
      const callId = readString(event.tool_call_id)
      if (callId === null) return state
      return {
        ...state,
        runningCalls: upsertCall(state.runningCalls, {
          callId,
          name: readString(event.tool_name) ?? '',
          argsRaw: '',
          time: envelopeTime(envelope),
        }),
      }
    }
    case 'tool.call': {
      const callId = readString(event.tool_call_id)
      if (callId === null) return state
      const name = readString(event.tool_name) ?? ''
      const argsRaw = readString(event.arguments) ?? ''
      const runningCalls = upsertCall(state.runningCalls, {
        callId, name, argsRaw, time: envelopeTime(envelope),
      })
      // A tool call closes the text run it interrupted; the block only joins
      // the partial when a response is already open (an idle socket has none).
      // `openResponse` still runs, so a call that opens a new step lands in a
      // fresh partial instead of extending the previous one.
      const base = state.partial === null ? null : opened(state.partial, responseId, envelope)
      const partial: LivePartial | null = base === null
        ? null
        : {
            ...base,
            blocks: [...base.blocks, { kind: 'tool-call' as const, callId, name, argsRaw }],
            openBlock: null,
            stale: false,
          }
      return { ...state, runningCalls, ...(partial === null ? {} : { partial }) }
    }
    case 'tool.result': {
      const callId = readString(event.tool_call_id)
      if (callId === null) return state
      const runningCalls = withoutCall(state.runningCalls, callId)
      return runningCalls === state.runningCalls ? state : { ...state, runningCalls }
    }

    case 'step.start':
      // The previous step's output is on its way to disk. Mark the partial
      // stale rather than dropping it, so the text stays on screen until the
      // landed row replaces it.
      return {
        ...state,
        running: true,
        sessionState: 'running',
        ...(state.partial === null ? {} : { partial: { ...state.partial, stale: true, openBlock: null } }),
      }
    case 'task.start':
      return { ...cleared(state, true), error: null }
    case 'task.finish':
      return cleared(state, false)
    case 'interrupt':
      return cleared(state, false)

    case 'history.appended': {
      const lineCount = readNumber(event.line_count)
      if (lineCount === null) return state
      return { ...state, appendedLineCount: lineCount, appendedSeq: state.appendedSeq + 1 }
    }

    default:
      // usage, user.message, tool.output.delta, notices, todo changes … carry
      // nothing the snapshot's two live fields can hold.
      return state
  }
}

function reduceControl(state: LiveState, frame: Record<string, unknown>): LiveState {
  const sessionId = readString(frame.session_id)
  if (sessionId !== null && sessionId !== state.sessionId) return state
  switch (frame.type) {
    case 'replay_complete':
      return state.replayed ? state : { ...state, replayed: true }
    case 'session_info': {
      const value = readString(frame.state)
      if (value === null || (value === state.sessionState && state.running === (value === 'running'))) {
        return state
      }
      return { ...state, sessionState: value, running: value === 'running' }
    }
    case 'error': {
      const message = readString(frame.message) ?? readString(frame.code) ?? 'socket error'
      return { ...state, error: message }
    }
    // connection_info (its code_fingerprint is a server-side digest a browser
    // cannot compute — reading it would be a permanent false positive),
    // usage.snapshot, replay_history (REST owns landed rows) and
    // follow_ups_dequeued carry nothing this viewer renders.
    default:
      return state
  }
}

/**
 * Fold one wire frame into the live state.
 * @param state - Current live state.
 * @param frame - One parsed frame (`parseLiveFrames`).
 * @returns The next state; the same object when nothing changed.
 */
export function liveReducer(state: LiveState, frame: LiveFrame): LiveState {
  return frame.kind === 'envelope'
    ? reduceEnvelope(state, frame.envelope)
    : reduceControl(state, frame.frame)
}

/**
 * Fold every frame of one received WS message.
 * @param state - Current live state.
 * @param frames - Frames the message carried, in order.
 * @returns The next state; the same object when nothing changed.
 */
export function reduceLiveFrames(
  state: LiveState,
  frames: readonly LiveFrame[],
): LiveState {
  let next = state
  for (const frame of frames) next = liveReducer(next, frame)
  return next
}

/** What a freshly loaded batch of ledger rows settles. */
interface LandedFacts {
  readonly anyAssistant: boolean
  readonly assistantResponseIds: readonly string[]
  readonly assistantsWithoutResponseId: boolean
  readonly resultCallIds: readonly string[]
}

function landedFacts(rows: readonly HistoryRow[]): LandedFacts {
  const assistantResponseIds: string[] = []
  const resultCallIds: string[] = []
  let anyAssistant = false
  let assistantsWithoutResponseId = false
  for (const row of rows) {
    const entry = row.entry
    if (entry === null) continue
    if (entry.type === 'AssistantMessage') {
      anyAssistant = true
      const responseId = readString(entry.data.response_id)
      if (responseId === null) assistantsWithoutResponseId = true
      else assistantResponseIds.push(responseId)
      continue
    }
    if (entry.type === 'ToolResultMessage') {
      const callId = readString(entry.data.call_id)
      if (callId !== null) resultCallIds.push(callId)
    }
  }
  return { anyAssistant, assistantResponseIds, assistantsWithoutResponseId, resultCallIds }
}

/**
 * Retire the in-flight projection that a batch of landed rows replaced.
 *
 * The durable row is always the better copy: once the `AssistantMessage` is in
 * `events.jsonl` it carries usage, timing and a stable seq that the streamed
 * prefix never had, and the `ToolResultMessage` turns a running call into a
 * foldable tool row.
 * @param state - Current live state.
 * @param rows - Rows that just landed (a `history.appended` tail increment).
 * @returns The next state; the same object when nothing was retired.
 */
export function applyLandedRows(
  state: LiveState,
  rows: readonly HistoryRow[],
): LiveState {
  const facts = landedFacts(rows)
  const runningCalls = facts.resultCallIds.reduce(withoutCall, state.runningCalls)
  const partial = state.partial
  const dropPartial = partial !== null && facts.anyAssistant && (
    // Same response: unambiguous.
    (partial.responseId !== null && facts.assistantResponseIds.includes(partial.responseId))
    // No id to match on, either side: any assistant landing ends the stream.
    || partial.responseId === null
    || facts.assistantsWithoutResponseId
  )
  if (!dropPartial && runningCalls === state.runningCalls) return state
  return { ...state, runningCalls, ...(dropPartial ? { partial: null } : {}) }
}
