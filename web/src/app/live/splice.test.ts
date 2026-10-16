import { describe, expect, it } from 'vitest'
import { buildTrajectorySnapshot } from '../../adapter/index.ts'
import { row, stamp, usage } from '../../adapter/fixtures.ts'
import type { HistoryRow } from '../../adapter/index.ts'
import { parseLiveFrames } from './frames.ts'
import { initialLiveState, liveSocketOpened, reduceLiveFrames } from './reducer.ts'
import type { LiveState } from './reducer.ts'
import { spliceLiveSnapshot, trajectoryAnchor } from './splice.ts'

const SESSION = 'sess1'

function snapshotOf(rows: readonly HistoryRow[]) {
  return buildTrajectorySnapshot(rows, { sessionId: SESSION })
}

function envelope(eventType: string, event: Record<string, unknown>): Record<string, unknown> {
  return {
    event_id: 'e1',
    event_seq: 1,
    session_id: SESSION,
    event_type: eventType,
    durability: 'ephemeral',
    timestamp: 1_800_000_000,
    event: { session_id: SESSION, ...event },
  }
}

function live(...payloads: readonly unknown[]): LiveState {
  let state = liveSocketOpened(initialLiveState(SESSION))
  for (const payload of payloads) state = reduceLiveFrames(state, parseLiveFrames(payload))
  return state
}

const TURN_1 = [
  row(0, 'UserMessage', { created_at: stamp(0), parts: [{ type: 'text', text: 'go' }] }),
  row(1, 'AssistantMessage', {
    created_at: stamp(20),
    response_id: 'r1',
    parts: [{ type: 'text', text: 'done' }],
    usage: usage(),
    stop_reason: 'stop',
  }),
]

describe('anchor', () => {
  it('reads the newest landed assistant step', () => {
    expect(trajectoryAnchor(snapshotOf(TURN_1))).toEqual({ turn: 1, step: 1 })
  })

  it('reports step 0 when the newest row opened a turn', () => {
    expect(trajectoryAnchor(snapshotOf(TURN_1.slice(0, 1)))).toEqual({ turn: 1, step: 0 })
  })

  it('defaults to turn 1 for an empty snapshot', () => {
    expect(trajectoryAnchor(snapshotOf([]))).toEqual({ turn: 1, step: 0 })
  })
})

