/**
 * `LLMRequestEntry` -> request dots.
 *
 * Three things are pinned here: the join is by `request_id` and never by
 * position, every recorded call ends up numbered and anchored on a row that can
 * carry its dot, and a session written before the entry existed still renders
 * exactly what it used to (unknown, never zero).
 */

import { describe, expect, it } from 'vitest'
import { applyTrajectoryAnnotations } from './annotate.ts'
import { buildTrajectorySnapshot } from './snapshot.ts'
import { numbered, row, stamp, stampMs } from './fixtures.ts'
import type { HistoryRow } from './wire.ts'
import { requestSeq } from './seq.ts'
import { deriveTrajectoryLayout } from '../trajectory/layout.ts'
import type { TrajectoryCellProps } from '../trajectory/trajectory-record.ts'
import type { TrajectorySnapshot } from '../trajectory/trajectory-contract.ts'
import type { RequestView } from '../contract/index.ts'
import { t } from '../locale.ts'

const SESSION = 'sess-m4'

function snapshotOf(rows: readonly HistoryRow[]): TrajectorySnapshot {
  return buildTrajectorySnapshot(rows, { sessionId: SESSION })
}

interface LaidRow {
  readonly turn: number | null
  readonly group: string
  readonly cell: TrajectoryCellProps
}

function laidRows(snapshot: TrajectorySnapshot): readonly LaidRow[] {
  const turns = applyTrajectoryAnnotations(deriveTrajectoryLayout({
    nodes: snapshot.eventNodes,
    eventLocations: snapshot.eventLocations,
    partial: null,
    runningCalls: [],
    requests: snapshot.requests,
    callSchemas: snapshot.callSchemas,
  }, t), snapshot.annotations)
  return turns.flatMap(turn => turn.groups.flatMap(group =>
    group.cells.map(cell => ({ turn: turn.turn, group: group.title, cell }))))
}

/** `TrajectoryTable.requestKey`, with a printable separator. */
function requestKey(turn: number | null, group: string): string {
  return `${turn} :: ${group}`
}

/** The group title `TrajectoryView` derives for one request. */
function groupOf(request: RequestView): string {
  return request.purpose === 'compaction'
    ? t('group.compaction', { seq: request.startSeq })
    : t('group.step', { step: request.step })
}

/**
 * `TrajectoryTable.indexRequestBoundaries`: the record each dot rides on.
 * A request whose group holds no eligible record would render no dot at all.
 */
function dotAnchors(snapshot: TrajectorySnapshot): ReadonlyMap<string, LaidRow> {
  const rows = laidRows(snapshot)
  const wanted = new Set(snapshot.requests.map(request =>
    requestKey(request.turn, groupOf(request))))
  const anchors = new Map<string, LaidRow>()
  for (const entry of rows) {
    const key = requestKey(entry.turn, entry.group)
    if (!wanted.has(key) || anchors.has(key)) continue
    if (entry.cell.kind === 'user' || entry.cell.kind === 'context') continue
    anchors.set(key, entry)
  }
  return anchors
}

/** Every request has a dot, and the dots are numbered in wire order. */
function expectEveryRequestDotted(snapshot: TrajectorySnapshot): void {
  const anchors = dotAnchors(snapshot)
  for (const request of snapshot.requests) {
    expect(anchors.get(requestKey(request.turn, groupOf(request))), groupOf(request))
      .toBeDefined()
  }
  const seqs = snapshot.requests.map(request => request.startSeq)
  expect([...seqs].sort((left, right) => left - right)).toEqual(seqs)
}

const OPTIONS = {
  model_id: 'claude-fable-5',
  temperature: 0.25,
  max_tokens: 4096,
  effort: 'high',
  fast_mode: false,
  supports_vision: true,
}

function llmRequest(
  line: number,
  turnIndex: number,
  fields: Record<string, unknown> = {},
): HistoryRow {
  return numbered(row(line, 'LLMRequestEntry', {
    request_id: 'r-primary',
    kind: 'compaction',
    label: 'fork',
    provider: 'anthropic',
    model: 'claude-fable-5',
    options: OPTIONS,
    status: 'completed',
    started_at: stamp(1_000),
    first_token_at: stamp(1_400),
    completed_at: stamp(2_600),
    tool_call_count: 0,
    created_at: stamp(2_600),
    ...fields,
  }, 'sidecar'), turnIndex)
}

const PROLOGUE: readonly HistoryRow[] = [
  numbered(row(0, 'UserMessage', {
    created_at: stamp(0),
    role: 'user',
    parts: [{ type: 'text', text: 'compact please' }],
  }), 1),
  numbered(row(1, 'AssistantMessage', {
    created_at: stamp(900),
    response_id: 'resp_1',
    parts: [{ type: 'text', text: 'ok' }],
    stop_reason: 'end_turn',
  }), 1, 1),
]

function compactionRow(line: number, fields: Record<string, unknown> = {}): HistoryRow {
  return numbered(row(line, 'CompactionEntry', {
    created_at: stamp(2_700),
    summary: 'we read the readme',
    first_kept_index: 4,
    tokens_before: 20_000,
    ...fields,
  }), 1)
}

