import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionSearchMatch } from '../adapter/index.ts'
import {
  MAX_JUMP_PAGES, SEARCH_DEBOUNCE_MS, createSearchRunner, pagesToReachLine,
  partitionSearchMatches, walkToLine,
} from './search.ts'

function match(line: number): SessionSearchMatch {
  return {
    line_index: line,
    turn_index: 1,
    kind: 'UserMessage',
    status: 'active',
    snippet: `line ${line}`,
  }
}

/** A lookup whose answers are resolved by hand, one deferred promise per call. */
function deferredLookup() {
  const calls: {
    query: string
    signal: AbortSignal
    resolve: (value: string) => void
    reject: (reason: Error) => void
  }[] = []
  const run = (query: string, signal: AbortSignal): Promise<string> =>
    new Promise<string>((resolve, reject) => { calls.push({ query, signal, resolve, reject }) })
  return { calls, run }
}

describe('createSearchRunner', () => {
  afterEach(() => { vi.useRealTimers() })

  it('fires once per pause, not once per keystroke', () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const results: [string, string | null][] = []
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: (query, result) => { results.push([query, result]) },
    })
    runner.request('t')
    runner.request('to')
    runner.request('too')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1)
    expect(lookup.calls).toHaveLength(0)
    vi.advanceTimersByTime(1)
    expect(lookup.calls.map(call => call.query)).toEqual(['too'])
    expect(results).toEqual([])
    runner.dispose()
  })

  it('repeating the current query does not fire again', () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: () => {},
    })
    runner.request('tool')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    runner.request('tool')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    expect(lookup.calls).toHaveLength(1)
    runner.dispose()
  })

  it('aborts the in-flight request and drops its answer when the query moves on', async () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const results: [string, string | null][] = []
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: (query, result) => { results.push([query, result]) },
    })
    runner.request('foo')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    const first = lookup.calls[0]
    expect(first?.signal.aborted).toBe(false)
    runner.request('foobar')
    expect(first?.signal.aborted).toBe(true)
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    // The stale answer lands after the fresh one was requested: it is dropped.
    first?.resolve('stale')
    lookup.calls[1]?.resolve('fresh')
    await vi.advanceTimersByTimeAsync(0)
    expect(results).toEqual([['foobar', 'fresh']])
    runner.dispose()
  })

  it('reports a rejection as "no result" rather than failing', async () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const results: [string, string | null][] = []
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: (query, result) => { results.push([query, result]) },
    })
    runner.request('q')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    lookup.calls[0]?.reject(new Error('422 Unprocessable Entity'))
    await vi.advanceTimersByTimeAsync(0)
    expect(results).toEqual([['q', null]])
    runner.dispose()
  })

  it('clears at once on an empty query and asks nothing', () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const results: [string, string | null][] = []
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: (query, result) => { results.push([query, result]) },
    })
    runner.request('gone')
    runner.request('')
    expect(results).toEqual([['', null]])
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS * 2)
    expect(lookup.calls).toHaveLength(0)
    runner.dispose()
  })

  it('stops reporting after dispose', async () => {
    vi.useFakeTimers()
    const lookup = deferredLookup()
    const results: [string, string | null][] = []
    const runner = createSearchRunner<string>({
      run: lookup.run,
      onResult: (query, result) => { results.push([query, result]) },
    })
    runner.request('q')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    runner.dispose()
    lookup.calls[0]?.resolve('late')
    await vi.advanceTimersByTimeAsync(0)
    expect(results).toEqual([])
    expect(lookup.calls[0]?.signal.aborted).toBe(true)
  })
})

describe('partitionSearchMatches', () => {
  it('splits on the oldest loaded line', () => {
    const partition = partitionSearchMatches([match(3), match(11), match(40)], 11)
    expect(partition.unloaded.map(hit => hit.line_index)).toEqual([3])
    expect(partition.loaded.map(hit => hit.line_index)).toEqual([11, 40])
    expect(partition.earliestUnloadedLine).toBe(3)
  })

  it('treats an empty window as "nothing loaded"', () => {
    const partition = partitionSearchMatches([match(2), match(5)], null)
    expect(partition.unloaded).toHaveLength(2)
    expect(partition.loaded).toHaveLength(0)
    expect(partition.earliestUnloadedLine).toBe(2)
  })

  it('reports no unloaded line when the window covers every hit', () => {
    const partition = partitionSearchMatches([match(12), match(13)], 4)
    expect(partition.unloaded).toHaveLength(0)
    expect(partition.earliestUnloadedLine).toBeNull()
  })

  it('has nothing to split when the server found nothing', () => {
    expect(partitionSearchMatches([], 10).earliestUnloadedLine).toBeNull()
  })
})

