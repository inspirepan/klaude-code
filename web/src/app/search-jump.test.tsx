/**
 * The two hooks M5 asks of the vendored view, end to end:
 * the toolbar's live-filter query comes out, and a ledger line goes in and
 * scrolls its row into view once the page holding it lands.
 * @vitest-environment jsdom
 */

import { afterEach, beforeAll, beforeEach, expect, it } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import type { HistoryRow } from '../adapter/index.ts'
import { buildTrajectorySnapshot } from '../adapter/index.ts'
import { row, stamp } from '../adapter/fixtures.ts'
import type { TrajectoryLineFocus } from '../adapter/index.ts'
import { t } from '../locale.ts'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'
import { renderImages } from './render-images.tsx'

const SESSION = 'sess1'
const OLD_TEXT = 'the needle in the unloaded page'

/** Six lines: three "older" ones, then the tail the page opens on. */
const ROWS: readonly HistoryRow[] = [
  row(0, 'UserMessage', { parts: [{ type: 'text', text: OLD_TEXT }], created_at: stamp(0) }),
  row(1, 'AssistantMessage', {
    response_id: 'r1',
    parts: [{ type: 'text', text: 'an old answer' }],
    created_at: stamp(1000),
  }),
  row(2, 'UserMessage', { parts: [{ type: 'text', text: 'tail question' }], created_at: stamp(2000) }),
  row(3, 'AssistantMessage', {
    response_id: 'r2',
    parts: [{ type: 'text', text: 'tail answer' }],
    created_at: stamp(3000),
  }),
]

const TAIL = ROWS.slice(2)

let host: HTMLDivElement
let root: Root
let scrolled: HTMLElement[]

beforeAll(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

beforeEach(() => {
  scrolled = []
  // jsdom has no scrollIntoView; the vendored table feature-detects it.
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: function scrollIntoView(this: HTMLElement) { scrolled.push(this) },
  })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => { root.unmount() })
  host.remove()
})

function render(
  rows: readonly HistoryRow[],
  options: {
    hasMore: boolean
    focus?: TrajectoryLineFocus | null
    onSearchQueryChange?: (query: string) => void
  },
): void {
  act(() => {
    root.render(<TrajectoryView
      snapshot={buildTrajectorySnapshot(rows, { sessionId: SESSION, translate: t })}
      session={{ openState: 'open', loadingOlder: false, hasMore: options.hasMore }}
      actualDuration={false}
      setActualDuration={() => {}}
      loadOlder={() => Promise.resolve(false)}
      renderImages={renderImages}
      t={t}
      onSearchQueryChange={options.onSearchQueryChange ?? (() => {})}
      focusRecordLine={options.focus ?? null}
    />)
  })
}

/** Type into a controlled React input the way the browser would. */
function type(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  setter?.call(input, value)
  act(() => { input.dispatchEvent(new Event('input', { bubbles: true })) })
}

it('mirrors the live-filter query out to the host', () => {
  const seen: string[] = []
  render(TAIL, { hasMore: true, onSearchQueryChange: (query) => { seen.push(query) } })
  const input = host.querySelector<HTMLInputElement>('input[type="search"]')
  expect(input).not.toBeNull()
  if (input === null) return
  type(input, 'needle')
  expect(seen).toEqual(['needle'])
  // The vendored filter still owns the query: the box shows what was typed.
  expect(input.value).toBe('needle')
})

it('scrolls to the jump target in the commit its page lands', () => {
  const command: TrajectoryLineFocus = { line: 0 }
  // The command is issued while line 0 is still unloaded: nothing to scroll to.
  render(TAIL, { hasMore: true, focus: command })
  expect(scrolled).toHaveLength(0)
  // The walk prepended the older page; the same commit carries both.
  render(ROWS, { hasMore: false, focus: command })
  expect(scrolled).toHaveLength(1)
  expect(scrolled[0]?.tagName).toBe('TR')
  expect(scrolled[0]?.textContent).toContain(OLD_TEXT)
})

it('scrolls once per command, not once per render', () => {
  const command: TrajectoryLineFocus = { line: 0 }
  render(TAIL, { hasMore: true, focus: command })
  render(ROWS, { hasMore: false, focus: command })
  expect(scrolled).toHaveLength(1)
  render(ROWS, { hasMore: false, focus: command })
  expect(scrolled).toHaveLength(1)
})

it('leaves the ledger alone without a command', () => {
  render(TAIL, { hasMore: true })
  render(ROWS, { hasMore: false })
  expect(scrolled).toHaveLength(0)
})
