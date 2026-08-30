import { describe, expect, it } from 'vitest'
import { applyTrajectoryAnnotations } from './annotate.ts'
import { buildTrajectorySnapshot } from './snapshot.ts'
import { numbered, row, stamp, stampMs, usage } from './fixtures.ts'
import { EMPTY_RESPONSE_CONTINUATION_PROMPT } from './classify.ts'
import type { HistoryRow } from './wire.ts'
import { nodeSeq } from './seq.ts'
import { deriveTrajectoryLayout } from '../trajectory/layout.ts'
import { trajectoryRecordId } from '../trajectory/trajectory-record.ts'
import type { TrajectoryCellProps } from '../trajectory/trajectory-record.ts'
import type { TrajectorySnapshot } from '../trajectory/trajectory-contract.ts'
import { t } from '../locale.ts'

const SESSION = 'sess1'

function snapshotOf(rows: readonly HistoryRow[]): TrajectorySnapshot {
  return buildTrajectorySnapshot(rows, { sessionId: SESSION })
}

interface LaidRow {
  readonly turn: number | null
  readonly group: string
  readonly cell: TrajectoryCellProps
}

/** Fold a snapshot exactly the way `TrajectoryView` does. */
function laidRows(snapshot: TrajectorySnapshot): readonly LaidRow[] {
  const turns = applyTrajectoryAnnotations(
    deriveTrajectoryLayout({
      nodes: snapshot.eventNodes,
      eventLocations: snapshot.eventLocations,
      partial: null,
      runningCalls: [],
      requests: snapshot.requests,
      callSchemas: snapshot.callSchemas,
    }, t),
    snapshot.annotations,
  )
  return turns.flatMap(turn => turn.groups.flatMap(group =>
    group.cells.map(cell => ({ turn: turn.turn, group: group.title, cell }))))
}

function kinds(rows: readonly LaidRow[]): readonly string[] {
  return rows.map(entry => entry.cell.kind)
}

const PLAIN_TURN: readonly HistoryRow[] = [
  row(0, 'UserMessage', {
    created_at: stamp(0),
    role: 'user',
    parts: [{ type: 'text', text: 'read the readme' }],
  }),
  row(1, 'AssistantMessage', {
    created_at: stamp(3_000),
    response_id: 'resp_1',
    parts: [
      { type: 'thinking_text', text: 'the readme is the fastest source' },
      { type: 'text', text: 'Reading it now.' },
      {
        type: 'tool_call',
        call_id: 'call_1',
        tool_name: 'Read',
        arguments_json: '{"file_path":"/repo/README.md"}',
      },
    ],
    usage: usage({ created_at: stamp(500), first_token_latency_ms: 700 }),
    stop_reason: 'tool_use',
  }),
  row(2, 'ToolResultMessage', {
    created_at: stamp(4_000),
    call_id: 'call_1',
    tool_name: 'Read',
    status: 'success',
    output_text: '# klaude',
    parts: [],
  }),
  row(3, 'AssistantMessage', {
    created_at: stamp(6_000),
    parts: [{ type: 'text', text: 'It is a coding agent.' }],
    usage: usage({ created_at: stamp(5_000) }),
    stop_reason: 'stop',
  }),
]

