/**
 * klaude: UX spec D1 — the timeline scroller's scale model.
 * Upstream had no equivalent (it fitted the whole domain into the container), so
 * these are all fork tests.
 */

import { describe, expect, it } from 'vitest'
import {
  timelineEarlierScrollLeft,
  timelineFollowsTail,
  timelineRevealScrollLeft,
  timelineScale,
  timelineZoomPxPerUnit,
  timelineZoomScrollLeft,
  TIMELINE_MINIMUM_ZOOM_RECORDS,
  TIMELINE_PX_PER_MS,
  TIMELINE_PX_PER_RECORD,
  TIMELINE_TAIL_FOLLOW_PX,
} from './timeline.ts'

const CONTAINER = 640

describe('timelineScale', () => {
  it('gives every record its own pixels once the domain outgrows the container', () => {
    const scale = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 500,
      mode: 'sequence',
      pxPerUnit: null,
    })
    expect(scale.pxPerUnit).toBe(TIMELINE_PX_PER_RECORD)
    expect(scale.contentWidth).toBe(500 * TIMELINE_PX_PER_RECORD)
    expect(scale.maxScrollLeft).toBe(500 * TIMELINE_PX_PER_RECORD - CONTAINER)
    expect(scale.visibleDuration).toBeCloseTo(CONTAINER / TIMELINE_PX_PER_RECORD)
  })

  it('stretches a short session to the container instead of leaving it stranded', () => {
    const scale = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 20,
      mode: 'sequence',
      pxPerUnit: null,
    })
    expect(scale.contentWidth).toBe(CONTAINER)
    expect(scale.maxScrollLeft).toBe(0)
    expect(scale.pxPerUnit).toBe(CONTAINER / 20)
  })

  it('opens a ten-minute session about two screens wide in duration mode', () => {
    const scale = timelineScale({
      containerWidth: 1_200,
      fullDuration: 10 * 60 * 1_000,
      mode: 'duration',
      pxPerUnit: null,
    })
    expect(scale.pxPerUnit).toBe(TIMELINE_PX_PER_MS)
    expect(scale.contentWidth).toBe(2_400)
    expect(scale.contentWidth / 1_200).toBe(2)
  })

  it('falls back to the raw scale before the track has been measured', () => {
    const scale = timelineScale({
      containerWidth: 0,
      fullDuration: 100,
      mode: 'sequence',
      pxPerUnit: null,
    })
    expect(scale.pxPerUnit).toBe(TIMELINE_PX_PER_RECORD)
    expect(scale.contentWidth).toBe(100 * TIMELINE_PX_PER_RECORD)
  })

  it('clamps a held zoom into the bounds the container implies', () => {
    const zoomedIn = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 500,
      mode: 'sequence',
      pxPerUnit: 10_000,
    })
    expect(zoomedIn.pxPerUnit).toBe(CONTAINER / TIMELINE_MINIMUM_ZOOM_RECORDS)
    const zoomedOut = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 500,
      mode: 'sequence',
      pxPerUnit: 0.001,
    })
    expect(zoomedOut.pxPerUnit).toBe(CONTAINER / 500)
    expect(zoomedOut.contentWidth).toBe(CONTAINER)
    expect(zoomedOut.maxScrollLeft).toBe(0)
  })

  it('lets a domain shorter than the zoom floor still fill the container', () => {
    const scale = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 2,
      mode: 'sequence',
      pxPerUnit: 10_000,
    })
    expect(scale.pxPerUnit).toBe(CONTAINER / 2)
    expect(scale.maximumPxPerUnit).toBe(scale.minimumPxPerUnit)
  })
})

describe('timelineZoomPxPerUnit', () => {
  const scale = timelineScale({
    containerWidth: CONTAINER,
    fullDuration: 500,
    mode: 'sequence',
    pxPerUnit: null,
  })

  it('zooms out on a positive wheel delta, as upstream did', () => {
    expect(timelineZoomPxPerUnit(scale, 120)).toBeLessThan(scale.pxPerUnit)
    expect(timelineZoomPxPerUnit(scale, -120)).toBeGreaterThan(scale.pxPerUnit)
  })

  it('uses the same exponent upstream applied to the domain duration', () => {
    // Upstream: nextDuration = duration * exp(deltaY * 0.0015). px per unit is
    // the reciprocal of the duration the container shows.
    expect(timelineZoomPxPerUnit(scale, -100))
      .toBeCloseTo(TIMELINE_PX_PER_RECORD / Math.exp(-100 * 0.0015), 10)
  })

  it('stops at "fits the container" when zooming out', () => {
    let pxPerUnit = scale.pxPerUnit
    for (let step = 0; step < 60; step += 1) {
      pxPerUnit = timelineZoomPxPerUnit({ ...scale, pxPerUnit }, 400)
    }
    expect(pxPerUnit).toBe(CONTAINER / 500)
  })

  it('stops with the zoom floor filling the container when zooming in', () => {
    let pxPerUnit = scale.pxPerUnit
    for (let step = 0; step < 60; step += 1) {
      pxPerUnit = timelineZoomPxPerUnit({ ...scale, pxPerUnit }, -400)
    }
    expect(pxPerUnit).toBe(CONTAINER / TIMELINE_MINIMUM_ZOOM_RECORDS)
  })
})

