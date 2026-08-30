import { describe, expect, it } from 'vitest'
import { row } from '../../adapter/fixtures.ts'
import { parseLiveFrames } from './frames.ts'
import type { LiveState } from './reducer.ts'
import {
  applyLandedRows, initialLiveState, liveSocketClosed, liveSocketOpened, reduceLiveFrames,
} from './reducer.ts'

const SESSION = 'sess1'

/** One envelope as `ws.py` serializes it (`timestamp` is epoch seconds). */
function envelope(
  eventType: string,
  event: Record<string, unknown> = {},
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    event_id: `e${eventType}`,
    event_seq: 1,
    session_id: SESSION,
    event_type: eventType,
    durability: 'ephemeral',
    timestamp: 1_800_000_000,
    event: { session_id: SESSION, timestamp: 1_800_000_000, ...event },
    ...overrides,
  }
}

/** Fold a list of raw wire payloads (objects or batch arrays) into state. */
function feed(state: LiveState, ...payloads: readonly unknown[]): LiveState {
  let next = state
  for (const payload of payloads) next = reduceLiveFrames(next, parseLiveFrames(payload))
  return next
}

const OPEN = liveSocketOpened(initialLiveState(SESSION))

describe('streaming assistant output', () => {
  it('accumulates thinking then text into one partial', () => {
    const state = feed(
      OPEN,
      envelope('thinking.start', { response_id: 'r1' }),
      envelope('thinking.delta', { response_id: 'r1', content: 'let me ' }),
      envelope('thinking.delta', { response_id: 'r1', content: 'check' }),
      envelope('thinking.end', { response_id: 'r1' }),
      envelope('assistant.text.start', { response_id: 'r1' }),
      envelope('assistant.text.delta', { response_id: 'r1', content: 'Done' }),
      envelope('assistant.text.delta', { response_id: 'r1', content: '.' }),
    )
    expect(state.partial?.responseId).toBe('r1')
    expect(state.partial?.blocks).toEqual([
      { kind: 'reasoning', text: 'let me check' },
      { kind: 'text', text: 'Done.' },
    ])
  })

  it('starts a fresh partial when the response id changes', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'first' }),
      envelope('assistant.text.delta', { response_id: 'r2', content: 'second' }),
    )
    expect(state.partial?.blocks).toEqual([{ kind: 'text', text: 'second' }])
    expect(state.partial?.responseId).toBe('r2')
  })

  it('replaces the partial after step.start even without response ids', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { content: 'step one' }),
      envelope('step.start'),
      envelope('assistant.text.delta', { content: 'step two' }),
    )
    expect(state.partial?.blocks).toEqual([{ kind: 'text', text: 'step two' }])
    expect(state.running).toBe(true)
  })

  it('keeps the previous step visible until the next delta arrives', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { content: 'step one' }),
      envelope('step.start'),
    )
    expect(state.partial?.blocks).toEqual([{ kind: 'text', text: 'step one' }])
  })

  it('starts a new block when a delta follows an end of the same kind', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'a' }),
      envelope('assistant.text.end', { response_id: 'r1' }),
      envelope('assistant.text.delta', { response_id: 'r1', content: 'b' }),
    )
    expect(state.partial?.blocks).toEqual([
      { kind: 'text', text: 'a' },
      { kind: 'text', text: 'b' },
    ])
  })
})