describe('plain turn', () => {
  const snapshot = snapshotOf(PLAIN_TURN)

  it('projects one row per model-visible entry', () => {
    expect(snapshot.eventNodes.map(node => node.kind))
      .toEqual(['user', 'assistant', 'tool-result', 'assistant'])
    const rows = laidRows(snapshot)
    expect(kinds(rows)).toEqual(['user', 'message', 'tool', 'message'])
    expect(rows.every(entry => entry.turn === 1)).toBe(true)
    expect(rows.map(entry => entry.group))
      .toEqual([t('group.message'), t('group.step', { step: 1 }), t('group.step', { step: 1 }), t('group.step', { step: 2 })])
  })

  it('pairs the tool result with its call and keeps the call time', () => {
    const tool = laidRows(snapshot).find(entry => entry.cell.kind === 'tool')
    expect(tool?.cell.text).toBe('Read')
    expect(tool?.cell.callId).toBe('call_1')
    expect(tool?.cell.resultPreviewMarkdown).toBe('# klaude')
    // call -> result duration comes from the assistant message's created_at.
    expect(tool?.cell.startedAt).toBe(stampMs(3_000))
    expect(tool?.cell.timeSeconds).toBe(1)
  })

  it('numbers turns by human user messages and steps by assistant order', () => {
    const assistants = snapshot.eventNodes.flatMap(node =>
      node.kind === 'assistant' ? [{ turn: node.turn, step: node.step }] : [])
    expect(assistants).toEqual([{ turn: 1, step: 1 }, { turn: 1, step: 2 }])
    expect(snapshot.eventLocations.get(9)).toEqual({ kind: 'step', turn: { turn: 1 }, step: { step: 1 } })
    expect(snapshot.eventLocations.get(1)).toEqual({ kind: 'turn', turn: { turn: 1 } })
  })

  it('emits one request per assistant message, anchored before its node', () => {
    expect(snapshot.requests).toHaveLength(2)
    const [first, second] = snapshot.requests
    expect(first?.purpose).toBe('assistant')
    expect(first?.startSeq).toBe(8)
    expect(first?.startedAt).toBe(stampMs(500))
    expect(first?.completedAt).toBe(stampMs(3_000))
    expect(first?.status).toBe('complete')
    expect(first?.provenance).toEqual({ provider: 'anthropic', model: 'claude-fable-5' })
    expect(second?.startSeq).toBe(24)
  })

  it('orders request headers between the surrounding nodes', () => {
    const nodeSeqs = snapshot.eventNodes.map(node => node.seq)
    expect(nodeSeqs).toEqual([1, 9, 17, 25])
    for (const request of snapshot.requests) {
      const owner = nodeSeqs.indexOf(request.startSeq + 1)
      expect(owner).toBeGreaterThan(0)
      // The header sorts after the previous node and before its own.
      expect(request.startSeq).toBeGreaterThan(nodeSeqs[owner - 1] ?? -1)
      expect(request.startSeq).toBeLessThan(nodeSeqs[owner] ?? -1)
    }
  })

  it('carries recorded timing onto the assistant record', () => {
    const message = laidRows(snapshot).find(entry => entry.cell.kind === 'message')
    expect(message?.cell.assistantMetrics).toEqual({
      timingRecorded: true,
      stepStartTime: stampMs(500),
      firstTokenTime: stampMs(1_200),
      completedTime: stampMs(3_000),
      usageProvided: true,
      outputTokens: 100,
    })
    expect(message?.cell.startedAt).toBe(stampMs(500))
    expect(message?.cell.timeSeconds).toBe(2.5)
  })

  it('stamps every record with the line it came from', () => {
    expect(laidRows(snapshot).map(entry => entry.cell.lineIndex)).toEqual([0, 1, 2, 3])
  })

  it('keeps the raw entry as the record source', () => {
    const user = laidRows(snapshot)[0]
    expect(user?.cell.messageSource).toEqual(PLAIN_TURN[0]?.entry)
  })
})

