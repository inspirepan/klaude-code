/**
 * klaude: UX spec D1 — the rendered track is a horizontal scroller whose content
 * layer is wider than the container once the session outgrows it.
 * @vitest-environment jsdom
 */

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { TrajectoryTimeline } from './TrajectoryTimeline.tsx'
import type { TrajectoryTurnModel } from './layout.ts'
import type { TrajectoryTranslate } from './locales.ts'
import { TIMELINE_PX_PER_RECORD } from './timeline.ts'

const CONTAINER_WIDTH = 640
const RECORD_COUNT = 500

const translate: TrajectoryTranslate = key => key

function isTrack(element: Element): boolean {
  return element.hasAttribute('data-timeline-scroller')
}

function turnsWith(count: number): readonly TrajectoryTurnModel[] {
  return [{
    turn: 1,
    groups: [{
      title: 'Step 1',
      cells: Array.from({ length: count }, (_, offset) => ({
        index: offset + 1,
        kind: 'tool' as const,
        text: `call ${offset + 1}`,
        timeSeconds: 0.1,
      })),
    }],
  }]
}

// jsdom has no CSSOM worth asking, and vitest hands `.module.css` imports a
// class-name proxy, so the rules are read as text.
// Project-root relative: vitest runs from `web/`, and under the jsdom
// environment `import.meta.url` resolves against jsdom's own document base
// rather than the file system.
const stylesheet = readFileSync(
  'src/trajectory/TrajectoryTimeline.module.css',
  'utf8',
)

function rule(name: string): string {
  return new RegExp(`\\.${name} \\{([^}]*)\\}`).exec(stylesheet)?.[1] ?? ''
}

let host: HTMLDivElement | null = null
let root: Root | null = null

beforeAll(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  // jsdom does no layout: the track reports the width the strip would have.
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get(this: HTMLElement) { return isTrack(this) ? CONTAINER_WIDTH : 0 },
  })
  HTMLElement.prototype.getBoundingClientRect = function getRect(this: HTMLElement) {
    const width = isTrack(this) ? CONTAINER_WIDTH : 0
    return {
      bottom: 50, height: 50, left: 0, right: width, toJSON: () => ({}),
      top: 0, width, x: 0, y: 0,
    }
  }
})

afterAll(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = false
})

afterEach(() => {
  if (root !== null) act(() => { root?.unmount() })
  host?.remove()
  root = null
  host = null
})

function render(count: number): HTMLElement {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  const target = root
  act(() => {
    target.render(
      <TrajectoryTimeline
        t={translate}
        turns={turnsWith(count)}
        mode="sequence"
        range={null}
        onRangeChange={() => {}}
      />,
    )
  })
  const track = host.querySelector<HTMLElement>('[data-timeline-scroller]')
  expect(track).not.toBeNull()
  return track as HTMLElement
}

describe('TrajectoryTimeline scroller', () => {
  it('scrolls horizontally instead of clipping the domain into the container', () => {
    const track = rule('track')
    expect(track).toContain('overflow-x: auto')
    expect(track).toContain('overflow-y: hidden')
    // The content layers are sized by the width the component publishes.
    expect(rule('lanes')).toContain('width: var(--trajectory-content-width)')
    expect(rule('turnBoundaries')).toContain('width: var(--trajectory-content-width)')
  })

  it('lays the content out wider than the container for a large session', () => {
    const track = render(RECORD_COUNT)
    const contentWidth = RECORD_COUNT * TIMELINE_PX_PER_RECORD
    expect(contentWidth).toBeGreaterThan(CONTAINER_WIDTH)
    expect(track.style.getPropertyValue('--trajectory-content-width'))
      .toBe(`${contentWidth}px`)
    expect(track.querySelector('[data-timeline-content]')).not.toBeNull()
  })

  it('renders only the spans near the scrolled window', () => {
    const track = render(RECORD_COUNT)
    const rendered = track.querySelectorAll('[data-timeline-record-index]')
    expect(rendered.length).toBeGreaterThan(0)
    expect(rendered.length).toBeLessThan(RECORD_COUNT)
  })

  it('still fills the container when the session is short', () => {
    const track = render(20)
    expect(track.style.getPropertyValue('--trajectory-content-width'))
      .toBe(`${CONTAINER_WIDTH}px`)
    expect(track.querySelectorAll('[data-timeline-record-index]')).toHaveLength(20)
  })
})
