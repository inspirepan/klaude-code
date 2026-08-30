/**
 * Hand-written trajectory snapshot used to bring the forked UI up before the
 * REST/WS adapter exists. It exercises one turn: a user message, a two-step
 * assistant exchange with one tool call, and the request headers that put
 * request dots on the ledger.
 */

import type {
  ConversationLocation, ConversationNode, ConversationPromptSnapshot, RequestView, ToolSchema,
} from '../contract/index.ts'
import type { TrajectorySnapshot } from '../trajectory/trajectory-contract.ts'

const T0 = Date.UTC(2026, 7, 30, 9, 15, 0)

const READ_TOOL: ToolSchema = {
  name: 'Read',
  description: 'Read a file from the local filesystem.',
  parameters: {
    type: 'object',
    properties: {
      file_path: { type: 'string', description: 'Absolute path to the file.' },
      limit: { type: 'number', description: 'Maximum number of lines to read.' },
    },
    required: ['file_path'],
  },
}

const PROMPT: ConversationPromptSnapshot = {
  config: {
    provider: 'anthropic',
    model: 'claude-fable-5',
    temperature: 1,
    maxTokens: 32_000,
  },
  system: 'You are klaude, a coding agent running in the user\'s terminal.\n\n'
    + 'Answer concisely. Prefer editing an existing file over creating a new one.',
  tools: [READ_TOOL],
}

const CALL_ID = 'toolu_01FixtureRead'
const CALL_ARGS = JSON.stringify({ file_path: '/Users/panjx/code/klaude/README.md', limit: 40 })

const nodes: readonly ConversationNode[] = [
  {
    kind: 'user',
    seq: 1,
    time: T0,
    content: [{ type: 'text', text: 'Summarize the README and tell me what klaude does.' }],
    source: { kind: 'user' },
  },
  {
    kind: 'assistant',
    seq: 3,
    messageId: 'msg_fixture_1',
    time: T0 + 2_400,
    turn: 1,
    step: 1,
    blocks: [
      { kind: 'reasoning', text: 'The README is the fastest source. Read it first.' },
      { kind: 'text', text: 'Reading the README now.' },
      { kind: 'tool-call', callId: CALL_ID, name: 'Read', argsRaw: CALL_ARGS },
    ],
    usage: {
      inputTokens: 4_211,
      cacheReadTokens: 3_840,
      outputTokens: 96,
      reasoningTokens: 41,
    },
    provenance: { provider: 'anthropic', model: 'claude-fable-5' },
    requestConfig: PROMPT.config,
    timing: {
      stepStartTime: T0 + 120,
      firstTokenTime: T0 + 980,
      completedTime: T0 + 2_400,
    },
  },
  {
    kind: 'tool-result',
    seq: 4,
    time: T0 + 2_760,
    callId: CALL_ID,
    call: { name: 'Read', argsRaw: CALL_ARGS },
    callTime: T0 + 2_420,
    content: [{
      type: 'text',
      text: '# klaude-code\n\nA terminal coding agent.\n\n- Persistent server, many sessions\n'
        + '- Headless command surface\n- Web trajectory viewer\n',
    }],
    isError: false,
    subCalls: [],
  },
  {
    kind: 'assistant',
    seq: 6,
    messageId: 'msg_fixture_2',
    time: T0 + 6_050,
    turn: 1,
    step: 2,
    blocks: [{
      kind: 'text',
      text: '`klaude-code` is a terminal coding agent.\n\n'
        + '- One **persistent server** multiplexes many sessions.\n'
        + '- A headless command surface (`run`/`ps`/`wait`) drives it from scripts.\n'
        + '- This web viewer replays a session trajectory read-only.\n',
    }],
    usage: {
      inputTokens: 4_620,
      cacheReadTokens: 4_180,
      outputTokens: 214,
    },
    provenance: { provider: 'anthropic', model: 'claude-fable-5' },
    requestConfig: PROMPT.config,
    timing: {
      stepStartTime: T0 + 2_800,
      firstTokenTime: T0 + 3_410,
      completedTime: T0 + 6_050,
    },
  },
]

const requests: readonly RequestView[] = [
  {
    purpose: 'assistant',
    turn: 1,
    step: 1,
    startSeq: 2,
    startedAt: T0 + 120,
    completedAt: T0 + 2_400,
    status: 'complete',
    prompt: PROMPT,
    promptChange: { seq: 2, time: T0 + 100, kind: 'initial' },
    provenance: { provider: 'anthropic', model: 'claude-fable-5' },
    requestConfig: PROMPT.config,
    usage: {
      inputTokens: 4_211,
      cacheReadTokens: 3_840,
      outputTokens: 96,
      reasoningTokens: 41,
    },
    resultSeq: 3,
  },
  {
    purpose: 'assistant',
    turn: 1,
    step: 2,
    startSeq: 5,
    startedAt: T0 + 2_800,
    completedAt: T0 + 6_050,
    status: 'complete',
    prompt: PROMPT,
    provenance: { provider: 'anthropic', model: 'claude-fable-5' },
    requestConfig: PROMPT.config,
    usage: {
      inputTokens: 4_620,
      cacheReadTokens: 4_180,
      outputTokens: 214,
    },
    resultSeq: 6,
  },
]

const step = (turn: number, stepNumber: number): ConversationLocation => ({
  kind: 'step',
  turn: { turn },
  step: { step: stepNumber },
})

const eventLocations = new Map<number, ConversationLocation>([
  [1, { kind: 'session' }],
  [2, step(1, 1)],
  [3, step(1, 1)],
  [4, step(1, 1)],
  [5, step(1, 2)],
  [6, step(1, 2)],
])

const callSchemas = new Map<string, ToolSchema>([[CALL_ID, READ_TOOL]])

/** The fixture snapshot rendered by the standalone entry. */
export const FIXTURE_SNAPSHOT: TrajectorySnapshot = {
  eventNodes: nodes,
  eventLocations,
  requests,
  callSchemas,
  partial: null,
  runningCalls: [],
}