describe('discarded rows', () => {
  it('greys a retracted user row and keeps it in place', () => {
    const rows = laidRows(snapshotOf([
      ...PLAIN_TURN,
      row(4, 'UserMessage', {
        created_at: stamp(7_000),
        role: 'user',
        parts: [{ type: 'text', text: 'oops' }],
      }, 'retracted', 5),
      row(5, 'RetractEntry', { retracted_text: 'oops', retracted_line: 4, created_at: stamp(7_100) }),
    ]))
    const retracted = rows.filter(entry => entry.cell.discarded !== undefined)
    expect(retracted).toHaveLength(1)
    expect(retracted[0]?.cell.kind).toBe('user')
    expect(retracted[0]?.cell.discarded).toEqual({ status: 'retracted', droppedBy: 5 })
    // The RetractEntry itself takes no row.
    expect(kinds(rows)).toEqual(['user', 'message', 'tool', 'message', 'user'])
  })

  it('marks a compacted prefix and adds the COMPACT row with its own request', () => {
    const compacted = PLAIN_TURN.map(entry => ({ ...entry, status: 'compacted' as const, dropped_by: 4 }))
    const snapshot = snapshotOf([
      ...compacted,
      row(4, 'CompactionEntry', {
        summary: '## Goal\nread the readme',
        first_kept_index: 4,
        first_kept_line: 5,
        tokens_before: 120_000,
        created_at: stamp(8_000),
      }),
      row(5, 'UserMessage', {
        created_at: stamp(9_000),
        role: 'user',
        parts: [{ type: 'text', text: 'carry on' }],
      }),
    ])
    const rows = laidRows(snapshot)
    expect(kinds(rows)).toEqual(['user', 'message', 'tool', 'message', 'compacted', 'user'])
    expect(rows.slice(0, 4).every(entry => entry.cell.discarded?.status === 'compacted')).toBe(true)
    expect(rows[4]?.cell.discarded).toBeUndefined()
    expect(rows[5]?.cell.discarded).toBeUndefined()
    const compaction = snapshot.requests.find(request => request.purpose === 'compaction')
    expect(compaction?.startSeq).toBe(32)
    expect(rows[4]?.cell.sourceSeq).toBe(32)
    expect(rows[4]?.cell.previewMarkdown).toBe('## Goal\nread the readme')
  })
})

describe('klaude-only rows', () => {
  it('renders a legacy RewindEntry as a rewind row', () => {
    const rows = laidRows(snapshotOf([
      ...PLAIN_TURN,
      row(4, 'RewindEntry', {
        checkpoint_id: 1,
        note: 'reverted the echo test',
        rationale: 'user asked to demo rewind',
        reverted_from_index: 12,
        original_user_message: 'test rewind',
        created_at: stamp(7_000),
      }),
    ]))
    const rewind = rows.at(-1)
    expect(rewind?.cell.kind).toBe('rewind')
    expect(rewind?.cell.previewMarkdown).toBe('user asked to demo rewind')
    expect(rewind?.cell.inputDetail).toContain('reverted the echo test')
  })

  it('renders a side question as a btw row with its answer in the body', () => {
    const rows = laidRows(snapshotOf([
      ...PLAIN_TURN,
      row(4, 'SideQuestionEntry', {
        question: 'how far along are you?',
        answer: 'the adapter is done',
        cache_hit_rate: 0.99,
        created_at: stamp(7_000),
      }),
    ]))
    const btw = rows.at(-1)
    expect(btw?.cell.kind).toBe('btw')
    expect(btw?.cell.previewMarkdown).toBe('how far along are you?')
    expect(btw?.cell.inputDetail).toBe('how far along are you?\nthe adapter is done')
  })

  it('turns a fork summary into the opening user row', () => {
    const rows = laidRows(snapshotOf([
      row(0, 'ForkSummaryEntry', {
        summary: 'the parent session was doing X',
        source_session_id: 'parent',
        source_pivot_index: 3,
        source_message_count: 12,
        created_at: stamp(0),
      }),
      ...PLAIN_TURN.slice(1).map(entry => ({ ...entry })),
    ]))
    expect(rows[0]?.cell.kind).toBe('user')
    expect(rows[0]?.cell.previewMarkdown).toBe('the parent session was doing X')
  })
})