describe('pagesToReachLine', () => {
  it('counts whole pages back to the target', () => {
    expect(pagesToReachLine(500, 499, 500)).toBe(1)
    expect(pagesToReachLine(500, 0, 500)).toBe(1)
    expect(pagesToReachLine(1000, 0, 500)).toBe(2)
    expect(pagesToReachLine(1001, 0, 500)).toBe(3)
  })

  it('is zero when the line is already loaded, or nothing is', () => {
    expect(pagesToReachLine(10, 10, 500)).toBe(0)
    expect(pagesToReachLine(10, 40, 500)).toBe(0)
    expect(pagesToReachLine(null, 3, 500)).toBe(0)
  })

  it('cannot divide by an empty page', () => {
    expect(pagesToReachLine(500, 0, 0)).toBe(0)
  })

  it('caps a walk at a page count a user can wait through', () => {
    expect(MAX_JUMP_PAGES).toBeGreaterThan(0)
    expect(MAX_JUMP_PAGES).toBeLessThanOrEqual(50)
  })
})

describe('walkToLine', () => {
  /** A window that a scripted `loadOlder` walks back 10 lines at a time. */
  function stepping(start: number, floor: number, step = 10) {
    let first = start
    const window = () => ({
      rows: [{ line_index: first }],
      hasMore: first > floor,
    })
    const loadOlder = vi.fn(() => {
      first = Math.max(floor, first - step)
      return Promise.resolve(true)
    })
    return { window, loadOlder, at: () => first }
  }

  it('stops as soon as the line is inside the window', async () => {
    const walk = stepping(100, 0)
    const outcome = await walkToLine({ targetLine: 82, window: walk.window, loadOlder: walk.loadOlder })
    expect(outcome).toEqual({ reached: true, pages: 2 })
    expect(walk.at()).toBe(80)
  })

  it('loads nothing when the line is already loaded', async () => {
    const walk = stepping(100, 0)
    const outcome = await walkToLine({ targetLine: 100, window: walk.window, loadOlder: walk.loadOlder })
    expect(outcome).toEqual({ reached: true, pages: 0 })
    expect(walk.loadOlder).not.toHaveBeenCalled()
  })

  it('gives up at the page cap without reaching the line', async () => {
    const walk = stepping(1000, 0)
    const outcome = await walkToLine({
      targetLine: 0,
      window: walk.window,
      loadOlder: walk.loadOlder,
      maxPages: 3,
    })
    expect(outcome).toEqual({ reached: false, pages: 3 })
    expect(walk.at()).toBe(970)
  })

  it('stops when a page fails to move the window', async () => {
    const loadOlder = vi.fn(() => Promise.resolve(false))
    const outcome = await walkToLine({
      targetLine: 0,
      window: () => ({ rows: [{ line_index: 50 }], hasMore: true }),
      loadOlder,
    })
    expect(outcome).toEqual({ reached: false, pages: 1 })
    expect(loadOlder).toHaveBeenCalledTimes(1)
  })

  it('stops when the session has nothing older', async () => {
    const loadOlder = vi.fn(() => Promise.resolve(false))
    const outcome = await walkToLine({
      targetLine: 0,
      window: () => ({ rows: [{ line_index: 4 }], hasMore: false }),
      loadOlder,
    })
    expect(outcome).toEqual({ reached: false, pages: 0 })
    expect(loadOlder).not.toHaveBeenCalled()
  })

  it('walks at most MAX_JUMP_PAGES by default', async () => {
    const walk = stepping(10_000, 0)
    const outcome = await walkToLine({ targetLine: 0, window: walk.window, loadOlder: walk.loadOlder })
    expect(outcome.pages).toBe(MAX_JUMP_PAGES)
    expect(outcome.reached).toBe(false)
  })
})