describe('timelineZoomScrollLeft', () => {
  it('keeps the record under the cursor under the cursor', () => {
    const before = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 500,
      mode: 'sequence',
      pxPerUnit: null,
    })
    const after = timelineScale({
      containerWidth: CONTAINER,
      fullDuration: 500,
      mode: 'sequence',
      pxPerUnit: timelineZoomPxPerUnit(before, -300),
    })
    const scrollLeft = 900
    const cursorOffset = 220
    const anchorUnit = (scrollLeft + cursorOffset) / before.pxPerUnit
    const next = timelineZoomScrollLeft({
      cursorOffset,
      maxScrollLeft: after.maxScrollLeft,
      nextPxPerUnit: after.pxPerUnit,
      pxPerUnit: before.pxPerUnit,
      scrollLeft,
    })
    expect((next + cursorOffset) / after.pxPerUnit).toBeCloseTo(anchorUnit, 6)
  })

  it('clamps the anchored offset into the new scroll range', () => {
    const next = timelineZoomScrollLeft({
      cursorOffset: 0,
      maxScrollLeft: 100,
      nextPxPerUnit: 1,
      pxPerUnit: 6,
      scrollLeft: 3_000,
    })
    expect(next).toBe(100)
    expect(timelineZoomScrollLeft({
      cursorOffset: 600,
      maxScrollLeft: 0,
      nextPxPerUnit: 0.5,
      pxPerUnit: 6,
      scrollLeft: 0,
    })).toBe(0)
  })
})

describe('timelineFollowsTail', () => {
  it('treats the last two pixels as the tail', () => {
    expect(timelineFollowsTail(1_000, 1_000)).toBe(true)
    expect(timelineFollowsTail(1_000 - TIMELINE_TAIL_FOLLOW_PX, 1_000)).toBe(true)
    expect(timelineFollowsTail(1_000 - TIMELINE_TAIL_FOLLOW_PX - 1, 1_000)).toBe(false)
  })

  it('follows a track that cannot scroll at all', () => {
    expect(timelineFollowsTail(0, 0)).toBe(true)
  })
})

describe('timelineRevealScrollLeft', () => {
  const base = { containerWidth: CONTAINER, maxScrollLeft: 2_360, scrollLeft: 1_000 }

  it('leaves a span that already intersects the viewport alone', () => {
    expect(timelineRevealScrollLeft({ ...base, spanLeft: 1_500, spanRight: 1_506 }))
      .toBe(1_000)
    expect(timelineRevealScrollLeft({ ...base, spanLeft: 994, spanRight: 1_002 }))
      .toBe(1_000)
  })

  it('travels the minimum distance to reveal a span on the left', () => {
    expect(timelineRevealScrollLeft({ ...base, spanLeft: 600, spanRight: 606 }))
      .toBe(600)
  })

  it('travels the minimum distance to reveal a span on the right', () => {
    expect(timelineRevealScrollLeft({ ...base, spanLeft: 2_000, spanRight: 2_006 }))
      .toBe(2_006 - CONTAINER)
  })

  it('never scrolls outside the track', () => {
    expect(timelineRevealScrollLeft({ ...base, spanLeft: -50, spanRight: -44 })).toBe(0)
    expect(timelineRevealScrollLeft({ ...base, spanLeft: 9_000, spanRight: 9_006 }))
      .toBe(2_360)
  })

  it('holds still while the track has no measured width', () => {
    expect(timelineRevealScrollLeft({
      containerWidth: 0,
      maxScrollLeft: 0,
      scrollLeft: 0,
      spanLeft: 900,
      spanRight: 906,
    })).toBe(0)
  })
})

describe('timelineEarlierScrollLeft', () => {
  it('shifts the viewport by the width the prepended page added', () => {
    expect(timelineEarlierScrollLeft({
      maxScrollLeft: 3_560,
      nextContentWidth: 4_200,
      previousContentWidth: 3_000,
      scrollLeft: 0,
    })).toBe(1_200)
  })

  it('keeps a mid-track viewport on the same records', () => {
    expect(timelineEarlierScrollLeft({
      maxScrollLeft: 3_560,
      nextContentWidth: 4_200,
      previousContentWidth: 3_000,
      scrollLeft: 500,
    })).toBe(1_700)
  })

  it('clamps to the track when the added width overshoots', () => {
    expect(timelineEarlierScrollLeft({
      maxScrollLeft: 1_000,
      nextContentWidth: 9_000,
      previousContentWidth: 3_000,
      scrollLeft: 0,
    })).toBe(1_000)
  })
})
