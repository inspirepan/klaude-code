/**
 * The session list at `#/`: the per-row message count, and the sub-agent type
 * and description a child row borrows from its parent's ledger.
 * @vitest-environment jsdom
 */

import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { SessionList } from './SessionList.tsx'

const PARENT = 'parent01abcdef'
const CHILD = 'child001abcdef'
/** `updated_at` is epoch seconds on the list endpoint. */
const T0 = 1_800_000_000

const SESSIONS = [
  {
    id: PARENT,
    title: 'fix the loader',
    agent_type: 'main',
    work_dir: '/w/klaude-code',
    model: 'opus',
    state: 'completed',
    updated_at: T0,
    messages_count: 198,
  },
  {
    id: CHILD,
    parent_session_id: PARENT,
    agent_type: 'code-reviewer',
    spawn_kind: 'subagent',
    state: 'completed',
    updated_at: T0 - 10,
    messages_count: 12,
  },
]

const CHILDREN = [
  {
    session_id: CHILD,
    sub_agent_type: 'code-reviewer',
    sub_agent_desc: 'review the loader change',
    model: 'sonnet',
    created_at: '2026-08-30T10:00:00',
    line_index: 3,
  },
]

let host: HTMLDivElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>
let childrenAnswer: () => Promise<Response>

function answer(payload: unknown): Response {
  return { ok: true, status: 200, statusText: 'OK', json: () => Promise.resolve(payload) } as Response
}

beforeAll(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

beforeEach(() => {
  vi.useFakeTimers()
  childrenAnswer = () => Promise.resolve(answer({ session_id: PARENT, children: CHILDREN }))
  fetchMock = vi.fn((input: unknown) => {
    const url = String(input)
    if (url.startsWith('/api/headless/sessions')) return Promise.resolve(answer({ sessions: SESSIONS }))
    if (url.endsWith('/children')) return childrenAnswer()
    return Promise.reject(new Error(`unexpected request: ${url}`))
  })
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

/** Mount and let the first poll land. */
async function mount(): Promise<void> {
  act(() => { root.render(<SessionList />) })
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

function rows(): HTMLLIElement[] {
  return [...host.querySelectorAll('li')]
}

/** Open the one parent on the page and let its `/children` request land. */
async function expandParent(): Promise<void> {
  const toggle = host.querySelector<HTMLButtonElement>('button[aria-label="Expand sub-agent sessions"]')
  expect(toggle).not.toBeNull()
  act(() => { toggle?.click() })
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

function childrenCalls(): string[] {
  return fetchMock.mock.calls.map(call => String(call[0])).filter(url => url.endsWith('/children'))
}

it('shows every row its message count, and nothing for an unknown one', async () => {
  await mount()

  expect(rows()).toHaveLength(1)
  expect(rows()[0]?.textContent).toContain('198 条')

  await expandParent()
  expect(rows()[1]?.textContent).toContain('12 条')
})

it('asks for the children only once the parent is open', async () => {
  await mount()
  expect(childrenCalls()).toEqual([])

  await expandParent()
  expect(childrenCalls()).toEqual([`/api/web/sessions/${PARENT}/children`])

  // The 5 s poll must not re-ask: spawn rows never change once written.
  await act(async () => { await vi.advanceTimersByTimeAsync(11_000) })
  expect(childrenCalls()).toHaveLength(1)
})

it('labels a child row with its type and the description the parent gave', async () => {
  await mount()
  await expandParent()

  const child = rows()[1]
  expect(child?.textContent).toContain('code-reviewer')
  expect(child?.textContent).toContain('review the loader change')
  expect(child?.querySelector('a')?.getAttribute('href')).toBe(`#/s/${CHILD}`)
  // The parent is not a sub-agent, so it carries no type badge.
  expect(rows()[0]?.textContent).not.toContain('main')
})

it('falls back to the short id when the children request fails', async () => {
  childrenAnswer = () => Promise.reject(new Error('Failed to fetch'))
  await mount()
  await expandParent()

  const child = rows()[1]
  expect(child?.textContent).toContain(CHILD.slice(0, 8))
  expect(child?.textContent).not.toContain('review the loader change')
  // The type still shows: it comes off the child's own meta.
  expect(child?.textContent).toContain('code-reviewer')
})
