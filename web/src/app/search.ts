/**
 * Server search over the lines the viewer has not loaded (plan decision #22).
 *
 * The vendored toolbar's search box is a **live filter over loaded rows** and
 * stays exactly that. This module only answers the question that filter cannot:
 * how many more matches sit above the loaded window, and how far back the
 * earliest one is. Nothing here touches React or the DOM — the bar
 * (`SearchBar.tsx`) is the only consumer.
 *
 * The server's searchable text is a subset of the client index, so a hit
 * reported here is guaranteed to also survive the live filter once its page is
 * on screen; the reverse does not hold, which is why the counts are phrased as
 * "at least this many".
 */

import type { SessionSearchMatch } from '../adapter/index.ts'

/** Keystroke-to-request delay; one request per pause, not per character. */
export const SEARCH_DEBOUNCE_MS = 300

/** Older pages one jump may walk before handing the user a "continue" button. */
export const MAX_JUMP_PAGES = 20

/** A debounced, abortable, stale-proof single-flight lookup. */
export interface SearchRunner {
  /**
   * Ask for `query`.
   *
   * Repeating the current query is a no-op (no second request, no flicker); an
   * empty query cancels everything and reports "no result" at once.
   */
  request: (query: string) => void
  /** Cancel the timer and any in-flight request; the runner stops reporting. */
  dispose: () => void
}

/** How a runner is built. */
export interface SearchRunnerOptions<T> {
  /** Debounce delay; defaults to {@link SEARCH_DEBOUNCE_MS}. */
  readonly delayMs?: number
  /** One lookup. Rejections (422, offline, abort) become a `null` result. */
  readonly run: (query: string, signal: AbortSignal) => Promise<T>
  /** Receives the answer for `query`, or null when there is none. */
  readonly onResult: (query: string, result: T | null) => void
}

/**
 * Build a runner that debounces, aborts and ignores stale answers.
 *
 * A query that is superseded while its request is in flight never reports:
 * the in-flight request is aborted *and* its settlement is dropped, so a slow
 * answer for `foo` can never overwrite a fresh answer for `foobar`.
 * @param options - Delay, the lookup, and the result sink.
 * @returns The runner; call `dispose` when the owner unmounts.
 */
export function createSearchRunner<T>(options: SearchRunnerOptions<T>): SearchRunner {
  const delay = options.delayMs ?? SEARCH_DEBOUNCE_MS
  let current: string | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let inFlight: AbortController | null = null
  let disposed = false

  const cancel = (): void => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    if (inFlight !== null) {
      inFlight.abort()
      inFlight = null
    }
  }

  return {
    request(query: string): void {
      if (disposed || query === current) return
      current = query
      cancel()
      if (query === '') {
        options.onResult(query, null)
        return
      }
      timer = setTimeout(() => {
        timer = null
        const controller = new AbortController()
        inFlight = controller
        void options.run(query, controller.signal).then(
          (result) => {
            if (disposed || current !== query) return
            inFlight = null
            options.onResult(query, result)
          },
          () => {
            if (disposed || current !== query) return
            inFlight = null
            options.onResult(query, null)
          },
        )
      }, delay)
    },
    dispose(): void {
      disposed = true
      cancel()
    },
  }
}

/** What one "load down to the earliest match" walk achieved. */
export interface SearchJumpOutcome {
  /** True when the target line is inside the window now. */
  readonly reached: boolean
  /** Older pages this walk actually fetched. */
  readonly pages: number
}

/** The window facts a jump walk reads; `LoadedWindow` satisfies it. */
export interface JumpWindow {
  readonly rows: readonly { readonly line_index: number }[]
  readonly hasMore: boolean
}

/** How one jump walk is driven. */
export interface JumpWalk {
  /** The line to bring into the window. */
  readonly targetLine: number
  /** Read the window as it is *now* — re-read after every page. */
  readonly window: () => JumpWindow
  /** Load one older page; the window must reflect it once this resolves. */
  readonly loadOlder: () => Promise<unknown>
  /** Page cap; defaults to {@link MAX_JUMP_PAGES}. */
  readonly maxPages?: number
}

/**
 * Load older pages until `targetLine` is inside the window.
 *
 * Stops on four conditions: the line landed, the session has no older rows,
 * the page cap ran out, or a page left the window where it was (a failed or
 * empty read — the caller has already surfaced the failure). The cap is what
 * turns a match thousands of pages back into a "continue" button instead of a
 * loop that holds the page hostage.
 * @param walk - Target, window reader, page loader and cap.
 * @returns Whether the line landed, and how many pages it took.
 */
export async function walkToLine(walk: JumpWalk): Promise<SearchJumpOutcome> {
  const cap = walk.maxPages ?? MAX_JUMP_PAGES
  const firstLine = (): number | undefined => walk.window().rows[0]?.line_index
  let pages = 0
  while (pages < cap) {
    const first = firstLine()
    if (first !== undefined && first <= walk.targetLine) break
    if (!walk.window().hasMore) break
    await walk.loadOlder()
    pages += 1
    if (firstLine() === first) break
  }
  const reached = (firstLine() ?? Number.POSITIVE_INFINITY) <= walk.targetLine
  return { reached, pages }
}

/** Server hits split against the loaded window. */
export interface SearchPartition {
  /** Hits above the window; the live filter cannot show these yet. */
  readonly unloaded: readonly SessionSearchMatch[]
  /** Hits the loaded rows already cover. */
  readonly loaded: readonly SessionSearchMatch[]
  /** Oldest unloaded hit's line, or null when there is none. */
  readonly earliestUnloadedLine: number | null
}

/**
 * Split server hits into "already on screen" and "still above the window".
 * @param matches - Hits ascending by `line_index`.
 * @param firstLoadedLine - Oldest loaded row's line; null when nothing loaded.
 * @returns The two groups plus the oldest unloaded line.
 */
export function partitionSearchMatches(
  matches: readonly SessionSearchMatch[],
  firstLoadedLine: number | null,
): SearchPartition {
  const unloaded = firstLoadedLine === null
    ? matches
    : matches.filter(match => match.line_index < firstLoadedLine)
  const loaded = firstLoadedLine === null
    ? []
    : matches.filter(match => match.line_index >= firstLoadedLine)
  return {
    unloaded,
    loaded,
    earliestUnloadedLine: unloaded[0]?.line_index ?? null,
  }
}

/**
 * How many older pages the window needs before `targetLine` is inside it.
 *
 * One page moves the window back by at most `pageLimit` lines, so this is the
 * best case; the loop still checks the real window after every page (a page
 * can come back short) and stops when the line is in.
 * @param firstLoadedLine - Oldest loaded row's line; null when nothing loaded.
 * @param targetLine - The line to reach.
 * @param pageLimit - Rows per history page.
 * @returns Page count, 0 when the line is already loaded.
 */
export function pagesToReachLine(
  firstLoadedLine: number | null,
  targetLine: number,
  pageLimit: number,
): number {
  if (firstLoadedLine === null || pageLimit <= 0) return 0
  const missing = firstLoadedLine - targetLine
  if (missing <= 0) return 0
  return Math.ceil(missing / pageLimit)
}