describe('context rows', () => {
  it('hides the legacy checkpoint reminder', () => {
    const rows = laidRows(snapshotOf([
      PLAIN_TURN[0]!,
      row(1, 'DeveloperMessage', {
        created_at: stamp(10),
        role: 'developer',
        parts: [{ type: 'text', text: '<system-reminder>Checkpoint 3</system-reminder>' }],
        attachment_position: 'append',
      }),
      row(2, 'DeveloperMessage', {
        created_at: stamp(20),
        role: 'developer',
        parts: [{ type: 'text', text: '<system-reminder>Loaded memory files.</system-reminder>' }],
        attachment_position: 'prepend',
        ui_extra: { items: [{ type: 'memory_loaded' }] },
      }),
      { ...PLAIN_TURN[1]!, line_index: 3 },
    ]))
    expect(kinds(rows)).toEqual(['user', 'context', 'message', 'tool'])
    expect(rows[1]?.cell.lineIndex).toBe(2)
  })
})

describe('non-human user rows', () => {
  const rows = laidRows(snapshotOf([
    row(0, 'UserMessage', {
      created_at: stamp(0),
      role: 'user',
      parts: [{ type: 'text', text: 'do the thing' }],
    }),
    row(1, 'UserMessage', {
      created_at: stamp(10),
      role: 'user',
      source: 'bash_mode',
      parts: [{ type: 'text', text: '!ls -la' }],
    }),
    row(2, 'UserMessage', {
      created_at: stamp(20),
      role: 'user',
      parts: [{ type: 'text', text: EMPTY_RESPONSE_CONTINUATION_PROMPT }],
    }),
    row(3, 'UserMessage', {
      created_at: stamp(30),
      role: 'user',
      parts: [{
        type: 'text',
        text: '<assistant>\nhalf a sentence\n</assistant>\n\n<system-reminder>'
          + 'Your previous response was interrupted due to a transient error '
          + '(often network-related). Please continue.</system-reminder>',
      }],
    }),
    row(4, 'UserMessage', {
      created_at: stamp(40),
      role: 'user',
      parts: [{
        type: 'text',
        text: '<system-reminder>You are no longer the main coding agent. '
          + 'You are now acting as a specialized sub-agent.</system-reminder>',
      }],
    }),
    row(5, 'AssistantMessage', {
      created_at: stamp(50),
      parts: [{ type: 'text', text: 'ok' }],
      usage: usage({ created_at: stamp(45) }),
      stop_reason: 'stop',
    }),
  ]))

  it('tags every machine-written user row', () => {
    expect(rows.map(entry => entry.cell.auto)).toEqual([undefined, true, true, true, true, undefined])
  })

  it('does not let a synthesized prompt open a new turn', () => {
    expect(rows.every(entry => entry.turn === 1)).toBe(true)
  })
})

describe('sub-agent links', () => {
  it('attaches the spawned session to the Agent tool row', () => {
    const rows = laidRows(snapshotOf([
      PLAIN_TURN[0]!,
      row(1, 'AssistantMessage', {
        created_at: stamp(3_000),
        parts: [
          { type: 'tool_call', call_id: 'call_a', tool_name: 'Agent', arguments_json: '{"desc":"review"}' },
          { type: 'tool_call', call_id: 'call_b', tool_name: 'Agent', arguments_json: '{"desc":"find"}' },
        ],
        usage: usage({ created_at: stamp(2_000) }),
        stop_reason: 'tool_use',
      }),
      row(2, 'SpawnSubAgentEntry', {
        session_id: 'child_a',
        sub_agent_type: 'code-reviewer',
        sub_agent_desc: 'review',
        created_at: stamp(3_100),
      }),
      row(3, 'SpawnSubAgentEntry', {
        session_id: 'child_b',
        sub_agent_type: 'finder',
        sub_agent_desc: 'find',
        created_at: stamp(3_200),
      }),
      row(4, 'ToolResultMessage', {
        created_at: stamp(9_000),
        call_id: 'call_a',
        tool_name: 'Agent',
        status: 'success',
        output_text: 'reviewed',
        parts: [],
      }),
    ]))
    const tools = rows.filter(entry => entry.cell.kind === 'tool')
    expect(tools.map(entry => entry.cell.subAgent?.sessionId)).toEqual(['child_a', 'child_b'])
    expect(tools[0]?.cell.subAgent).toEqual({
      sessionId: 'child_a',
      type: 'code-reviewer',
      desc: 'review',
    })
  })
})

