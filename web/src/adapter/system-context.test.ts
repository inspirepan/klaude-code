/**
 * `GET .../system-context` -> the SYSTEM row and the tool Schema tab.
 *
 * klaude persists neither the prompt nor the catalogue, so both exist only
 * because the page fetched them. What is pinned here: the row appears once, at
 * the head, with the prompt and the whole catalogue behind it; every tool call
 * in the window resolves to its schema; a rebuilt answer says so; and an
 * unavailable one adds nothing at all.
 */

import { describe, expect, it } from 'vitest'
import { applyTrajectoryAnnotations } from './annotate.ts'
import { buildTrajectorySnapshot } from './snapshot.ts'
import { numbered, row, stamp, stampMs, usage } from './fixtures.ts'
import type { HistoryRow, SystemContext } from './wire.ts'
import { deriveTrajectoryLayout } from '../trajectory/layout.ts'
import type { TrajectoryCellProps } from '../trajectory/trajectory-record.ts'
import type { TrajectorySnapshot } from '../trajectory/trajectory-contract.ts'
import { t } from '../locale.ts'

const SESSION = 'sess-system'

const ROWS: readonly HistoryRow[] = [
  numbered(row(0, 'UserMessage', {
    created_at: stamp(0),
    role: 'user',
    parts: [{ type: 'text', text: 'read the readme' }],
  }), 1),
  numbered(row(1, 'AssistantMessage', {
    created_at: stamp(3_000),
    response_id: 'resp_1',
    parts: [
      { type: 'text', text: 'on it' },
      {
        type: 'tool_call',
        call_id: 'call_1',
        tool_name: 'Read',
        arguments_json: '{"file_path":"/repo/README.md"}',
      },
    ],
    usage: usage({ created_at: stamp(500) }),
    stop_reason: 'tool_use',
  }), 1, 1),
  numbered(row(2, 'ToolResultMessage', {
    created_at: stamp(4_000),
    call_id: 'call_1',
    tool_name: 'Read',
    status: 'success',
    output_text: '# klaude',
    parts: [],
  }), 1),
  // A result whose call fell outside the loaded window still names its tool.
  numbered(row(3, 'ToolResultMessage', {
    created_at: stamp(4_400),
    call_id: 'call_orphan',
    tool_name: 'Bash',
    status: 'success',
    output_text: 'ok',
    parts: [],
  }), 1),
]

const CONTEXT: SystemContext = {
  available: true,
  source: 'live',
  system_prompt: 'You are klaude.',
  tools: [
    { name: 'Read', description: 'Read a file', parameters: { type: 'object' } },
    { name: 'Bash', description: 'Run a command', parameters: { type: 'object' } },
    { name: 'Write', description: 'Write a file', parameters: { type: 'object' } },
  ],
  model: {
    provider: 'anthropic',
    model: 'claude-fable-5',
    effort: 'high',
    max_tokens: 4096,
    temperature: 0.25,
    thinking: { type: 'enabled' },
  },
  reason: null,
}

function snapshotOf(context: SystemContext | undefined): TrajectorySnapshot {
  return buildTrajectorySnapshot(ROWS, {
    sessionId: SESSION,
    systemContext: context,
    translate: t,
  })
}

function cells(snapshot: TrajectorySnapshot): readonly TrajectoryCellProps[] {
  const turns = applyTrajectoryAnnotations(deriveTrajectoryLayout({
    nodes: snapshot.eventNodes,
    eventLocations: snapshot.eventLocations,
    partial: null,
    runningCalls: [],
    requests: snapshot.requests,
    callSchemas: snapshot.callSchemas,
  }, t), snapshot.annotations)
  return turns.flatMap(turn => turn.groups.flatMap(group => group.cells))
}

describe('available', () => {
  const snapshot = snapshotOf(CONTEXT)

  it('hangs the prompt on the first ordinary request', () => {
    const anchor = snapshot.requests.find(request => request.purpose === 'assistant')
    expect(anchor?.purpose).toBe('assistant')
    if (anchor?.purpose !== 'assistant') return
    // Seq 0 is a constant, not a window position: prepending an older page
    // must not change the SYSTEM record's identity.
    expect(anchor.promptChange).toEqual({ seq: 0, time: stampMs(0), kind: 'initial' })
    expect(anchor.prompt?.system).toBe('You are klaude.')
    expect(anchor.prompt?.tools.map(tool => tool.name)).toEqual(['Read', 'Bash', 'Write'])
    expect(anchor.prompt?.config).toEqual({
      provider: 'anthropic',
      model: 'claude-fable-5',
      reasoningEffort: 'high',
      temperature: 0.25,
      maxTokens: 4096,
      thinking: '{"type":"enabled"}',
    })
  })

  it('emits one SYSTEM record, ahead of the conversation', () => {
    const laid = cells(snapshot)
    const system = laid.filter(cell => cell.kind === 'system')
    expect(system).toHaveLength(1)
    expect(laid.findIndex(cell => cell.kind === 'system'))
      .toBeLessThan(laid.findIndex(cell => cell.kind === 'user'))
    expect(system[0]?.text).toBe(t('layout.initialSystemPrompt'))
    expect(system[0]?.promptDetail?.system).toBe('You are klaude.')
    // Only one snapshot per session for now, so nothing to diff against.
    expect(system[0]?.previousPromptDetail).toBeUndefined()
  })

  it('resolves every tool call in the window to its schema', () => {
    expect([...snapshot.callSchemas.keys()].sort()).toEqual(['call_1', 'call_orphan'])
    expect(snapshot.callSchemas.get('call_1')?.name).toBe('Read')
    const tool = cells(snapshot).find(cell => cell.callId === 'call_1')
    expect(tool?.schemaDetail).toBe(JSON.stringify(
      { name: 'Read', description: 'Read a file', parameters: { type: 'object' } },
      null,
      2,
    ))
  })

  it('says nothing extra when the context was read live', () => {
    const system = cells(snapshot).find(cell => cell.kind === 'system')
    expect(system?.promptDetail?.caveat).toBeUndefined()
  })
})

describe('rebuilt', () => {
  it('carries a caveat, because it is today prompt files and not a recording', () => {
    const snapshot = snapshotOf({ ...CONTEXT, source: 'rebuilt' })
    const system = cells(snapshot).find(cell => cell.kind === 'system')
    expect(system).toBeDefined()
    expect(system?.promptDetail?.caveat).toBe(t('klaude.systemContext.rebuilt'))
    // The key must actually resolve, not fall through as its own name.
    expect(system?.promptDetail?.caveat).not.toBe('klaude.systemContext.rebuilt')
  })
})

describe('unavailable', () => {
  it('adds no SYSTEM row and no schemas', () => {
    const snapshot = snapshotOf({ available: false, reason: 'rebuild failed: OSError' })
    expect(cells(snapshot).some(cell => cell.kind === 'system')).toBe(false)
    expect(snapshot.callSchemas.size).toBe(0)
    const anchor = snapshot.requests.find(request => request.purpose === 'assistant')
    expect(anchor?.purpose === 'assistant' ? anchor.prompt : undefined).toBeUndefined()
  })

  it('adds nothing before the fetch resolves', () => {
    const snapshot = snapshotOf(undefined)
    expect(cells(snapshot).some(cell => cell.kind === 'system')).toBe(false)
    expect(snapshot.callSchemas.size).toBe(0)
  })
})
