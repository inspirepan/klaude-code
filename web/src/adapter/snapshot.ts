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
  AssistantTiming,
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
import { decodeLLMRequest, requestOptions, type LLMRequestRecord } from './llm-request.ts'
import { assistantBlocks, contentBlocks, joinTextParts, toolCallPart } from './parts.ts'
import { nodeSeq, requestSeq } from './seq.ts'
import { promptSnapshot, toolSchemasByName } from './system-context.ts'
import { decodeUsage, toAssistantTiming, toUsageLike } from './usage.ts'
import type { HistoryRow, SystemContext } from './wire.ts'

type AssistantRequestView = Extract<RequestView, { purpose: 'assistant' }>
type CompactionRequestView = Extract<RequestView, { purpose: 'compaction' }>

/** Inputs the projection needs beyond the rows themselves. */
export interface BuildSnapshotOptions {
  /** Session that owns the rows; local image paths resolve against it. */
  readonly sessionId: string
  /**
   * `GET /api/web/sessions/{id}/system-context`, once it has been fetched.
   *
   * klaude persists neither the system prompt nor the tool catalogue, so the
   * SYSTEM row and the tool inspector's Schema tab exist only when the page
   * has this. Undefined (or `available: false`) simply means no SYSTEM row.
   */
  readonly systemContext?: SystemContext | undefined
  /** Locale seat for the one string the projection needs (the rebuilt caveat). */
  readonly translate?: ((key: string) => string) | undefined
}

/**
 * Seq of the SYSTEM record.
 *
 * The prompt was never an event, so it owns no ledger line. Seq 0 sorts it
 * ahead of every row and — being a constant rather than a window position —
 * keeps the record's React key stable when an older page is prepended.
 * `layout.ts` places an `initial` prompt change at the head regardless of seq.
 */
const PROMPT_SEQ = 0

/**
 * First synthetic step number for a sidecar request.
 *
 * A recorded LLM call outside a step (compaction sub-call, `/btw`, fork
 * summary, a failed call) still needs a request identity, and upstream's is
 * `assistant\0turn\0step`. Real steps are small and 1-based, so a line-derived
 * step above this base can never collide with one; the number is never shown
 * (the group it names holds nothing but the zero-height dot row).
 */
const SIDECAR_STEP_BASE = 1_000_000

/** Longest error headline kept for a failed tool row. */
const ERROR_CODE_MAX_LENGTH = 140

/** The Agent tool is the one that spawns a sub-agent session. */
const AGENT_TOOL_NAME = 'Agent'

/** Absolute turn/step ordinals a row carries, when the server computed them. */
interface RowOrdinals {
  /** Absolute human-turn ordinal (0 ahead of the first human message). */
  readonly turn?: number
  /** 1-based assistant step inside the turn. */
  readonly step?: number
  /** True when the runtime, not a person, wrote this user message. */
  readonly auto?: boolean
}

/**
 * Read the server-computed ordinals off a row.
 *
 * `session/ledger.py` numbers every physical line in one pass over the whole
 * file, so these are absolute and survive a prepend. They are optional: an
 * older server omits them and the caller falls back to counting inside the
 * loaded window.
 * @param row - One ledger row.
 * @returns The ordinals the row carries; empty when the server sent none.
 */
function rowOrdinals(row: HistoryRow): RowOrdinals {
  return {
    ...(typeof row.turn_index === 'number' ? { turn: row.turn_index } : {}),
    ...(typeof row.step_index === 'number' ? { step: row.step_index } : {}),
    ...(typeof row.auto === 'boolean' ? { auto: row.auto } : {}),
  }
}