describe('sidecars', () => {
  it('folds an interrupt into the preceding request status', () => {
    const snapshot = snapshotOf([
      ...PLAIN_TURN,
      row(4, 'InterruptEntry', { show_notice: true, created_at: stamp(6_500) }),
    ])
    expect(snapshot.requests.at(-1)?.status).toBe('error')
    expect(snapshot.requests.at(-1)?.error).toBe('Interrupted')
    expect(snapshot.requests[0]?.status).toBe('complete')
  })

  it('folds a stream error into the request that produced it', () => {
    const snapshot = snapshotOf([
      ...PLAIN_TURN,
      row(4, 'StreamErrorItem', { error: 'APIStatusError upstream lost', created_at: stamp(6_500) }),
    ])
    expect(snapshot.requests.at(-1)?.error).toBe('APIStatusError upstream lost')
  })

  it('folds a cache-hit entry into the request it precedes', () => {
    const snapshot = snapshotOf([
      PLAIN_TURN[0]!,
      row(1, 'CacheHitRateEntry', {
        cache_hit_rate: 0.97,
        cached_tokens: 800,
        prev_step_input_tokens: 900,
        created_at: stamp(2_900),
      }),
      row(2, 'AssistantMessage', {
        created_at: stamp(3_000),
        parts: [{ type: 'text', text: 'hi' }],
        usage: usage({ input_tokens: 1_000, cached_tokens: 0, created_at: stamp(2_500) }),
        stop_reason: 'stop',
      }),
    ])
    expect(snapshot.requests[0]?.usage).toEqual({
      inputTokens: 200,
      cacheReadTokens: 800,
      outputTokens: 100,
    })
  })

  it('takes no row for the remaining sidecars', () => {
    const rows = laidRows(snapshotOf([
      PLAIN_TURN[0]!,
      row(1, 'TaskMetadataItem', { created_at: stamp(10) }),
      row(2, 'PromptSuggestionEntry', { text: 'next?', created_at: stamp(20) }),
      row(3, 'AwaySummaryEntry', { text: 'recap', source: 'auto', created_at: stamp(30) }),
      row(4, 'TaskFileChangeSummaryEntry', { files: [], created_at: stamp(40) }),
      row(5, 'FallbackModelConfigWarnEntry', {
        from_model: 'a', to_model: 'b', reason: 'quota', created_at: stamp(50),
      }),
      row(6, 'SomeFutureEntry', { created_at: stamp(60) }),
      { ...PLAIN_TURN[1]!, line_index: 7 },
    ]))
    expect(kinds(rows)).toEqual(['user', 'message', 'tool'])
  })
})

describe('images', () => {
  it('routes recorded paths through the file endpoint and URLs straight through', () => {
    const snapshot = snapshotOf([
      row(0, 'UserMessage', {
        created_at: stamp(0),
        role: 'user',
        parts: [
          { type: 'text', text: 'look at this' },
          { type: 'image_file', file_path: '/tmp/klaude-image-1.png', mime_type: 'image/png', byte_size: 42 },
          { type: 'image_url', url: 'data:image/jpeg;base64,AAAA' },
        ],
      }),
    ])
    const user = snapshot.eventNodes[0]
    expect(user?.kind).toBe('user')
    const blocks = user?.kind === 'user' ? user.content : []
    expect(blocks.map(block => block.type)).toEqual(['text', 'image', 'image'])
    const first = blocks[1]
    expect(first?.type === 'image' && first.attachment.attachmentId)
      .toBe('/api/web/file?session_id=sess1&path=%2Ftmp%2Fklaude-image-1.png')
    expect(first?.type === 'image' && first.attachment.mediaType).toBe('image/png')
    const second = blocks[2]
    expect(second?.type === 'image' && second.attachment.attachmentId).toBe('data:image/jpeg;base64,AAAA')
    expect(second?.type === 'image' && second.attachment.mediaType).toBe('image/jpeg')
  })
})

