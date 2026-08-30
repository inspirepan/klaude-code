/**
 * The server-search bar: when it appears, what it says, and what the jump
 * button asks the page to load.
 * @vitest-environment jsdom
 */

import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import type { SessionSearchResult } from '../adapter/index.ts'
import { t } from '../locale.ts'
import { SearchBar } from './SearchBar.tsx'
import { SEARCH_DEBOUNCE_MS, type SearchJumpOutcome } from './search.ts'

const SESSION = 'sess1'

function result(lines: readonly number[], extra: Partial<SessionSearchResult> = {}) {
  return {
    session_id: SESSION,
    query: 'tool',
    terms: ['tool'],
    matches: lines.map(line => ({
      line_index: line,
      turn_index: 1,
      kind: 'AssistantMessage',
      status: 'active' as const,
      snippet: `tool at ${line}`,
    })),
    total: lines.length,
    truncated: false,
    ...extra,
  }
}

let host: HTMLDivElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function answer(payload: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 422,
    statusText: ok ? 'OK' : 'Unprocessable Entity',
    json: () => Promise.resolve(payload),
  } as Response
}

beforeAll(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

beforeEach(() => {
  vi.useFakeTimers()
  fetchMock = vi.fn(() => Promise.resolve(answer(result([4, 9, 120]))))
  vi.stubGlobal('fetch', fetchMock)
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => { root.unmount() })
  host.remove()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

interface BarState {
  query: string
  firstLoadedLine: number | null
  hasMore: boolean
  onLoadUntilLine?: (line: number) => Promise<SearchJumpOutcome>
}

function render(state: BarState): void {
  act(() => {
    root.render(<SearchBar
      sessionId={SESSION}
      query={state.query}
      firstLoadedLine={state.firstLoadedLine}
      hasMore={state.hasMore}
      onLoadUntilLine={state.onLoadUntilLine
        ?? (() => Promise.resolve({ reached: true, pages: 1 }))}
      t={t}
    />)
  })
}

/** Render, then let the debounce fire and the answer land. */
async function settle(state: BarState): Promise<void> {
  render(state)
  await act(async () => { await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS) })
}

function bar(): HTMLElement | null {
  return host.querySelector<HTMLElement>('[aria-label="服务端搜索"]')
}

function button(): HTMLButtonElement | null {
  return host.querySelector('button')
}

it('stays quiet — and asks nothing — while the query is empty', async () => {
  await settle({ query: '   ', firstLoadedLine: 100, hasMore: true })
  expect(fetchMock).not.toHaveBeenCalled()
  expect(bar()).toBeNull()
})

it('asks nothing when the whole session is already loaded', async () => {
  await settle({ query: 'tool', firstLoadedLine: 0, hasMore: false })
  expect(fetchMock).not.toHaveBeenCalled()
  expect(bar()).toBeNull()
})

it('reports the matches above the window once the answer lands', async () => {
  await settle({ query: 'tool', firstLoadedLine: 100, hasMore: true })
  const url = String(fetchMock.mock.calls[0]?.[0])
  expect(url).toContain(`/api/web/sessions/${SESSION}/search?q=tool`)
  expect(bar()?.textContent).toContain('更早历史中还有 2 条匹配（共 3 条）')
  expect(button()?.textContent).toBe('加载到最早匹配')
})

it('says nothing when every hit is already on screen', async () => {
  await settle({ query: 'tool', firstLoadedLine: 0, hasMore: true })
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(bar()).toBeNull()
})

it('treats a 422 as "no server information" and keeps out of the way', async () => {
  fetchMock.mockResolvedValue(answer({ detail: 'q must contain at least one search term' }, false))
  await settle({ query: 'tool', firstLoadedLine: 100, hasMore: true })
  expect(bar()).toBeNull()
})

it('treats an offline server the same way', async () => {
  fetchMock.mockRejectedValue(new Error('Failed to fetch'))
  await settle({ query: 'tool', firstLoadedLine: 100, hasMore: true })
  expect(bar()).toBeNull()
})

it('says how many pages the jump will walk when it is more than one', async () => {
  await settle({ query: 'tool', firstLoadedLine: 2000, hasMore: true })
  expect(bar()?.textContent).toContain('约 4 页')
})

it('warns when the server had more hits than it returned', async () => {
  fetchMock.mockResolvedValue(answer(result([4, 9, 120], { total: 900, truncated: true })))
  await settle({ query: 'tool', firstLoadedLine: 100, hasMore: true })
  expect(bar()?.textContent).toContain('服务端最多返回 3 条，可能还有更多')
})

it('loads down to the earliest unloaded match, then disappears', async () => {
  const asked: number[] = []
  const state: BarState = {
    query: 'tool',
    firstLoadedLine: 100,
    hasMore: true,
    onLoadUntilLine: (line) => {
      asked.push(line)
      return Promise.resolve({ reached: true, pages: 1 })
    },
  }
  await settle(state)
  await act(async () => {
    button()?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  expect(asked).toEqual([4])
  // The page prepended the older rows; the window now covers every hit.
  render({ ...state, firstLoadedLine: 0 })
  expect(bar()).toBeNull()
})

it('offers a continuation when the walk hit its page cap', async () => {
  let release: ((outcome: SearchJumpOutcome) => void) | undefined
  await settle({
    query: 'tool',
    firstLoadedLine: 100,
    hasMore: true,
    onLoadUntilLine: () => new Promise<SearchJumpOutcome>((resolve) => { release = resolve }),
  })
  await act(async () => {
    button()?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  expect(bar()?.textContent).toContain('已加载到第 100 行…')
  expect(button()?.disabled).toBe(true)
  await act(async () => { release?.({ reached: false, pages: 20 }) })
  expect(button()?.textContent).toBe('继续加载')
  expect(bar()?.textContent).toContain('一次最多加载 20 页，还没到最早匹配')
})