/**
 * Project a page of ledger rows into the snapshot the trajectory view folds.
 * @param rows - Ledger rows in ascending `line_index` order.
 * @param options - Session context for the projection.
 * @returns A finalized snapshot. `partial` and `runningCalls` are always empty
 *   here — REST owns landed rows; the live WS splice (`app/live`) is what fills
 *   those two fields for an online session.
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
  // Every call id seen in the window, so the tool catalogue can be resolved to
  // a per-row schema once the system context has landed.
  const toolNameByCall = new Map<string, string>()
  // Recorded LLM calls, by `request_id`. The paired entry always follows, so a
  // lookup here is the whole join — position is never used.
  const sidecarById = new Map<string, { request: AssistantRequestView; record: LLMRequestRecord }>()
  // Sidecar requests a later entry claimed: the compaction primary becomes the
  // COMPACT row's own request instead of a dot of its own.
  const absorbed = new Set<RequestView>()

  let turn = 0
  let step = 0
  let firstTime: number | null = null
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
    if (firstTime === null && time !== 0) firstTime = time
    const ordinals = rowOrdinals(row)
    // Server ordinals are absolute; adopting them keeps every later row in the
    // page numbered the same way even when this row's arm reads none. Turn 0
    // means "ahead of the first human message" and is kept as such: `layout.ts`
    // folds turn-0 cells into Turn 1 on its own.
    const numbered = ordinals.turn !== undefined
    if (ordinals.turn !== undefined) turn = ordinals.turn

    switch (entry.type) {
      case 'UserMessage': {
        const parts = readArray(data.parts)
        const auto = ordinals.auto
          ?? (autoUserReason(readString(data.source), joinTextParts(parts)) !== null)
        if (numbered) {
          // The scan already opened the turn; only the step counter is ours.
          if (!auto) step = 0
        } else if (!auto) {
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
          ...(auto ? { auto: true as const } : {}),
        })
        lastAssistantRequest = null
        break
      }

      case 'AssistantMessage': {
        if (!numbered && turn === 0) turn = 1
        if (ordinals.step !== undefined) step = ordinals.step
        else step += 1
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
          toolNameByCall.set(call.callId, call.name)
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
        // A result whose call fell outside the window still names its tool.
        if (toolName !== '' && !toolNameByCall.has(callId)) toolNameByCall.set(callId, toolName)
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
        eventLocations.set(seq, { kind: 'turn', turn: { turn } })
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
        // The primary call becomes this row's own request rather than a dot of
        // its own; a degraded compaction's second call keeps its dot and fans
        // out beside this one.
        const joined = joinRequest(sidecarById, absorbed, data.request_id)
        const failure = requestError(joined)
        const request: CompactionRequestView = {
          purpose: 'compaction',
          turn: turn === 0 ? null : turn,
          step: 0,
          startSeq: requestSeq(line),
          startedAt: joined?.startedAt ?? time,
          // Without a recorded end the marker reports a zero-length request
          // rather than a pending one — a `null` would render as still running.
          completedAt: joined?.completedAt ?? joined?.startedAt ?? time,
          status: requestStatus(joined),
          ...(failure === undefined ? {} : { error: failure }),
          ...requestFacts(joined),
          summary: [{ type: 'text', text: summary }],
          replacementSeq: seq,
        }
        requests.push(request)
        annotate(bySeq, requestSeq(line), { lineIndex: line })
        break
      }

      case 'LLMRequestEntry': {
        // One recorded LLM call outside a step. It renders as a dot with no
        // row; the entry it describes follows on the next line and, for
        // compaction, claims this request through `request_id`.
        const record = decodeLLMRequest(data)
        if (record === undefined) break
        const request = sidecarRequest(record, line, turn, time)
        requests.push(request)
        sidecarById.set(record.requestId, { request, record })
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
        eventLocations.set(seq, { kind: 'turn', turn: { turn } })
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
        eventLocations.set(seq, { kind: 'turn', turn: { turn } })
        annotate(bySeq, seq, {
          lineIndex: line,
          kind: 'btw',
          ...(discarded === undefined ? {} : { discarded }),
        })
        break
      }

      case 'ForkSummaryEntry': {
        // A fork summary renders as a user row but is not one: `session/ledger.py`
        // does not open a turn for it, and neither does the fallback. It sits
        // in the turn it was written into (turn 0 at the head of a fork, which
        // `layout.ts` folds into Turn 1).
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
  const live = requests.filter(request => !absorbed.has(request))
  attachPrompt(live, options, firstTime ?? 0)
  return {
    eventNodes: nodes,
    eventLocations,
    requests: live,
    callSchemas: schemasByCall(toolNameByCall, options.systemContext),
    partial: null,
    runningCalls: [],
    annotations,
  }
}

/**
 * Resolve the `request_id` an entry carries to the record written before it.
 * @param sidecars - Recorded calls seen so far, by id.
 * @param absorbed - Requests that stop being dots of their own; extended here.
 * @param value - The entry's `request_id`; absent on a pre-M4 session.
 * @returns The joined record, or undefined when the entry links to nothing.
 */
function joinRequest(
  sidecars: ReadonlyMap<string, { request: AssistantRequestView; record: LLMRequestRecord }>,
  absorbed: Set<RequestView>,
  value: unknown,
): LLMRequestRecord | undefined {
  const requestId = readString(value)
  if (requestId === undefined) return undefined
  const hit = sidecars.get(requestId)
  if (hit === undefined) return undefined
  absorbed.add(hit.request)
  return hit.record
}

/** Upstream request status for a recorded call; unrecorded calls read complete. */
function requestStatus(record: LLMRequestRecord | undefined): 'complete' | 'error' {
  return record !== undefined && record.status !== 'completed' ? 'error' : 'complete'
}

/** Failure text for a recorded call; an interrupt carries none of its own. */
function requestError(record: LLMRequestRecord | undefined): string | undefined {
  if (record === undefined || record.status === 'completed') return undefined
  return record.error ?? (record.status === 'interrupted' ? 'Interrupted' : 'Request failed')
}