describe('failed tool results', () => {
  it('summarizes the error headline on the row', () => {
    const rows = laidRows(snapshotOf([
      PLAIN_TURN[0]!,
      PLAIN_TURN[1]!,
      row(2, 'ToolResultMessage', {
        created_at: stamp(4_000),
        call_id: 'call_1',
        tool_name: 'Read',
        status: 'error',
        output_text: 'File not found: /repo/README.md\nstack trace…',
        parts: [],
      }),
    ]))
    const tool = rows.find(entry => entry.cell.kind === 'tool')
    expect(tool?.cell.isError).toBe(true)
    expect(tool?.cell.result).toBe('File not found: /repo/README.md')
  })
})

describe('older page prepend', () => {
  it('keeps record identities stable when earlier rows arrive', () => {
    const tail = PLAIN_TURN.map(entry => ({ ...entry, line_index: entry.line_index + 4 }))
    const older: readonly HistoryRow[] = [
      row(0, 'UserMessage', {
        created_at: stamp(-5_000),
        role: 'user',
        parts: [{ type: 'text', text: 'an earlier question' }],
      }),
      row(1, 'AssistantMessage', {
        created_at: stamp(-4_000),
        parts: [{ type: 'text', text: 'an earlier answer' }],
        usage: usage({ created_at: stamp(-4_500) }),
        stop_reason: 'stop',
      }),
      row(2, 'UserMessage', {
        created_at: stamp(-3_000),
        role: 'user',
        parts: [{ type: 'text', text: 'another earlier question' }],
      }),
      row(3, 'AssistantMessage', {
        created_at: stamp(-2_000),
        parts: [{ type: 'text', text: 'another earlier answer' }],
        usage: usage({ created_at: stamp(-2_500) }),
        stop_reason: 'stop',
      }),
    ]
    const before = laidRows(snapshotOf(tail)).map(entry => trajectoryRecordId(entry.cell))
    const after = laidRows(snapshotOf([...older, ...tail])).map(entry => trajectoryRecordId(entry.cell))
    expect(after.slice(-before.length)).toEqual(before)
    // The prepended page is the only thing that grew.
    expect(after).toHaveLength(before.length + 4)
  })
})