describe('running tool calls', () => {
  it('opens on tool.call.start, completes on tool.call, clears on tool.result', () => {
    const started = feed(
      OPEN,
      envelope('tool.call.start', { response_id: 'r1', tool_call_id: 'c1', tool_name: 'Read' }),
    )
    expect(started.runningCalls).toEqual([
      { callId: 'c1', name: 'Read', argsRaw: '', time: 1_800_000_000_000 },
    ])
    // No block yet: only the completed call joins the partial.
    expect(started.partial).toBeNull()

    const called = feed(
      started,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'reading' }),
      envelope('tool.call', {
        response_id: 'r1', tool_call_id: 'c1', tool_name: 'Read', arguments: '{"path":"a.ts"}',
      }),
    )
    expect(called.runningCalls[0]?.argsRaw).toBe('{"path":"a.ts"}')
    expect(called.partial?.blocks.at(-1)).toEqual({
      kind: 'tool-call', callId: 'c1', name: 'Read', argsRaw: '{"path":"a.ts"}',
    })

    const done = feed(called, envelope('tool.result', {
      response_id: 'r1', tool_call_id: 'c1', tool_name: 'Read', result: 'ok', status: 'success',
    }))
    expect(done.runningCalls).toEqual([])
    // The streamed text is untouched; only the call card is retired.
    expect(done.partial?.blocks.length).toBe(2)
  })

  it('opens a fresh partial when a tool call starts the next step', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { content: 'step one' }),
      envelope('step.start'),
      envelope('tool.call', { tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
    )
    expect(state.partial?.blocks).toEqual([
      { kind: 'tool-call', callId: 'c1', name: 'Read', argsRaw: '{}' },
    ])
  })

  it('tracks parallel calls independently', () => {
    const state = feed(
      OPEN,
      envelope('tool.call', { tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
      envelope('tool.call', { tool_call_id: 'c2', tool_name: 'Bash', arguments: '{}' }),
      envelope('tool.result', { tool_call_id: 'c1', tool_name: 'Read', result: '', status: 'success' }),
    )
    expect(state.runningCalls.map(call => call.callId)).toEqual(['c2'])
  })

  it('drops everything in flight on task.finish and on interrupt', () => {
    const busy = feed(
      OPEN,
      envelope('assistant.text.delta', { content: 'x' }),
      envelope('tool.call', { tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
    )
    for (const closer of ['task.finish', 'interrupt']) {
      const closed = feed(busy, envelope(closer, closer === 'task.finish' ? { task_result: '' } : {}))
      expect(closed.partial).toBeNull()
      expect(closed.runningCalls).toEqual([])
      expect(closed.running).toBe(false)
      expect(closed.sessionState).toBe('idle')
    }
  })
})

describe('frame handling', () => {
  it('folds a batched JSON array in order', () => {
    const batched = feed(OPEN, [
      envelope('assistant.text.delta', { response_id: 'r1', content: 'one ' }),
      envelope('assistant.text.delta', { response_id: 'r1', content: 'two' }),
      envelope('tool.call', { tool_call_id: 'c9', tool_name: 'Grep', arguments: '{}' }),
    ])
    expect(batched.partial?.blocks[0]).toEqual({ kind: 'text', text: 'one two' })
    expect(batched.runningCalls.map(call => call.callId)).toEqual(['c9'])
  })

  it('ignores envelopes from another session', () => {
    // Sub-agent events are forwarded on the parent socket; each child has its
    // own page and its own socket.
    const state = feed(OPEN, envelope('assistant.text.delta', { content: 'child' }, {
      session_id: 'child-session',
    }))
    expect(state).toBe(OPEN)
    expect(state.partial).toBeNull()
  })

  it('treats replay_complete as "live now" and reads session_info state', () => {
    const state = feed(
      OPEN,
      { type: 'connection_info', can_input: false, session_id: SESSION, code_fingerprint: 'abc' },
      { type: 'session_info', session_id: SESSION, state: 'running' },
      { type: 'usage.snapshot', session_id: SESSION, event_type: 'usage.snapshot' },
      { type: 'replay_history', session_id: SESSION, events: [{ event_type: 'user.message', event: {} }] },
      { type: 'replay_complete', session_id: SESSION },
    )
    expect(state.replayed).toBe(true)
    expect(state.sessionState).toBe('running')
    expect(state.running).toBe(true)
    // replay_history is deliberately dropped: REST owns landed rows.
    expect(state.partial).toBeNull()
  })

  it('survives malformed and unknown payloads', () => {
    expect(parseLiveFrames(null)).toEqual([])
    expect(parseLiveFrames(['not a frame', 7, { nope: true }])).toEqual([])
    expect(feed(OPEN, { type: 'follow_ups_dequeued', session_id: SESSION, texts: [] })).toBe(OPEN)
    expect(feed(OPEN, envelope('todo.change')).partial).toBeNull()
  })

  it('records history.appended and bumps its counter', () => {
    const state = feed(OPEN, envelope('history.appended', { line_count: 42 }))
    expect(state.appendedLineCount).toBe(42)
    expect(state.appendedSeq).toBe(1)
    expect(feed(state, envelope('history.appended', { line_count: 44 })).appendedSeq).toBe(2)
  })
})

describe('socket transitions', () => {
  it('keeps the counters but drops in-flight rows across a reconnect', () => {
    const busy = feed(
      OPEN,
      envelope('history.appended', { line_count: 10 }),
      envelope('assistant.text.delta', { content: 'x' }),
    )
    const closed = liveSocketClosed(busy)
    expect(closed.connected).toBe(false)
    expect(closed.partial).toBeNull()

    const reopened = liveSocketOpened(closed)
    expect(reopened.connected).toBe(true)
    expect(reopened.appendedSeq).toBe(busy.appendedSeq)
    expect(reopened.connectionEpoch).toBe(busy.connectionEpoch + 1)
  })
})

describe('landed rows retire the live projection', () => {
  const streaming = feed(
    OPEN,
    envelope('assistant.text.delta', { response_id: 'r1', content: 'answer' }),
    envelope('tool.call', { response_id: 'r1', tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
    envelope('tool.call', { response_id: 'r1', tool_call_id: 'c2', tool_name: 'Bash', arguments: '{}' }),
  )

  it('drops the partial when its own assistant message lands', () => {
    const settled = applyLandedRows(streaming, [
      row(7, 'AssistantMessage', { response_id: 'r1', parts: [] }),
    ])
    expect(settled.partial).toBeNull()
    expect(settled.runningCalls.map(call => call.callId)).toEqual(['c1', 'c2'])
  })

  it('keeps the partial when a different response landed', () => {
    const settled = applyLandedRows(streaming, [
      row(7, 'AssistantMessage', { response_id: 'other', parts: [] }),
    ])
    expect(settled.partial?.blocks).toEqual(streaming.partial?.blocks)
  })

  it('falls back to "any assistant landed" when no response id is on offer', () => {
    const anonymous = feed(OPEN, envelope('assistant.text.delta', { content: 'answer' }))
    expect(applyLandedRows(anonymous, [row(7, 'AssistantMessage', { parts: [] })]).partial)
      .toBeNull()
    // …and the same the other way round: an id on the wire, none on disk.
    expect(applyLandedRows(streaming, [row(7, 'AssistantMessage', { parts: [] })]).partial)
      .toBeNull()
  })

  it('retires only the running call whose result landed', () => {
    const settled = applyLandedRows(streaming, [
      row(8, 'ToolResultMessage', { call_id: 'c1', tool_name: 'Read', status: 'success', output_text: '' }),
    ])
    expect(settled.runningCalls.map(call => call.callId)).toEqual(['c2'])
    expect(settled.partial).not.toBeNull()
  })

  it('is a no-op for rows that settle nothing', () => {
    expect(applyLandedRows(streaming, [row(9, 'TaskMetadataItem', {})])).toBe(streaming)
    expect(applyLandedRows(streaming, [])).toBe(streaming)
  })
})

describe('stop reason', () => {
  it('records the reason the final text block reported', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.start', { response_id: 'r1' }),
      envelope('assistant.text.delta', { response_id: 'r1', content: 'done' }),
      envelope('assistant.text.end', { response_id: 'r1', stop_reason: 'end_turn' }),
    )
    expect(state.partial?.stopReason).toBe('end_turn')
    expect(state.partial?.stopReasonAt).toBe(1_800_000_000_000)
    expect(state.partial?.openBlock).toBeNull()
  })

  it('records an error the same way a landed row does', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'half' }),
      envelope('assistant.text.end', { response_id: 'r1', stop_reason: 'error' }),
    )
    expect(state.partial?.stopReason).toBe('error')
  })

  it('ignores a block a tool call cut short, which carries no key at all', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'calling' }),
      envelope('assistant.text.end', { response_id: 'r1' }),
    )
    expect(state.partial?.stopReason).toBeNull()
    expect(state.partial?.openBlock).toBeNull()
  })

  it('clears it when the next response opens', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.delta', { response_id: 'r1', content: 'first' }),
      envelope('assistant.text.end', { response_id: 'r1', stop_reason: 'end_turn' }),
      envelope('assistant.text.delta', { response_id: 'r2', content: 'second' }),
    )
    expect(state.partial?.responseId).toBe('r2')
    expect(state.partial?.stopReason).toBeNull()
  })

  it('stamps the start of the response it belongs to', () => {
    const state = feed(
      OPEN,
      envelope('assistant.text.start', { response_id: 'r1' }, { timestamp: 1_800_000_001 }),
      envelope('assistant.text.delta', { response_id: 'r1', content: 'x' }, { timestamp: 1_800_000_002 }),
    )
    expect(state.partial?.startedAt).toBe(1_800_000_001_000)
  })
})
