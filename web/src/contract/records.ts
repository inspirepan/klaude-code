// Each publication replaces the top-level snapshot while preserving unchanged
// substructure references. Stable node and location stores make old snapshots
// live readers rather than time-point views.

// klaude: cross-package imports flattened onto ./types.ts (CommandId,
// LlmRetryEventData and TodoItem dropped with the node arms below)
import type { ContentBlock, ImageAttachmentRef, MessageId } from './types.ts'
import type { ContextProvenanceView, KnownContextForm } from './context-provenance.ts'

/** Request configuration recorded for one provider call. */
export interface AssistantRequestConfig {
  provider: string
  model: string
  purpose?: string
  thinking?: string
  reasoningEffort?: string
  temperature?: number
  maxTokens?: number
  stop?: readonly string[]
}

/** Stable provider/model identity reported for one completed request. */
export interface AssistantProvenanceView {
  provider: string
  model: string
}

/** Assistant content blocks sorted by what a UI target presents. */
export type AssistantBlock =
  | { kind: 'text'; text: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'image'; attachment: ImageAttachmentRef }
  | { kind: 'tool-call'; callId: string; name: string; argsRaw: string }
  | { kind: 'other'; block: unknown }

/** A finalized user message. */
export interface UserMessageNode {
  kind: 'user'
  seq: number
  /** Unix epoch ms from the source session event. */
  time: number
  content: readonly ContentBlock[]
  source: unknown
}

/** Recorded boundaries used to derive assistant latency and throughput. */
export interface AssistantTiming {
  /** Matching step/start timestamp, or null when it is outside the current event window. */
  stepStartTime: number | null
  /** First non-empty text/reasoning/tool delta timestamp, or null when no token delta was recorded. */
  firstTokenTime: number | null
  /** Final assistant/message timestamp. */
  completedTime: number
}

/** A finalized assistant message or an interruption-frozen streaming prefix. */
export interface AssistantMessageNode {
  kind: 'assistant'
  seq: number
  /**
   * Stable identity carried from the `assistant/message` event. Absent only on
   * synthetic interruption fallbacks assembled from chunks without a durable
   * assistant message.
   */
  messageId?: MessageId
  /** Unix epoch ms from the source session event (or turn/end when frozen from a partial). */
  time: number
  turn: number
  step: number
  blocks: readonly AssistantBlock[]
  usage?: unknown
  provenance?: AssistantProvenanceView
  requestConfig?: AssistantRequestConfig
  /** Timing derived from the recorded step/chunk/message event sequence. */
  timing?: AssistantTiming
  /** Prefix of an aborted turn, rendered with a 已停止 marker. A durable
   *  finalized prefix uses its event seq; a chunk-only fallback uses a fractional
   *  seq derived from the closing boundary to keep it ordered inside the flow. */
  interrupted?: true
}

/** A human message admitted from the next-step inbox while a turn was running. */
export interface SteeringMessageNode {
  kind: 'steering'
  /** Stable message identity shared with its pre-admission inbox occurrence. */
  messageId: MessageId
  seq: number
  /** Unix epoch ms from the source session event. */
  time: number
  content: readonly ContentBlock[]
  source: unknown
}

/** A context/system injection surfaced in the flow. */
export interface ContextMessageNode {
  kind: 'context'
  seq: number
  /** Unix epoch ms from the source session event. */
  time: number
  content: readonly ContentBlock[]
  source: unknown
  /** Role and producer name projected from `source` by the target. */
  provenance: ContextProvenanceView
  /** Producer-declared information form supported by the target; null presents as opaque. */
  form: KnownContextForm | null
}

// klaude: ModelRetryNode / TurnErrorNode / TurnMaxTokensNode dropped —
// layout.ts handles only user/steering/assistant/context/compaction/tool-result

/** A tool result paired (when in-window) with its call head. */
export interface ToolResultNode {
  kind: 'tool-result'
  seq: number
  /** Unix epoch ms from the tool/result session event. */
  time: number
  callId: string
  /** Parent Tool call for a Code Dispatch result; absent on a root Session result. */
  parentCallId?: string
  /** Call head backfilled from the in-window tool/call; null when window truncation left the call outside (card head shows callId). */
  call: { name: string; argsRaw: string } | null
  /** Unix epoch ms of the paired tool/call when the call is still in-window; used for call-row duration. */
  callTime: number | null
  content: readonly ContentBlock[]
  isError: boolean
  error?: { name: string; code: string }
  meta?: unknown
  /** Child calls owned by this call, in dispatch order. */
  subCalls: readonly ToolCallBlock[]
}

/**
 * One landed compaction, marked at the checkpoint's own log position. The
 * conversation it shadowed on the model surface stays in the transcript above
 * it: the marker reports where the model stopped seeing that history, it does
 * not replace it. The framed checkpoint payload is an instruction envelope
 * written for the model and never renders.
 */
export interface CompactionSummaryNode {
  kind: 'compaction'
  /** Seq of the replacement `user/message` that landed the checkpoint. */
  seq: number
  /** Unix epoch ms of the checkpoint event. */
  time: number
  /** Summary text from the checkpoint's cited `compaction/summary` event; null when
   *  the window cut left that event outside (the marker is then not expandable). */
  summary: string | null
  /** Seq of the loaded `compaction/summary` event, or null when that event is outside the window. */
  summaryEventSeq: number | null
  /** Number of surface items replaced, or null when the summary event is unavailable or malformed. */
  shadowedItemCount: number | null
  /** Estimated token price of the replaced items, or null when the summary event is unavailable or malformed. */
  shadowedTokenCount: number | null
}

// klaude: UnknownSurfaceNode / CommandNode dropped with the same rationale

/** Finalized conversation node union (kind discriminates; seq is the React key). */
export type ConversationNode =
  | UserMessageNode
  | AssistantMessageNode
  | SteeringMessageNode
  | ContextMessageNode
  | ToolResultNode
  | CompactionSummaryNode // klaude: arms above trimmed to the six layout.ts handles

/** In-flight tool card material: tool/call seen, tool/result not yet. */
export interface RunningToolCall {
  callId: string
  /** Parent Tool call for a Code Dispatch start; absent on a root Session call. */
  parentCallId?: string
  name: string
  argsRaw: string
  turn: number
  step: number
  /** Unix epoch ms when the tool/call event was logged. */
  time: number
  /** Child calls owned by this call, in dispatch order. */
  subCalls: readonly ToolCallBlock[]
}

/** One running or settled call, recursively owning its child calls. */
export type ToolCallBlock = RunningToolCall | ToolResultNode

/** In-progress assistant output (chunk accumulator product). */
export interface PartialAssistant {
  turn: number
  step: number
  blocks: readonly AssistantBlock[]
}