describe('compaction', () => {
  it('joins the primary call onto the COMPACT row and adds no dot of its own', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1),
      compactionRow(3, { request_id: 'r-primary' }),
    ])
    // assistant step + compaction; the entry did not become a request of its own
    expect(snapshot.requests).toHaveLength(2)
    const compaction = snapshot.requests[1]
    expect(compaction?.purpose).toBe('compaction')
    expect(compaction?.provenance).toEqual({ provider: 'anthropic', model: 'claude-fable-5' })
    expect(compaction?.startedAt).toBe(stampMs(1_000))
    expect(compaction?.completedAt).toBe(stampMs(2_600))
    expect(compaction?.timing).toEqual({
      stepStartTime: stampMs(1_000),
      firstTokenTime: stampMs(1_400),
      completedTime: stampMs(2_600),
    })
    expect(compaction?.requestConfig).toEqual({
      provider: 'anthropic',
      model: 'claude-fable-5',
      purpose: 'compaction · fork',
      reasoningEffort: 'high',
      temperature: 0.25,
      maxTokens: 4096,
    })
    expectEveryRequestDotted(snapshot)
  })

  it('keeps a non-primary sub-call as its own dot beside the COMPACT row', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, { request_id: 'r-summary', label: 'summary' }),
      llmRequest(3, 1, { request_id: 'r-prefix', label: 'task_prefix' }),
      compactionRow(4, { request_id: 'r-summary' }),
    ])
    expect(snapshot.requests).toHaveLength(3)
    const [, subCall, compaction] = snapshot.requests
    expect(subCall?.purpose).toBe('assistant')
    expect(subCall?.startSeq).toBe(requestSeq(3))
    expect(compaction?.purpose).toBe('compaction')
    expectEveryRequestDotted(snapshot)

    // The dot-only row sits immediately before the COMPACT row, which is what
    // fans the two dots out sideways instead of stacking them on one anchor.
    const rows = laidRows(snapshot)
    const compactedAt = rows.findIndex(entry => entry.cell.kind === 'compacted')
    expect(rows[compactedAt - 1]?.cell.requestOnly).toBe(true)
  })

  it('joins by request_id, not by the entry that happens to be adjacent', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, { request_id: 'r-summary', label: 'summary' }),
      llmRequest(3, 1, { request_id: 'r-prefix', label: 'task_prefix', model: 'haiku-mini' }),
      compactionRow(4, { request_id: 'r-summary' }),
    ])
    const compaction = snapshot.requests.find(request => request.purpose === 'compaction')
    // The adjacent line is `task_prefix`; the id points at `summary`.
    expect(compaction?.provenance?.model).toBe('claude-fable-5')
    expect(compaction?.requestConfig?.purpose).toBe('compaction · summary')
  })

  it('leaves an unlinked compaction exactly as it was before the entry existed', () => {
    const snapshot = snapshotOf([...PROLOGUE, compactionRow(2)])
    const compaction = snapshot.requests[1]
    expect(compaction?.purpose).toBe('compaction')
    expect(compaction?.startedAt).toBe(stampMs(2_700))
    // A zero-length request, not a pending one, and nothing invented.
    expect(compaction?.completedAt).toBe(stampMs(2_700))
    expect(compaction?.usage).toBeUndefined()
    expect(compaction?.requestConfig).toBeUndefined()
    expect(compaction?.timing).toBeUndefined()
    expect(compaction?.provenance).toBeUndefined()
  })
})

