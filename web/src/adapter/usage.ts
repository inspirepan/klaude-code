/**
 * klaude `Usage` -> the token buckets the vendored inspector renders.
 *
 * klaude's counts are **inclusive** (AGENTS.md "Usage Model Semantics"):
 * `input_tokens` is the whole prompt and already contains `cached_tokens +
 * cache_write_tokens`; `output_tokens` already contains `reasoning_tokens`.
 * The upstream Usage panel is disjoint on the input side — it prints
 * `Input = input + cacheRead + cacheWrite`, then `Cached = cacheRead`,
 * `Cache created = cacheWrite`, `Other = input` (`TrajectoryTable.tsx`
 * `inputTotal` / `UsageRows`) — so `inputTokens` must carry the *uncached*
 * remainder. The output side is already inclusive upstream (`Content = output -
 * reasoning`), so `output_tokens` and `reasoning_tokens` pass through.
 *
 * Anthropic-Bedrock reports `input_tokens` *excluding* the cache buckets, so
 * the real prompt total is `max(input_tokens, cached + cache_write)`; the
 * remainder is computed from that total and can never go negative.
 */

import { readNumber, readRecord, readTime } from './json.ts'

/** Token buckets `layout.ts` copies onto a cell (its private `UsageLike`). */
export interface UsageLike {
  readonly inputTokens?: number
  readonly cacheReadTokens?: number
  readonly cacheWriteTokens?: number
  readonly outputTokens?: number
  readonly reasoningTokens?: number
}

/** The `Usage` fields the ledger reads, already decoded. */
export interface KlaudeUsage {
  readonly inputTokens: number
  readonly cachedTokens: number
  readonly cacheWriteTokens: number
  readonly reasoningTokens: number
  readonly outputTokens: number
  readonly modelName: string | undefined
  readonly provider: string | undefined
  readonly maxTokens: number | undefined
  readonly responseId: string | undefined
  readonly firstTokenLatencyMs: number | undefined
  readonly taskDurationSeconds: number | undefined
  readonly throughputTps: number | undefined
  /** Request start (`llm/usage.py` stamps it before the call). */
  readonly createdAt: number | null
}

/**
 * Decode one persisted `Usage` payload.
 * @param value - `data.usage` from an AssistantMessage line.
 * @returns The decoded usage, or undefined when the line carried none.
 */
export function decodeUsage(value: unknown): KlaudeUsage | undefined {
  const usage = readRecord(value)
  if (usage === undefined) return undefined
  return {
    inputTokens: readNumber(usage.input_tokens) ?? 0,
    cachedTokens: readNumber(usage.cached_tokens) ?? 0,
    cacheWriteTokens: readNumber(usage.cache_write_tokens) ?? 0,
    reasoningTokens: readNumber(usage.reasoning_tokens) ?? 0,
    outputTokens: readNumber(usage.output_tokens) ?? 0,
    modelName: emptyToUndefined(usage.model_name),
    provider: emptyToUndefined(usage.provider),
    maxTokens: readNumber(usage.max_tokens),
    responseId: emptyToUndefined(usage.response_id),
    firstTokenLatencyMs: readNumber(usage.first_token_latency_ms),
    taskDurationSeconds: readNumber(usage.task_duration_s),
    throughputTps: readNumber(usage.throughput_tps),
    createdAt: readTime(usage.created_at),
  }
}

function emptyToUndefined(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined
}

/**
 * Convert inclusive klaude counts into the disjoint buckets the panel prints.
 * @param usage - Decoded klaude usage.
 * @param cachedFallback - `CacheHitRateEntry.cached_tokens` for the same
 *   request, used only when the provider reported no cached tokens at all.
 * @returns Token buckets; empty buckets are omitted so the panel skips them.
 */
export function toUsageLike(
  usage: KlaudeUsage,
  cachedFallback?: number,
): UsageLike {
  const cacheRead = usage.cachedTokens > 0
    ? usage.cachedTokens
    : Math.max(0, cachedFallback ?? 0)
  const cacheWrite = Math.max(0, usage.cacheWriteTokens)
  const promptTotal = Math.max(usage.inputTokens, cacheRead + cacheWrite)
  const uncached = Math.max(0, promptTotal - cacheRead - cacheWrite)
  return {
    inputTokens: uncached,
    ...(cacheRead > 0 ? { cacheReadTokens: cacheRead } : {}),
    ...(cacheWrite > 0 ? { cacheWriteTokens: cacheWrite } : {}),
    outputTokens: usage.outputTokens,
    ...(usage.reasoningTokens > 0 ? { reasoningTokens: usage.reasoningTokens } : {}),
  }
}

/**
 * Recorded request boundaries for one assistant message.
 * @param usage - Decoded klaude usage, or undefined when the line has none.
 * @param completedTime - `AssistantMessage.created_at` in epoch ms.
 * @returns The upstream `AssistantTiming`, or undefined when nothing was recorded.
 */
export function toAssistantTiming(
  usage: KlaudeUsage | undefined,
  completedTime: number,
): { stepStartTime: number | null; firstTokenTime: number | null; completedTime: number } | undefined {
  if (usage === undefined) return undefined
  const stepStartTime = usage.createdAt
  const firstTokenTime = stepStartTime !== null && usage.firstTokenLatencyMs !== undefined
    ? stepStartTime + usage.firstTokenLatencyMs
    : null
  if (stepStartTime === null && firstTokenTime === null) return undefined
  return { stepStartTime, firstTokenTime, completedTime }
}
