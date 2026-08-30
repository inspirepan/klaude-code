// klaude: llm types flattened onto ./types.ts; the SessionEvent import went
// with inspectRequestPrompt (see below)
import type { ContentBlock, ToolSchema } from './types.ts'
import type {
  AssistantProvenanceView, AssistantRequestConfig, AssistantTiming,
} from './records.ts'

export type {
  AssistantProvenanceView, AssistantRequestConfig,
} from './records.ts'

/** Complete model-visible request header in force for an ordinary generation. */
export interface ConversationPromptSnapshot {
  /** Provider/model and sampling configuration from the effective request header. */
  config: AssistantRequestConfig
  /** Rendered system prompt text; empty when the request had no system prompt. */
  system: string
  /** Complete tool catalog sent with the request, including tools that were never called. */
  tools: readonly ToolSchema[]
  // klaude: klaude persists neither the prompt nor the catalog, so the SYSTEM
  // row is served on demand by `/api/web/sessions/{id}/system-context`. A
  // `rebuilt` answer reflects today's prompt files rather than what the session
  // sent, and says so here (src/adapter/system-context.ts).
  /** Provenance warning to print above the snapshot; absent when it was recorded live. */
  caveat?: string
}

/** System/tool change introduced while preparing one ordinary request. */
export interface RequestPromptChange {
  /** Sequence of the request/header event that introduced this state. */
  seq: number
  /** Unix epoch ms from the request/header event. */
  time: number
  /** How the model-visible prompt differs from the previous recorded state. */
  kind: 'initial' | 'system' | 'tools' | 'system-and-tools'
  /** State immediately before this change; absent for the initial header. */
  previous?: ConversationPromptSnapshot
}

/** Canonical prompt snapshot and any model-visible change introduced by one request header. */
export interface RequestPromptInspection {
  /** Complete prompt state recorded by the header. */
  prompt: ConversationPromptSnapshot
  /** System/tool change relative to the preceding loaded header. */
  change?: RequestPromptChange
}

// klaude: RequestPromptInspector and inspectRequestPrompt dropped — they read a
// host SessionEvent that klaude's REST/WS adapter never produces

/** Lifecycle fields shared by ordinary generation and compaction requests. */
interface RequestViewBase {
  /** Sequence that opened the operation represented by this request. */
  startSeq: number
  startedAt: number
  completedAt: number | null
  status: 'running' | 'complete' | 'error'
  error?: string
  /** Stable provider code for localized presentation of known failures. */
  errorCode?: string
  provenance?: AssistantProvenanceView
  requestConfig?: AssistantRequestConfig
  usage?: unknown
  // klaude: `LLMRequestEntry` records the boundaries of the LLM calls that
  // happen outside a step (compaction / `/btw` / `/rewind`), which have no
  // assistant record to hang `AssistantTiming` on. Present only when the call
  // was recorded; the request inspector then prints the full timing panel
  // instead of Started/Duration (src/adapter/snapshot.ts).
  /** Recorded call boundaries when the request itself, not a message, carries them. */
  timing?: AssistantTiming
  /** Assistant message or compaction summary sequence produced by this request. */
  resultSeq?: number
}

/** One ordinary assistant generation assembled from durable request events. */
interface AssistantRequestView extends RequestViewBase {
  purpose: 'assistant'
  turn: number
  /** Agent-loop step that issued this request. */
  step: number
  /** Effective ordinary request input, inherited until a later header changes it. */
  prompt?: ConversationPromptSnapshot
  /** Prompt change logged while preparing this request. */
  promptChange?: RequestPromptChange
  /** Retry ordinal scheduled after a failed ordinary request. */
  retry?: number
  maxRetries?: number
  retryDelayMs?: number
}

/** One compaction provider request, either turn-owned or standalone between turns. */
interface CompactionRequestView extends RequestViewBase {
  purpose: 'compaction'
  /** Owning turn, or `null` when manual compaction ran between turns. */
  turn: number | null
  /** Direct compaction requests do not consume an agent-loop step. */
  step: 0
  /** Compaction replacement message sequence, when one was committed. */
  replacementSeq?: number
  /** Safe compaction summary projection. */
  summary?: readonly ContentBlock[]
  /** Complete compaction provider output before the safe projection. */
  rawOutput?: readonly ContentBlock[]
}

/** One provider request assembled from durable request lifecycle events. */
export type RequestView = AssistantRequestView | CompactionRequestView

/** Request data consumed by the stage-oriented Trajectory layout. */
export interface RequestInspectionSnapshot {
  requests: readonly RequestView[]
  callSchemas: ReadonlyMap<string, ToolSchema>
}