/** The recorded facts every request arm copies verbatim. */
interface RecordedRequestFacts {
  provenance?: AssistantProvenanceView
  requestConfig?: AssistantRequestConfig
  usage?: unknown
  timing?: AssistantTiming
}

/**
 * Provider, options, usage and timing of one recorded call.
 *
 * Every field is omitted rather than zeroed when the entry did not record it,
 * so an old session reads as unknown. `CacheHitRateEntry` is deliberately not
 * folded in here: `agent/task.py` writes it for the *next main step*, so
 * charging its cached tokens to a compaction or `/btw` call would misattribute
 * them.
 * @param record - The decoded entry, or undefined for an unrecorded call.
 * @returns The facts to spread onto the request.
 */
function requestFacts(record: LLMRequestRecord | undefined): RecordedRequestFacts {
  if (record === undefined) return {}
  const provenance = provenanceOf(record.provider, record.model)
  const config = requestOptions(record)
  const usage = record.usage === undefined ? undefined : toUsageLike(record.usage)
  const timing: AssistantTiming | undefined = record.startedAt === null
    ? undefined
    : {
      stepStartTime: record.startedAt,
      firstTokenTime: record.firstTokenAt,
      completedTime: record.completedAt ?? record.startedAt,
    }
  return {
    ...(provenance === undefined ? {} : { provenance }),
    ...(config === undefined ? {} : { requestConfig: config }),
    ...(usage === undefined ? {} : { usage }),
    ...(timing === undefined ? {} : { timing }),
  }
}

/**
 * One recorded LLM call that owns no ledger row.
 *
 * It renders as a `requestOnly` dot anchored on the entry's own line: right
 * above the BTW / fork-summary row it produced, beside the COMPACT row for a
 * degraded compaction's second call, and alone for a call that failed before
 * it could write anything.
 * @param record - The decoded entry.
 * @param line - Its zero-based `events.jsonl` line.
 * @param turn - Absolute turn the line belongs to.
 * @param fallbackTime - The row's `created_at`, used when the call recorded no start.
 * @returns The request.
 */
function sidecarRequest(
  record: LLMRequestRecord,
  line: number,
  turn: number,
  fallbackTime: number,
): AssistantRequestView {
  const error = requestError(record)
  return {
    purpose: 'assistant',
    // `layout.ts` folds turn-0 cells into Turn 1, and the dot only renders when
    // the request's turn matches the folded row's, so clamp here too.
    turn: Math.max(1, turn),
    step: SIDECAR_STEP_BASE + line,
    startSeq: requestSeq(line),
    startedAt: record.startedAt ?? fallbackTime,
    completedAt: record.completedAt,
    status: requestStatus(record),
    ...(error === undefined ? {} : { error }),
    ...requestFacts(record),
  }
}

/**
 * Hang the fetched system context on the window's first ordinary request.
 *
 * `layout.ts` emits its `system` record from `request.prompt` +
 * `request.promptChange`, and an `initial` change is placed at the head of the
 * first visible turn whatever seq it carries — so which request holds it only
 * decides *whether* the row exists, never where it lands.
 * @param requests - The window's requests, in order.
 * @param options - Build options carrying the system context and locale seat.
 * @param time - Epoch ms of the window's first row.
 */
function attachPrompt(
  requests: readonly RequestView[],
  options: BuildSnapshotOptions,
  time: number,
): void {
  const prompt = promptSnapshot(options.systemContext, options.translate)
  if (prompt === undefined) return
  const assistants = requests.filter(
    (request): request is AssistantRequestView => request.purpose === 'assistant',
  )
  const anchor = assistants.find(request => request.step < SIDECAR_STEP_BASE) ?? assistants[0]
  if (anchor === undefined) return
  anchor.prompt = prompt
  anchor.promptChange = { seq: PROMPT_SEQ, time, kind: 'initial' }
}

/**
 * Resolve every tool call in the window to its model-visible schema.
 *
 * klaude persists no per-call schema, so the catalogue the system-context
 * endpoint reports is the only source; a tool that has since been renamed or
 * removed simply resolves to nothing and its Schema tab stays empty.
 * @param toolNameByCall - Tool name of every call id seen in the window.
 * @param context - The system-context payload, when it has been fetched.
 * @returns call id -> schema.
 */
function schemasByCall(
  toolNameByCall: ReadonlyMap<string, string>,
  context: SystemContext | undefined,
): ReadonlyMap<string, ToolSchema> {
  const byName = toolSchemasByName(context)
  const byCall = new Map<string, ToolSchema>()
  if (byName.size === 0) return byCall
  for (const [callId, name] of toolNameByCall) {
    const schema = byName.get(name)
    if (schema !== undefined) byCall.set(callId, schema)
  }
  return byCall
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
