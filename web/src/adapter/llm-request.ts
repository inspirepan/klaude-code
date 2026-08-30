/**
 * `LLMRequestEntry` -> the request dot's data.
 *
 * klaude records one entry per LLM call made **outside** an agent step:
 * compaction, `/btw` and `/rewind`'s fork summary (`agent/llm_request.py`). A
 * main step needs none — `AssistantMessage.usage` already carries its timing
 * and tokens.
 *
 * Two rules from the wire contract shape everything here:
 *
 * - **Join by `request_id` only.** The entry is written immediately before the
 *   `CompactionEntry` / `SideQuestionEntry` / `ForkSummaryEntry` it describes,
 *   and that entry repeats the id. Never pair by position: one logical
 *   operation can issue several calls (`label` = `fork` / `summary` /
 *   `task_prefix` / `fallback`), and a failed call has no paired entry at all.
 * - **Absent means absent.** Entries are persisted with `exclude_none`, so
 *   `usage`, `options`, `first_token_at` and `error` are missing keys rather
 *   than nulls. An old session has no entry at all: everything stays unknown
 *   and nothing is ever rendered as `0`.
 */

import type { AssistantRequestConfig } from '../contract/index.ts'
import { readNumber, readRecord, readString, readTime } from './json.ts'
import { decodeUsage, type KlaudeUsage } from './usage.ts'

/** Outcome of one recorded call. */
export type LLMRequestStatus = 'completed' | 'error' | 'interrupted'

/** One decoded `LLMRequestEntry`. */
export interface LLMRequestRecord {
  readonly requestId: string
  /** Which operation issued the call. */
  readonly kind: string | undefined
  /** Which sub-call this was inside that operation, when it issued several. */
  readonly label: string | undefined
  readonly provider: string | undefined
  readonly model: string | undefined
  /** Effective model knobs, credential-free; absent on an unrecorded call. */
  readonly options: Record<string, unknown> | undefined
  readonly status: LLMRequestStatus
  readonly error: string | undefined
  readonly usage: KlaudeUsage | undefined
  readonly startedAt: number | null
  /** Absent when the call produced no streaming delta (no TTFT to report). */
  readonly firstTokenAt: number | null
  readonly completedAt: number | null
  readonly toolCallCount: number
}

function status(value: unknown): LLMRequestStatus {
  const text = readString(value)
  return text === 'error' || text === 'interrupted' ? text : 'completed'
}

/**
 * Decode one `LLMRequestEntry` payload.
 * @param data - `entry.data` of an `LLMRequestEntry` line.
 * @returns The record, or undefined when it carries no `request_id` (the one
 *   field the join needs).
 */
export function decodeLLMRequest(
  data: Record<string, unknown>,
): LLMRequestRecord | undefined {
  const requestId = readString(data.request_id)
  if (requestId === undefined || requestId === '') return undefined
  return {
    requestId,
    kind: readString(data.kind),
    label: readString(data.label),
    provider: readString(data.provider),
    model: readString(data.model),
    options: readRecord(data.options),
    status: status(data.status),
    error: readString(data.error),
    usage: decodeUsage(data.usage),
    startedAt: readTime(data.started_at),
    firstTokenAt: readTime(data.first_token_at),
    completedAt: readTime(data.completed_at),
    toolCallCount: readNumber(data.tool_call_count) ?? 0,
  }
}

/**
 * Recorded call knobs -> the Options tab's config.
 *
 * `options` is `safe_call_options()`: an `LLMCallParameter` dump minus the
 * payload (`input` / `system` / `tools`), the routing identity and every
 * credential field. Only the knobs the vendored `AssistantRequestConfig`
 * declares are carried across; `verbosity`, `cache_retention`, `fast_mode`,
 * `context_limit`, `supports_vision` and `cost` have no slot and are dropped
 * rather than renamed into one.
 * @param record - The decoded entry.
 * @returns The config, or undefined when the call recorded no `options` — the
 *   inspector then hides the Options tab instead of showing today's config.
 */
export function requestOptions(
  record: LLMRequestRecord,
): AssistantRequestConfig | undefined {
  const options = record.options
  if (options === undefined) return undefined
  const thinking = readRecord(options.thinking)
  const effort = readString(thinking?.reasoning_effort) ?? readString(options.effort)
  const temperature = readNumber(options.temperature)
  const maxTokens = readNumber(options.max_tokens)
  const purpose = record.label === undefined
    ? record.kind
    : record.kind === undefined ? record.label : `${record.kind} · ${record.label}`
  return {
    provider: record.provider ?? '',
    model: record.model ?? readString(options.model_id) ?? '',
    ...(purpose === undefined ? {} : { purpose }),
    ...(effort === undefined ? {} : { reasoningEffort: effort }),
    ...(temperature === undefined ? {} : { temperature }),
    ...(maxTokens === undefined ? {} : { maxTokens }),
    ...(thinking === undefined ? {} : { thinking: JSON.stringify(thinking) }),
  }
}