describe('side question and fork', () => {
  it('gives the BTW row a dot carrying the recorded call', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, {
        request_id: 'r-btw',
        kind: 'side_question',
        label: 'fork',
        usage: {
          input_tokens: 1_200,
          cached_tokens: 800,
          cache_write_tokens: 100,
          reasoning_tokens: 120,
          output_tokens: 300,
        },
      }),
      numbered(row(3, 'SideQuestionEntry', {
        created_at: stamp(2_800),
        question: 'what is the build command?',
        answer: 'pnpm build',
        request_id: 'r-btw',
      }), 1),
    ])
    expect(snapshot.requests).toHaveLength(2)
    const btw = snapshot.requests[1]
    expect(btw?.purpose).toBe('assistant')
    expect(btw?.startSeq).toBe(requestSeq(2))
    expect(btw?.status).toBe('complete')
    expect(btw?.usage).toEqual({
      inputTokens: 300,
      cacheReadTokens: 800,
      cacheWriteTokens: 100,
      outputTokens: 300,
      reasoningTokens: 120,
    })
    expectEveryRequestDotted(snapshot)

    const rows = laidRows(snapshot)
    const btwAt = rows.findIndex(entry => entry.cell.kind === 'btw')
    expect(btwAt).toBeGreaterThan(0)
    expect(rows[btwAt - 1]?.cell.requestOnly).toBe(true)
  })

  it('gives the fork summary row a dot in the new session', () => {
    const snapshot = snapshotOf([
      numbered(row(0, 'LLMRequestEntry', {
        request_id: 'r-fork',
        kind: 'fork',
        label: 'fork',
        provider: 'anthropic',
        model: 'claude-fable-5',
        status: 'completed',
        started_at: stamp(0),
        completed_at: stamp(1_500),
        created_at: stamp(1_500),
      }, 'sidecar'), 0),
      numbered(row(1, 'ForkSummaryEntry', {
        created_at: stamp(1_600),
        summary: 'the tail we discarded',
        source_session_id: 'older',
        source_pivot_index: 3,
        source_message_count: 8,
        request_id: 'r-fork',
      }), 0),
      numbered(row(2, 'AssistantMessage', {
        created_at: stamp(3_000),
        response_id: 'resp_f',
        parts: [{ type: 'text', text: 'carrying on' }],
      }), 1, 1),
    ])
    const fork = snapshot.requests[0]
    expect(fork?.startSeq).toBe(requestSeq(0))
    // Turn 0 folds into Turn 1, and the dot's identity has to fold with it.
    expect(fork?.turn).toBe(1)
    // No streaming delta was recorded, so there is no TTFT to report.
    expect(fork?.timing).toEqual({
      stepStartTime: stampMs(0),
      firstTokenTime: null,
      completedTime: stampMs(1_500),
    })
    expectEveryRequestDotted(snapshot)

    const rows = laidRows(snapshot)
    expect(rows[0]?.cell.requestOnly).toBe(true)
    expect(rows[1]?.cell.kind).toBe('user')
  })
})

describe('failed calls', () => {
  it('renders a dot with no row and carries the error', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, {
        request_id: 'r-dead',
        status: 'error',
        error: 'context window exceeded',
      }),
    ])
    expect(snapshot.requests).toHaveLength(2)
    const failed = snapshot.requests[1]
    expect(failed?.status).toBe('error')
    expect(failed?.error).toBe('context window exceeded')
    expect(failed?.usage).toBeUndefined()
    expectEveryRequestDotted(snapshot)

    const rows = laidRows(snapshot)
    const dot = rows.find(entry => entry.cell.requestOnly === true)
    expect(dot?.cell.isError).toBe(true)
    // A dot, never a row: nothing visible was added to the ledger.
    expect(rows.filter(entry => entry.cell.requestOnly !== true)).toHaveLength(2)
  })

  it('names an interrupt that carried no message of its own', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, { request_id: 'r-cut', status: 'interrupted' }),
    ])
    expect(snapshot.requests[1]?.status).toBe('error')
    expect(snapshot.requests[1]?.error).toBe('Interrupted')
  })

  it('ignores an entry with no request_id to join on', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      numbered(row(2, 'LLMRequestEntry', {
        kind: 'compaction',
        status: 'completed',
        created_at: stamp(1_000),
      }, 'sidecar'), 1),
    ])
    expect(snapshot.requests).toHaveLength(1)
  })
})

describe('options', () => {
  it('hides the Options tab when the call recorded none', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, { request_id: 'r-old', options: undefined }),
    ])
    // Provider and model are still known; only the knobs are not.
    expect(snapshot.requests[1]?.provenance)
      .toEqual({ provider: 'anthropic', model: 'claude-fable-5' })
    expect(snapshot.requests[1]?.requestConfig).toBeUndefined()
  })

  it('prefers the thinking effort over the plain one', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, {
        request_id: 'r-think',
        options: { ...OPTIONS, thinking: { type: 'enabled', reasoning_effort: 'max' } },
      }),
    ])
    const config = snapshot.requests[1]?.requestConfig
    expect(config?.reasoningEffort).toBe('max')
    expect(config?.thinking).toBe('{"type":"enabled","reasoning_effort":"max"}')
  })
})

describe('numbering', () => {
  it('orders every kind of dot chronologically', () => {
    const snapshot = snapshotOf([
      ...PROLOGUE,
      llmRequest(2, 1, { request_id: 'r-btw', kind: 'side_question' }),
      numbered(row(3, 'SideQuestionEntry', {
        created_at: stamp(2_800),
        question: 'q',
        answer: 'a',
        request_id: 'r-btw',
      }), 1),
      numbered(row(4, 'AssistantMessage', {
        created_at: stamp(3_400),
        response_id: 'resp_2',
        parts: [{ type: 'text', text: 'more' }],
      }), 1, 2),
      llmRequest(5, 1, { request_id: 'r-sum', label: 'summary' }),
      llmRequest(6, 1, { request_id: 'r-pre', label: 'task_prefix' }),
      compactionRow(7, { request_id: 'r-sum' }),
    ])
    // step 1, /btw, step 2, the orphaned task_prefix, compaction
    expect(snapshot.requests.map(request => request.startSeq)).toEqual([
      requestSeq(1), requestSeq(2), requestSeq(4), requestSeq(6), requestSeq(7),
    ])
    expectEveryRequestDotted(snapshot)
  })
})
