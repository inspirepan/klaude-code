/**
 * REST ledger rows -> `TrajectorySnapshot`.
 *
 * One linear pass over the rows of `events.jsonl`. Every row keeps its line
 * number as its identity (see `seq.ts`), so prepending an older page never
 * renumbers a row that is already on screen.
 *
 * The full entry -> row mapping is documented in `README.md`.
 */

import type {
  AssistantMessageNode,
  AssistantProvenanceView,
  AssistantRequestConfig,
  ContentBlock,
  ContextMessageNode,
  ConversationLocation,
  ConversationNode,
  RequestView,
  ToolResultNode,
  ToolSchema,
  TrajectoryAnnotations,
  TrajectoryDiscarded,
  TrajectoryRecordAnnotation,
} from '../contract/index.ts'
import type { TrajectorySnapshot } from '../trajectory/trajectory-contract.ts'
import { autoUserReason, isCheckpointReminder } from './classify.ts'
import { readArray, readNumber, readRecord, readString, readTime } from './json.ts'
import { assistantBlocks, contentBlocks, joinTextParts, toolCallPart } from './parts.ts'
import { nodeSeq, requestSeq } from './seq.ts'
import { decodeUsage, toAssistantTiming, toUsageLike } from './usage.ts'
import type { HistoryRow } from './wire.ts'

type AssistantRequestView = Extract<RequestView, { purpose: 'assistant' }>
type CompactionRequestView = Extract<RequestView, { purpose: 'compaction' }>

/** Inputs the projection needs beyond the rows themselves. */
export interface BuildSnapshotOptions {
  /** Session that owns the rows; local image paths resolve against it. */
  readonly sessionId: string
}

/** Longest error headline kept for a failed tool row. */
const ERROR_CODE_MAX_LENGTH = 140

/** The Agent tool is the one that spawns a sub-agent session. */
const AGENT_TOOL_NAME = 'Agent'

/**
 * Project a page of ledger rows into the snapshot the trajectory view folds.
 * @param rows - Ledger rows in ascending `line_index` order.
 * @param options - Session context for the projection.
 * @returns A finalized snapshot; `partial` and `runningCalls` stay empty until
 *   the live WS channel lands (part 2).
 */