describe('splice', () => {
  it('returns the snapshot untouched when nothing is in flight', () => {
    const snapshot = snapshotOf(TURN_1)
    expect(spliceLiveSnapshot(snapshot, initialLiveState(SESSION))).toBe(snapshot)
  })

  it('numbers the streaming partial as the step after the newest landed one', () => {
    const spliced = spliceLiveSnapshot(
      snapshotOf(TURN_1),
      live(envelope('assistant.text.delta', { response_id: 'r2', content: 'next' })),
    )
    expect(spliced.partial).toEqual({
      turn: 1, step: 2, blocks: [{ kind: 'text', text: 'next' }],
    })
  })

  it('places a running call in the landed step when its response already landed', () => {
    const spliced = spliceLiveSnapshot(
      snapshotOf(TURN_1),
      live(envelope('tool.call', { tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' })),
    )
    expect(spliced.runningCalls).toEqual([{
      callId: 'c1',
      name: 'Read',
      argsRaw: '{}',
      turn: 1,
      step: 1,
      time: 1_800_000_000_000,
      subCalls: [],
    }])
  })

  it('places a running call in the streaming step when the response is still open', () => {
    const spliced = spliceLiveSnapshot(
      snapshotOf(TURN_1),
      live(
        envelope('assistant.text.delta', { response_id: 'r2', content: 'calling' }),
        envelope('tool.call', { response_id: 'r2', tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
      ),
    )
    expect(spliced.runningCalls[0]?.step).toBe(2)
    expect(spliced.partial?.step).toBe(2)
  })

  it('never places a call in step 0', () => {
    const spliced = spliceLiveSnapshot(
      snapshotOf(TURN_1.slice(0, 1)),
      live(envelope('tool.call', { tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' })),
    )
    expect(spliced.runningCalls[0]?.step).toBe(1)
  })

  it('keeps the landed rows and annotations of the input snapshot', () => {
    const snapshot = snapshotOf(TURN_1)
    const spliced = spliceLiveSnapshot(
      snapshot,
      live(envelope('assistant.text.delta', { content: 'x' })),
    )
    expect(spliced.eventNodes).toBe(snapshot.eventNodes)
    expect(spliced.requests).toBe(snapshot.requests)
    expect(spliced.annotations).toBe(snapshot.annotations)
  })

  it('does not replay a response already in the initial history snapshot', () => {
    const snapshot = snapshotOf(TURN_1)
    const spliced = spliceLiveSnapshot(snapshot, live(
      envelope('assistant.text.delta', { response_id: 'r1', content: 'done' }),
      envelope('assistant.text.end', { response_id: 'r1', stop_reason: 'end_turn' }),
    ))
    expect(spliced).toBe(snapshot)
  })

  it.each([true, false])('deduplicates replayed tools with response ids: %s', (withResponseId) => {
    const rows = [
      ...TURN_1.slice(0, 1),
      row(1, 'AssistantMessage', {
        created_at: stamp(20),
        ...(withResponseId ? { response_id: 'r1' } : {}),
        parts: [
          { type: 'text', text: 'reading' },
          { type: 'tool_call', call_id: 'c1', tool_name: 'Read', arguments_json: '{}' },
          { type: 'tool_call', call_id: 'c2', tool_name: 'Bash', arguments_json: '{}' },
        ],
      }),
      row(2, 'ToolResultMessage', {
        call_id: 'c1', tool_name: 'Read', status: 'success', output_text: 'ok',
      }),
    ]
    const replayed = live(
      envelope('assistant.text.delta', { response_id: 'r1', content: 'reading' }),
      envelope('tool.call', { response_id: 'r1', tool_call_id: 'c1', tool_name: 'Read', arguments: '{}' }),
      envelope('tool.call', { response_id: 'r1', tool_call_id: 'c2', tool_name: 'Bash', arguments: '{}' }),
    )
    const beforeResult = spliceLiveSnapshot(snapshotOf(rows.slice(0, 2)), replayed)
    expect(beforeResult.partial).toBeNull()
    expect(beforeResult.runningCalls.map(call => call.callId)).toEqual(['c1', 'c2'])

    const snapshot = snapshotOf(rows)
    const spliced = spliceLiveSnapshot(snapshot, replayed)
    expect(spliced.partial).toBeNull()
    expect(spliced.runningCalls.map(call => call.callId)).toEqual(['c2'])
    expect(spliced.runningCalls[0]?.step).toBe(1)
    expect(spliced.eventNodes).toBe(snapshot.eventNodes)

    const next = reduceLiveFrames(replayed, parseLiveFrames([
      envelope('step.start', {}),
      envelope('assistant.text.delta', { response_id: 'r2', content: 'next response' }),
    ]))
    expect(spliceLiveSnapshot(snapshot, next).partial?.blocks).toEqual([
      { kind: 'text', text: 'next response' },
    ])
  })

  it('preserves a new anonymous response even when old assistants lack response ids', () => {
    const snapshot = snapshotOf([
      row(0, 'AssistantMessage', { parts: [{ type: 'text', text: 'old' }] }),
    ])
    expect(spliceLiveSnapshot(snapshot, live(
      envelope('assistant.text.delta', { content: 'new' }),
    )).partial?.blocks).toEqual([{ kind: 'text', text: 'new' }])
  })
})

describe('streaming stop reason', () => {
  it('adds no request while the response is still open', () => {
    const snapshot = snapshotOf(TURN_1)
    const state = live(envelope('assistant.text.delta', { response_id: 'r2', content: 'wo' }))
    expect(spliceLiveSnapshot(snapshot, state).requests).toEqual(snapshot.requests)
  })

  it('surfaces an error stop reason as a failed request on the streaming step', () => {
    const snapshot = snapshotOf(TURN_1)
    const state = live(
      envelope('assistant.text.delta', { response_id: 'r2', content: 'wo' }),
      envelope('assistant.text.end', { response_id: 'r2', stop_reason: 'error' }),
    )
    const spliced = spliceLiveSnapshot(snapshot, state)
    expect(spliced.requests).toHaveLength(snapshot.requests.length + 1)
    const streaming = spliced.requests[spliced.requests.length - 1]
    expect(streaming?.purpose).toBe('assistant')
    expect(streaming?.status).toBe('error')
    // The step after the newest landed one, i.e. the partial's own step.
    expect(streaming?.purpose === 'assistant' ? streaming.step : null).toBe(2)
    // The in-flight request is always the newest, so it sorts past every line.
    expect(streaming?.startSeq).toBe(Number.MAX_SAFE_INTEGER)
  })

  it('reports an ordinary stop reason as a completed request', () => {
    const state = live(
      envelope('assistant.text.delta', { response_id: 'r2', content: 'wo' }),
      envelope('assistant.text.end', { response_id: 'r2', stop_reason: 'end_turn' }),
    )
    const spliced = spliceLiveSnapshot(snapshotOf(TURN_1), state)
    expect(spliced.requests[spliced.requests.length - 1]?.status).toBe('complete')
  })
})
