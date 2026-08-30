/**
 * klaude: the `#/fixture` route has to keep rendering with no server running —
 * it is the only way to eyeball the ledger offline, and the D1 timeline
 * scroller mounts inside it (here with an unmeasured, zero-width track).
 * @vitest-environment jsdom
 */

import { expect, it } from 'vitest'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { StrictMode } from 'react'
import { FIXTURE_SNAPSHOT } from './fixture.ts'
import { renderImages } from './render-images.tsx'
import { t } from '../locale.ts'
import { TrajectoryView } from '../trajectory/TrajectoryView.tsx'

it('mounts the fixture trajectory', () => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  act(() => {
    root.render(<StrictMode><TrajectoryView
      snapshot={FIXTURE_SNAPSHOT}
      session={{ openState: 'open', loadingOlder: false, hasMore: false }}
      actualDuration={false}
      setActualDuration={() => {}}
      loadOlder={() => Promise.resolve(false)}
      renderImages={renderImages}
      t={t}
    /></StrictMode>)
  })
  expect(host.querySelector('[data-timeline-scroller]')).not.toBeNull()
  expect(host.querySelectorAll('[data-timeline-record-index]').length).toBeGreaterThan(0)
  act(() => { root.unmount() })
})