export function buildTrajectorySnapshot(
  rows: readonly HistoryRow[],
  options: BuildSnapshotOptions,
): TrajectorySnapshot {
  const { sessionId } = options
  const nodes: ConversationNode[] = []
  const requests: RequestView[] = []
  const eventLocations = new Map<number, ConversationLocation>()
  const bySeq = new Map<number, TrajectoryRecordAnnotation>()
  const byCallId = new Map<string, TrajectoryRecordAnnotation>()
  const callsById = new Map<string, { time: number; name: string; argsRaw: string }>()
  const unlinkedAgentCalls: string[] = []

  let turn = 0
  let step = 0
  let lastAssistantRequest: AssistantRequestView | null = null
  let pendingCachedTokens: number | undefined

  for (const row of rows) {
    const entry = row.entry
    if (entry === null) continue
    const line = row.line_index
    const seq = nodeSeq(line)
    const data = entry.data
    const discarded = discardedOf(row)
    const time = readTime(data.created_at) ?? 0

    switch (entry.type) {
      case 'UserMessage': {
        const parts = readArray(data.parts)
        const reason = autoUserReason(readString(data.source), joinTextParts(parts))
        if (reason === null) {
          turn += 1
          step = 0
        } else if (turn === 0) turn = 1
        nodes.push({
          kind: 'user',
          seq,
          time,
          content: contentBlocks(parts, sessionId),
          source: entry,
        })
        eventLocations.set(seq, { kind: 'turn', turn: { turn } })
        annotate(bySeq, seq, {
          lineIndex: line,
          ...(discarded === undefined ? {} : { discarded }),
          ...(reason === null ? {} : { auto: true as const }),
        })
        lastAssistantRequest = null
        break
      }

      case 'AssistantMessage': {
        if (turn === 0) turn = 1
        step += 1
        const parts = readArray(data.parts)
        const usage = decodeUsage(data.usage)
        const usageLike = usage === undefined
          ? undefined
          : toUsageLike(usage, pendingCachedTokens)
        pendingCachedTokens = undefined
        const provenance = provenanceOf(usage?.provider, usage?.modelName)
        const requestConfig = requestConfigOf(usage?.provider, usage?.modelName, usage?.maxTokens)
        const timing = toAssistantTiming(usage, time)
        const messageId = readString(data.response_id) ?? readString(data.id)
        const node: AssistantMessageNode = {
          kind: 'assistant',
          seq,
          time,
          turn,
          step,
          blocks: assistantBlocks(parts, sessionId),
          ...(messageId === undefined ? {} : { messageId }),
          ...(usageLike === undefined ? {} : { usage: usageLike }),
          ...(provenance === undefined ? {} : { provenance }),
          ...(requestConfig === undefined ? {} : { requestConfig }),
          ...(timing === undefined ? {} : { timing }),
        }
        nodes.push(node)
        eventLocations.set(seq, { kind: 'step', turn: { turn }, step: { step } })
        annotate(bySeq, seq, {
          lineIndex: line,
          ...(discarded === undefined ? {} : { discarded }),
        })
        const stopReason = readString(data.stop_reason)
        const request: AssistantRequestView = {
          purpose: 'assistant',
          turn,
          step,
          startSeq: requestSeq(line),
          startedAt: usage?.createdAt ?? time,
          completedAt: time,
          status: stopReason === 'error' ? 'error' : 'complete',
          ...(provenance === undefined ? {} : { provenance }),
          ...(requestConfig === undefined ? {} : { requestConfig }),
          ...(usageLike === undefined ? {} : { usage: usageLike }),
          resultSeq: seq,
        }
        requests.push(request)
        lastAssistantRequest = request
        for (const part of parts) {
          const record = readRecord(part)
          if (record === undefined || readString(record.type) !== 'tool_call') continue
          const call = toolCallPart(record)
          if (call === undefined) continue
          callsById.set(call.callId, { time, name: call.name, argsRaw: call.argsRaw })
          if (call.name === AGENT_TOOL_NAME) unlinkedAgentCalls.push(call.callId)
          annotate(byCallId, call.callId, {
            lineIndex: line,
            ...(discarded === undefined ? {} : { discarded }),
          })
        }
        break
      }

      case 'ToolResultMessage': {
        const callId = readString(data.call_id) ?? ''
        if (callId === '') break
        const toolName = readString(data.tool_name) ?? ''
        const call = callsById.get(callId)
        const status = readString(data.status)
        const isError = status === 'error' || status === 'aborted'
        const outputText = readString(data.output_text) ?? ''
        const content: ContentBlock[] = [
          ...(outputText === '' ? [] : [{ type: 'text' as const, text: outputText }]),
          ...contentBlocks(readArray(data.parts), sessionId),
        ]
        const node: ToolResultNode = {
          kind: 'tool-result',
          seq,
          time,
          callId,
          call: call === undefined
            ? (toolName === '' ? null : { name: toolName, argsRaw: '' })
            : { name: call.name, argsRaw: call.argsRaw },
          callTime: call?.time ?? null,
          content,
          isError,
          ...(isError
            ? { error: { name: toolName === '' ? 'tool' : toolName, code: errorCode(outputText, status) } }
            : {}),
          subCalls: [],
        }
        nodes.push(node)
        eventLocations.set(seq, { kind: 'step', turn: { turn }, step: { step } })
        const annotation: TrajectoryRecordAnnotation = {
          lineIndex: line,
          ...(discarded === undefined ? {} : { discarded }),
        }
        annotate(bySeq, seq, annotation)
        annotate(byCallId, callId, annotation)
        break
      }

      case 'DeveloperMessage': {
        const parts = readArray(data.parts)
        // Legacy checkpoint reminders are pure bookkeeping; the plan hides them.
        if (isCheckpointReminder(joinTextParts(parts))) break
        nodes.push(contextNode(seq, time, contentBlocks(parts, sessionId), entry, contextLabel(data)))
        eventLocations.set(seq, { kind: 'turn', turn: { turn: Math.max(1, turn) } })
        annotate(bySeq, seq, {
          lineIndex: line,
          ...(discarded === undefined ? {} : { discarded }),
        })
        break
      }

      case 'CompactionEntry': {
        const summary = readString(data.summary) ?? ''
        nodes.push({
          kind: 'compaction',
          seq,
          time,
          summary,
          summaryEventSeq: seq,
          shadowedItemCount: readNumber(data.first_kept_index) ?? null,
          shadowedTokenCount: readNumber(data.tokens_before) ?? null,
        })
        const request: CompactionRequestView = {
          purpose: 'compaction',
          turn: turn === 0 ? null : turn,
          step: 0,
          startSeq: requestSeq(line),
          startedAt: time,
          // No LLMRequestEntry yet (M4): the compaction call has no recorded
          // end, so the marker reports a zero-length request rather than a
          // pending one.
          completedAt: time,
          status: 'complete',
          summary: [{ type: 'text', text: summary }],
          replacementSeq: seq,
        }
        requests.push(request)
        annotate(bySeq, requestSeq(line), { lineIndex: line })
        break
      }

      case 'RewindEntry': {
        const note = readString(data.note) ?? ''
        const rationale = readString(data.rationale) ?? ''
        const content: ContentBlock[] = [
          { type: 'text', text: rationale === '' ? note : rationale },
          ...(rationale === '' || note === '' ? [] : [{ type: 'text' as const, text: note }]),
        ]
        nodes.push(contextNode(seq, time, content, entry, 'rewind'))
        eventLocations.set(seq, { kind: 'turn', turn: { turn: Math.max(1, turn) } })
        annotate(bySeq, seq, {
          lineIndex: line,
          kind: 'rewind',
          ...(discarded === undefined ? {} : { discarded }),
        })
        break
      }

      case 'SideQuestionEntry': {
        const question = readString(data.question) ?? ''
        const answer = readString(data.answer) ?? ''
        const content: ContentBlock[] = [
          { type: 'text', text: question },
          ...(answer === '' ? [] : [{ type: 'text' as const, text: answer }]),
        ]
        nodes.push(contextNode(seq, time, content, entry, 'btw'))
        eventLocations.set(seq, { kind: 'turn', turn: { turn: Math.max(1, turn) } })
        annotate(bySeq, seq, {
          lineIndex: line,
          kind: 'btw',
          ...(discarded === undefined ? {} : { discarded }),
        })
        break
      }

      case 'ForkSummaryEntry': {
        turn += 1
        step = 0
        const summary = readString(data.summary) ?? ''
        nodes.push({
          kind: 'user',
          seq,
          time,
          content: [{ type: 'text', text: summary }],
          source: entry,
        })
        eventLocations.set(seq, { kind: 'turn', turn: { turn } })
        annotate(bySeq, seq, {
          lineIndex: line,
          ...(discarded === undefined ? {} : { discarded }),
        })
        lastAssistantRequest = null
        break
      }

      case 'SpawnSubAgentEntry': {
        const childSession = readString(data.session_id)
        const callId = unlinkedAgentCalls.shift()
        if (childSession === undefined || callId === undefined) break
        annotate(byCallId, callId, {
          subAgent: {
            sessionId: childSession,
            type: readString(data.sub_agent_type) ?? '',
            desc: readString(data.sub_agent_desc) ?? '',
          },
        })
        break
      }

      case 'CacheHitRateEntry': {
        // Written when the step's usage arrives, i.e. just *before* the
        // assistant message it describes.
        pendingCachedTokens = readNumber(data.cached_tokens)
        break
      }

      case 'InterruptEntry': {
        failLastRequest(lastAssistantRequest, 'Interrupted')
        break
      }

      case 'StreamErrorItem': {
        failLastRequest(lastAssistantRequest, readString(data.error) ?? 'Stream error')
        break
      }

      default:
        // Every other sidecar (TaskMetadataItem, TaskFileChangeSummaryEntry,
        // FallbackModelConfigWarnEntry, PromptSuggestionEntry,
        // AwaySummaryEntry, RetractEntry, unknown types) takes no ledger row.
        break
    }
  }

  const annotations: TrajectoryAnnotations = { bySeq, byCallId }
  return {
    eventNodes: nodes,
    eventLocations,
    requests,
    callSchemas: new Map<string, ToolSchema>(),
    partial: null,
    runningCalls: [],
    annotations,
  }
}

