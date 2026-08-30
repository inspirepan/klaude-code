import { describe, expect, it } from 'vitest'
import { decodeUsage, toAssistantTiming, toUsageLike } from './usage.ts'
import { readTime } from './json.ts'
import { stamp, stampMs, usage } from './fixtures.ts'

describe('usage mapping', () => {
  it('turns inclusive klaude counts into the panel\'s disjoint buckets', () => {
    const decoded = decodeUsage(usage({
      input_tokens: 16_891,
      cached_tokens: 16_384,
      cache_write_tokens: 100,
      reasoning_tokens: 143,
      output_tokens: 416,
    }))
    expect(decoded).toBeDefined()
    const buckets = toUsageLike(decoded!)
    // "Other" is the uncached remainder, so the panel's
    // Input = input + cacheRead + cacheWrite reproduces the recorded total.
    expect(buckets).toEqual({
      inputTokens: 407,
      cacheReadTokens: 16_384,
      cacheWriteTokens: 100,
      outputTokens: 416,
      reasoningTokens: 143,
    })
    const total = (buckets.inputTokens ?? 0)
      + (buckets.cacheReadTokens ?? 0)
      + (buckets.cacheWriteTokens ?? 0)
    expect(total).toBe(16_891)
    // Output stays inclusive: the panel prints Content = output - reasoning.
    expect((buckets.outputTokens ?? 0) - (buckets.reasoningTokens ?? 0)).toBe(273)
  })

  it('normalizes the Anthropic-Bedrock exception with max()', () => {
    const decoded = decodeUsage(usage({
      input_tokens: 500,
      cached_tokens: 16_000,
      cache_write_tokens: 0,
      output_tokens: 20,
    }))
    const buckets = toUsageLike(decoded!)
    expect(buckets.cacheReadTokens).toBe(16_000)
    // max(500, 16000) - 16000 - 0: never negative.
    expect(buckets.inputTokens).toBe(0)
  })

  it('omits empty cache and reasoning buckets', () => {
    const buckets = toUsageLike(decodeUsage(usage())!)
    expect(buckets).toEqual({ inputTokens: 1000, outputTokens: 100 })
  })

  it('falls back to a CacheHitRateEntry count only when nothing was reported', () => {
    const decoded = decodeUsage(usage({ input_tokens: 20_000, cached_tokens: 0 }))!
    expect(toUsageLike(decoded, 16_384).cacheReadTokens).toBe(16_384)
    const reported = decodeUsage(usage({ input_tokens: 20_000, cached_tokens: 19_000 }))!
    expect(toUsageLike(reported, 3).cacheReadTokens).toBe(19_000)
  })

  it('derives assistant timing from the request start plus TTFT', () => {
    const decoded = decodeUsage(usage({
      created_at: stamp(0),
      first_token_latency_ms: 2644.75,
    }))!
    const timing = toAssistantTiming(decoded, stampMs(5_000))
    expect(timing).toEqual({
      stepStartTime: stampMs(0),
      firstTokenTime: stampMs(0) + 2644.75,
      completedTime: stampMs(5_000),
    })
  })

  it('reports no timing when the line carried no usage', () => {
    expect(toAssistantTiming(undefined, 1)).toBeUndefined()
  })
})

describe('timestamps', () => {
  it('reads python microsecond stamps as local wall-clock time', () => {
    expect(readTime(stamp(1_500))).toBe(stampMs(1_500))
  })

  it('returns null for missing or unparsable stamps', () => {
    expect(readTime(undefined)).toBeNull()
    expect(readTime('not a date')).toBeNull()
  })
})