describe('turn ordinals', () => {
  /** `PLAIN_TURN`, numbered by the server as the fifth turn of a long session. */
  const NUMBERED_TURN: readonly HistoryRow[] = [
    numbered(PLAIN_TURN[0]!, 5, null, false),
    numbered(PLAIN_TURN[1]!, 5, 1),
    numbered(PLAIN_TURN[2]!, 5),
    numbered(PLAIN_TURN[3]!, 5, 2),
  ]

  it('prefers the server ordinals over counting inside the window', () => {
    const snapshot = snapshotOf(NUMBERED_TURN)
    const assistants = snapshot.eventNodes.flatMap(node =>
      node.kind === 'assistant' ? [{ turn: node.turn, step: node.step }] : [])
    expect(assistants).toEqual([{ turn: 5, step: 1 }, { turn: 5, step: 2 }])
    expect(snapshot.eventLocations.get(1)).toEqual({ kind: 'turn', turn: { turn: 5 } })
    expect(snapshot.requests.map(request => [request.turn, request.step])).toEqual([[5, 1], [5, 2]])
    expect(laidRows(snapshot).every(entry => entry.turn === 5)).toBe(true)
  })

  it('falls back to window-relative numbering when the server sends none', () => {
    const snapshot = snapshotOf(PLAIN_TURN)
    const assistants = snapshot.eventNodes.flatMap(node =>
      node.kind === 'assistant' ? [{ turn: node.turn, step: node.step }] : [])
    expect(assistants).toEqual([{ turn: 1, step: 1 }, { turn: 1, step: 2 }])
    expect(laidRows(snapshot).every(entry => entry.turn === 1)).toBe(true)
  })

  /** A plain assistant answer at a caller-chosen line. */
  const answer = (lineIndex: number) => row(lineIndex, 'AssistantMessage', {
    created_at: stamp(3_000),
    parts: [{ type: 'text', text: 'ok' }],
    usage: usage({ created_at: stamp(2_500) }),
    stop_reason: 'stop',
  })

  it('trusts the server auto flag over the text heuristic', () => {
    // Text nothing in `classify.ts` recognizes, flagged auto by the server:
    // the row is tagged and does not open a turn.
    const rows = laidRows(snapshotOf([
      numbered(PLAIN_TURN[0]!, 5, null, false),
      numbered(row(1, 'UserMessage', {
        created_at: stamp(10),
        parts: [{ type: 'text', text: 'a future continuation prompt' }],
      }), 5, null, true),
      numbered(answer(2), 5, 1),
    ]))
    expect(kinds(rows)).toEqual(['user', 'user', 'message'])
    expect(rows.map(entry => entry.cell.auto)).toEqual([undefined, true, undefined])
    expect(rows.every(entry => entry.turn === 5)).toBe(true)
  })

  it('lets the server open a turn on text the heuristic would call synthetic', () => {
    const snapshot = snapshotOf([
      numbered(PLAIN_TURN[0]!, 5, null, false),
      numbered(row(1, 'UserMessage', {
        created_at: stamp(10),
        parts: [{ type: 'text', text: EMPTY_RESPONSE_CONTINUATION_PROMPT }],
      }), 6, null, false),
      numbered(answer(2), 6, 1),
    ])
    const assistant = snapshot.eventNodes.find(node => node.kind === 'assistant')
    expect(assistant?.kind === 'assistant' && assistant.turn).toBe(6)
    expect(snapshot.eventLocations.get(nodeSeq(1))).toEqual({ kind: 'turn', turn: { turn: 6 } })
  })

  it('folds the pre-first-turn prologue (turn 0) into Turn 1', () => {
    const rows = laidRows(snapshotOf([
      numbered(row(0, 'DeveloperMessage', {
        created_at: stamp(0),
        role: 'developer',
        parts: [{ type: 'text', text: 'startup context' }],
      }), 0),
      numbered(row(1, 'UserMessage', {
        created_at: stamp(10),
        parts: [{ type: 'text', text: 'read the readme' }],
      }), 1, null, false),
      numbered(answer(2), 1, 1),
    ]))
    expect(kinds(rows)).toEqual(['context', 'user', 'message'])
    expect(rows.every(entry => entry.turn === 1)).toBe(true)
  })

  it('never opens a turn on a fork summary, with or without ordinals', () => {
    const fork = (lineIndex: number) => row(lineIndex, 'ForkSummaryEntry', {
      summary: 'the parent session was doing X',
      source_session_id: 'parent',
      created_at: stamp(0),
    })
    const withOrdinals = snapshotOf([
      numbered(fork(0), 0),
      numbered(row(1, 'UserMessage', {
        created_at: stamp(10), parts: [{ type: 'text', text: 'carry on' }],
      }), 1, null, false),
    ])
    const withoutOrdinals = snapshotOf([
      fork(0),
      row(1, 'UserMessage', { created_at: stamp(10), parts: [{ type: 'text', text: 'carry on' }] }),
    ])
    for (const snapshot of [withOrdinals, withoutOrdinals]) {
      expect(snapshot.eventLocations.get(nodeSeq(1))).toEqual({ kind: 'turn', turn: { turn: 1 } })
      // The fork summary itself sits in the prologue and folds into Turn 1.
      expect(laidRows(snapshot).every(entry => entry.turn === 1)).toBe(true)
    }
  })
})