function contextNode(
  seq: number,
  time: number,
  content: readonly ContentBlock[],
  source: unknown,
  label: string | null,
): ContextMessageNode {
  return {
    kind: 'context',
    seq,
    time,
    content,
    source,
    provenance: { role: 'inject', label },
    form: null,
  }
}

/** Producer name for a developer row, taken from its UI metadata. */
function contextLabel(data: Record<string, unknown>): string | null {
  const uiExtra = readRecord(data.ui_extra)
  if (uiExtra === undefined) return null
  const single = readString(uiExtra.type)
  if (single !== undefined) return single
  const kinds = readArray(uiExtra.items)
    .flatMap((item) => {
      const type = readString(readRecord(item)?.type)
      return type === undefined ? [] : [type]
    })
  return kinds.length === 0 ? null : [...new Set(kinds)].join(', ')
}

function provenanceOf(
  provider: string | undefined,
  model: string | undefined,
): AssistantProvenanceView | undefined {
  if (provider === undefined && model === undefined) return undefined
  return { provider: provider ?? '', model: model ?? '' }
}

function requestConfigOf(
  provider: string | undefined,
  model: string | undefined,
  maxTokens: number | undefined,
): AssistantRequestConfig | undefined {
  if (provider === undefined || model === undefined) return undefined
  return { provider, model, ...(maxTokens === undefined ? {} : { maxTokens }) }
}

/** Fold an interrupt or stream error into the request that was running. */
function failLastRequest(request: AssistantRequestView | null, error: string): void {
  if (request === null || request.status === 'error') return
  request.status = 'error'
  request.error = error
}

function errorCode(outputText: string, status: string | undefined): string {
  const headline = outputText.split('\n').map(line => line.trim()).find(line => line !== '')
  if (headline === undefined) return status ?? 'error'
  return headline.length > ERROR_CODE_MAX_LENGTH
    ? `${headline.slice(0, ERROR_CODE_MAX_LENGTH)}…`
    : headline
}

function discardedOf(row: HistoryRow): TrajectoryDiscarded | undefined {
  if (row.status === 'retracted' || row.status === 'compacted' || row.status === 'rewound') {
    return { status: row.status, droppedBy: row.dropped_by }
  }
  return undefined
}

function annotate<K>(
  map: Map<K, TrajectoryRecordAnnotation>,
  key: K,
  patch: TrajectoryRecordAnnotation,
): void {
  const current = map.get(key)
  map.set(key, current === undefined ? patch : { ...current, ...patch })
}
