/** Chrome-Network-style overview timeline for focusing the trajectory ledger. */

import {
  memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type PointerEvent,
} from 'react'
// klaude: upstream cross-package import -> the vendored primitives tree
import { Tooltip } from '../ui-primitives/index.ts'
import type { TrajectoryTurnModel } from './layout.ts'
import type { TrajectoryTranslate } from './locales.ts'
import type { AssistantMetricDetail, TrajectoryCellKind, TrajectoryCellProps } from './trajectory-record.ts'
import {
  deriveTrajectoryTimeline,
  formatTimelineOffset,
  // klaude: UX spec D1 — the scroller's scale model lives in timeline.ts
  timelineEarlierScrollLeft,
  timelineFollowsTail,
  timelineRevealScrollLeft,
  timelineScale,
  timelineZoomPxPerUnit,
  timelineZoomScrollLeft,
  TIMELINE_REVEAL_MS,
  type TrajectoryTimelineMode,
  type TrajectoryTimeRange,
} from './timeline.ts'
import css from './TrajectoryTimeline.module.css'

const MINIMUM_DRAG_PX = 3
// klaude: D1 — upstream's MINIMUM_ZOOM_OPERATIONS is now the px-per-unit ceiling
// TIMELINE_MINIMUM_ZOOM_RECORDS / _MS in timeline.ts.
const EDGE_PAN_ZONE_FRACTION = 0.08
const EDGE_PAN_STEP_FRACTION = 0.025
const MAXIMUM_EDGE_PAN_PX = 32
const TIMELINE_TOOLTIP_DELAY_MS = 500
// klaude: D1 — upstream culled spans to the domain window; the scroller culls to
// the visible px window plus this margin, so a scroll inside the margin needs no
// re-render. The window only commits once the offset moved a whole step.
const SPAN_WINDOW_MARGIN_PX = 480
const SPAN_WINDOW_STEP_PX = 160

interface TimelineRecordDetail {
  decodingMs?: number
  durationMs?: number
  startedAt?: number
  ttftMs?: number
}

interface FractionRange {
  start: number
  end: number
}

interface HoverPoint {
  /** klaude: D1 — content px, was a viewport fraction. */
  contentX: number
  recordIndex: number | null
}

interface PanGesture {
  anchorClientX: number
  /** klaude: D1 — a right-drag pans `scrollLeft`, not the domain start. */
  anchorScrollLeft: number
  moved: boolean
  pannable: boolean
  pointerId: number
}

/** klaude: D1 — committed scroll offset the span cull window is built from. */
interface ScrollWindow {
  left: number
  atStart: boolean
}

function assistantTimingDetail(
  metrics: AssistantMetricDetail | undefined,
): Pick<TimelineRecordDetail, 'ttftMs' | 'decodingMs'> {
  const start = metrics?.stepStartTime
  const first = metrics?.firstTokenTime
  const completed = metrics?.completedTime
  if (
    metrics?.timingRecorded !== true
    || typeof start !== 'number'
    || typeof first !== 'number'
    || typeof completed !== 'number'
    || !Number.isFinite(start)
    || !Number.isFinite(first)
    || !Number.isFinite(completed)
    || first < start
    || completed < first
  ) return {}
  return { ttftMs: first - start, decodingMs: completed - first }
}

function timelineRecordDetail(cell: TrajectoryCellProps): TimelineRecordDetail {
  const durationMs = cell.timeSeconds === null || !Number.isFinite(cell.timeSeconds)
    ? undefined
    : Math.max(0, cell.timeSeconds * 1_000)
  const startedAt = cell.startedAt === null || !Number.isFinite(cell.startedAt)
    ? undefined
    : cell.startedAt
  return {
    ...(durationMs === undefined ? {} : { durationMs }),
    ...(startedAt === undefined ? {} : { startedAt }),
    ...assistantTimingDetail(cell.assistantMetrics),
  }
}

function timelineKindLabel(kind: TrajectoryCellKind, t: TrajectoryTranslate): string {
  switch (kind) {
    case 'system': return t('kind.system')
    case 'user': return t('kind.user')
    case 'context': return t('kind.context')
    case 'compacted': return t('kind.compacted')
    case 'message': return t('kind.assistant')
    case 'tool': return t('kind.tool')
    // klaude: UX spec D2 row kinds (the upstream nested-call kind is dropped)
    case 'rewind': return t('kind.rewind')
    case 'btw': return t('kind.btw')
  }
}

function formatRecordedTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  })
}

function timelineTooltipLabel(
  kind: TrajectoryCellKind,
  detail: TimelineRecordDetail | undefined,
  t: TrajectoryTranslate,
): string {
  const heading = timelineKindLabel(kind, t)
  if (detail === undefined) return heading
  const duration = detail.durationMs === undefined
    ? null
    : t('timeline.total', { duration: formatTimelineOffset(detail.durationMs, t) })
  const range = detail.startedAt === undefined
    ? null
    : detail.durationMs === undefined
      ? t('timeline.started', { time: formatRecordedTime(detail.startedAt) })
      : `${formatRecordedTime(detail.startedAt)} → ${formatRecordedTime(
        detail.startedAt + detail.durationMs,
      )}`
  const segments = detail.ttftMs === undefined || detail.decodingMs === undefined
    ? null
    : t('timeline.ttftDecoding', {
      ttft: formatTimelineOffset(detail.ttftMs, t),
      decoding: formatTimelineOffset(detail.decodingMs, t),
    })
  const timing = [duration, segments].filter(value => value !== null).join(' · ')
  return [heading, range, timing].filter(value => value !== null && value !== '').join('\n')
}

/** Props for the fixed full-domain overview above the trajectory ledger. */
export interface TrajectoryTimelineProps {
  t: TrajectoryTranslate
  turns: readonly TrajectoryTurnModel[]
  mode: TrajectoryTimelineMode
  range: TrajectoryTimeRange | null
  /** Whether the loaded timeline omits an earlier history prefix. */
  hasEarlierRecords?: boolean
  /** Load one earlier history page from the truncation control. */
  onLoadEarlier?: () => Promise<boolean>
  selectedIndex?: number | null
  /** Record indexes matching the active ledger search, or null without a query. */
  searchMatchIndexes?: ReadonlySet<number> | null
  onRangeChange: (range: TrajectoryTimeRange | null) => void
  /** Select a directly clicked timeline block. */
  onRecordSelect?: (index: number) => void
  /** Bring the nearest record into view after clicking timeline whitespace. */
  onRecordFocus?: (index: number) => void
}

function orderedRange(left: number, right: number): FractionRange {
  return left <= right ? { start: left, end: right } : { start: right, end: left }
}

function clampFraction(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function centeredRange(
  center: number,
  width: number,
  minimum: number,
  maximum: number,
): FractionRange {
  const clampedWidth = Math.min(maximum - minimum, Math.max(0, width))
  const start = Math.min(
    Math.max(center - clampedWidth / 2, minimum),
    maximum - clampedWidth,
  )
  return { start, end: start + clampedWidth }
}

// klaude: D1 — upstream's `rangeFraction` projected a range onto the viewport;
// the scroller places overlays in content px instead (see `contentPx`).
function maxScrollLeftOf(track: HTMLDivElement): number {
  return Math.max(0, track.scrollWidth - track.clientWidth)
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function LaneLabels({ t }: { t: TrajectoryTranslate }) {
  return (
    <div className={css.labels} aria-hidden="true">
      <span>{t('column.input')}</span>
      <span>{t('column.model')}</span>
      <span>{t('column.tools')}</span>
    </div>
  )
}

function EarlierHistoryBoundary({
  loading,
  onHover,
  onLoad,
  t,
}: {
  loading: boolean
  onHover: () => void
  onLoad: (() => void) | undefined
  t: TrajectoryTranslate
}) {
  return (
    <Tooltip
      label={loading ? t('history.loadingEarlier') : t('history.clickToLoadEarlier')}
      side="right"
      delayMs={TIMELINE_TOOLTIP_DELAY_MS}
    >
      <button
        type="button"
        className={css.earlierHistory}
        data-earlier-history
        data-loading={loading || undefined}
        aria-label={loading ? t('history.loadingEarlierAria') : t('history.loadEarlier')}
        aria-disabled={loading || onLoad === undefined}
        onClick={onLoad}
        onPointerEnter={(event) => {
          event.stopPropagation()
          onHover()
        }}
        onPointerMove={(event) => { event.stopPropagation() }}
        onPointerDown={(event) => { event.stopPropagation() }}
      >
        …
      </button>
    </Tooltip>
  )
}

/** Overview renderer with drag ranges, click-sized focus, and Escape reset. */
export const TrajectoryTimeline = memo(function TrajectoryTimeline({
  t,
  turns,
  mode,
  range,
  hasEarlierRecords = false,
  onLoadEarlier,
  selectedIndex = null,
  searchMatchIndexes = null,
  onRangeChange,
  onRecordSelect,
  onRecordFocus,
}: TrajectoryTimelineProps) {
  const model = useMemo(() => deriveTrajectoryTimeline(turns, mode), [mode, turns])
  const detailByIndex = useMemo(
    () => new Map(turns.flatMap(turn =>
      turn.groups.flatMap(group =>
        group.cells.map(cell => [cell.index, timelineRecordDetail(cell)] as const),
      ),
    )),
    [turns],
  )
  const dragRef = useRef<{
    pointerId: number
    anchorTime: number
    anchorClientX: number
    recordIndex: number | null
  } | null>(null)
  const panRef = useRef<PanGesture | null>(null)
  const rootRef = useRef<HTMLElement | null>(null)
  const trackRef = useRef<HTMLDivElement | null>(null)
  const [draft, setDraft] = useState<TrajectoryTimeRange | null>(null)
  const [hover, setHover] = useState<HoverPoint | null>(null)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [panning, setPanning] = useState(false)
  // klaude: D1 — the upstream `viewport` / `animateViewport` domain-window state is
  // replaced by a zoom (px per domain unit) plus the track's own `scrollLeft`.
  const [containerWidth, setContainerWidth] = useState(0)
  // The zoom carries its mode: px per record and px per millisecond are not the
  // same unit, so a mode switch falls back to that mode's default scale.
  const [zoom, setZoom] = useState<{ mode: TrajectoryTimelineMode; pxPerUnit: number } | null>(null)
  const [scrollWindow, setScrollWindow] = useState<ScrollWindow>({ atStart: true, left: 0 })
  const revealFrameRef = useRef<number | null>(null)
  const revealedIndexRef = useRef<number | null>(null)
  const pendingScrollRef = useRef<number | null>(null)
  const earlierAnchorRef = useRef<{ contentWidth: number; scrollLeft: number } | null>(null)
  const followsTailRef = useRef(true)

  const fullDuration = Math.max(1, (model?.end ?? 0) - (model?.start ?? 0))
  const domainStart = model?.start ?? 0
  const pxPerUnit = zoom !== null && zoom.mode === mode ? zoom.pxPerUnit : null
  const scale = useMemo(
    () => timelineScale({ containerWidth, fullDuration, mode, pxPerUnit }),
    [containerWidth, fullDuration, mode, pxPerUnit],
  )
  // Read by the reveal effect, which must not re-run (and re-scroll) on a zoom.
  const projectionRef = useRef({ domainStart, pxPerUnit: scale.pxPerUnit })
  useLayoutEffect(() => {
    projectionRef.current = { domainStart, pxPerUnit: scale.pxPerUnit }
  })
  const contentPx = useCallback(
    (unit: number): number => (unit - domainStart) * scale.pxPerUnit,
    [domainStart, scale.pxPerUnit],
  )
  const syncScrollWindow = useCallback((track: HTMLDivElement) => {
    const left = track.scrollLeft
    const atStart = left <= 0.5
    setScrollWindow(current =>
      current.atStart === atStart && Math.abs(current.left - left) < SPAN_WINDOW_STEP_PX
        ? current
        : { atStart, left })
  }, [])
  const scrollTrackTo = useCallback((track: HTMLDivElement, left: number) => {
    const maxScrollLeft = maxScrollLeftOf(track)
    track.scrollLeft = Math.min(Math.max(left, 0), maxScrollLeft)
    followsTailRef.current = timelineFollowsTail(track.scrollLeft, maxScrollLeft)
    syncScrollWindow(track)
  }, [syncScrollWindow])
  const cancelReveal = useCallback(() => {
    if (revealFrameRef.current !== null && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(revealFrameRef.current)
    }
    revealFrameRef.current = null
  }, [])
  const revealScroll = useCallback((track: HTMLDivElement, target: number) => {
    cancelReveal()
    if (
      prefersReducedMotion()
      || typeof requestAnimationFrame !== 'function'
      || typeof performance === 'undefined'
    ) {
      scrollTrackTo(track, target)
      return
    }
    const from = track.scrollLeft
    const startedAt = performance.now()
    const step = (now: number): void => {
      const progress = Math.min(1, (now - startedAt) / TIMELINE_REVEAL_MS)
      // ease-out, matching upstream's 180ms `left` transition.
      scrollTrackTo(track, from + (target - from) * (1 - (1 - progress) ** 3))
      revealFrameRef.current = progress < 1 ? requestAnimationFrame(step) : null
    }
    revealFrameRef.current = requestAnimationFrame(step)
  }, [cancelReveal, scrollTrackTo])
  useEffect(() => cancelReveal, [cancelReveal])
  // klaude: D1 — the content width is measured, not derived from a domain fraction.
  useLayoutEffect(() => {
    const track = trackRef.current
    if (track === null) return
    setContainerWidth(track.clientWidth)
    if (typeof ResizeObserver !== 'function') return
    const observer = new ResizeObserver(() => { setContainerWidth(track.clientWidth) })
    observer.observe(track)
    return () => { observer.disconnect() }
  }, [model === null])
  useEffect(() => {
    if (
      model !== null
      && range !== null
      && (range.end < model.start || range.start > model.end)
    ) {
      onRangeChange(null)
    }
  }, [model, onRangeChange, range])
  // klaude: D1 — growth, zoom and earlier-history all land on `scrollLeft`:
  // a pending zoom anchor wins, then an earlier-history anchor, then tail follow.
  useLayoutEffect(() => {
    const track = trackRef.current
    if (track === null) return
    const pending = pendingScrollRef.current
    if (pending !== null) {
      pendingScrollRef.current = null
      scrollTrackTo(track, pending)
      return
    }
    const anchor = earlierAnchorRef.current
    if (anchor !== null) {
      earlierAnchorRef.current = null
      if (anchor.contentWidth !== scale.contentWidth) {
        scrollTrackTo(track, timelineEarlierScrollLeft({
          maxScrollLeft: maxScrollLeftOf(track),
          nextContentWidth: scale.contentWidth,
          previousContentWidth: anchor.contentWidth,
          scrollLeft: anchor.scrollLeft,
        }))
        return
      }
    }
    if (followsTailRef.current) scrollTrackTo(track, maxScrollLeftOf(track))
  }, [model, scale.contentWidth, scale.pxPerUnit, scrollTrackTo])
  // klaude: D1 — upstream panned the domain window to reveal the selected span;
  // the scroller travels the same minimum distance with `scrollLeft`. Only a new
  // selection reveals: re-running on every model growth would fight tail follow.
  useEffect(() => {
    const track = trackRef.current
    if (track === null || model === null || selectedIndex === null) {
      revealedIndexRef.current = selectedIndex
      return
    }
    if (selectedIndex === revealedIndexRef.current) return
    const span = model.spans.find(candidate => candidate.index === selectedIndex)
    if (span === undefined) return
    revealedIndexRef.current = selectedIndex
    const projection = projectionRef.current
    const target = timelineRevealScrollLeft({
      containerWidth: track.clientWidth,
      maxScrollLeft: maxScrollLeftOf(track),
      scrollLeft: track.scrollLeft,
      spanLeft: (span.start - projection.domainStart) * projection.pxPerUnit,
      spanRight: (span.end - projection.domainStart) * projection.pxPerUnit,
    })
    if (Math.abs(target - track.scrollLeft) < 1) return
    revealScroll(track, target)
  }, [model, revealScroll, selectedIndex])
  const showsEarlierBoundary = hasEarlierRecords
    && model !== null
    && scrollWindow.atStart // klaude: D1 — was `domainStart === model.start`
  const loadEarlier = onLoadEarlier === undefined || loadingEarlier
    ? undefined
    : () => {
      // klaude: D1 — hold the viewport on the records already on screen; the
      // prepended page shifts them right by exactly the added content width.
      const track = trackRef.current
      earlierAnchorRef.current = {
        contentWidth: scale.contentWidth,
        scrollLeft: track === null ? 0 : track.scrollLeft,
      }
      followsTailRef.current = false
      setLoadingEarlier(true)
      void onLoadEarlier().finally(() => { setLoadingEarlier(false) })
    }
  // klaude: D1 — one content layer, laid out in px of the full content width;
  // spans stay percentages of it, so only the layer's own width moved.
  const contentStyle = {
    '--trajectory-content-width': `${scale.contentWidth}px`,
  } as CSSProperties
  const committed = model === null || range === null
    ? null
    : orderedRange(
      contentPx(Math.min(model.end, Math.max(model.start, range.start))),
      contentPx(Math.min(model.end, Math.max(model.start, range.end))),
    )
  const draftPixels = model === null || draft === null
    ? null
    : orderedRange(
      contentPx(Math.min(model.end, Math.max(model.start, draft.start))),
      contentPx(Math.min(model.end, Math.max(model.start, draft.end))),
    )
  const visibleRange = draftPixels ?? committed
  const activeRange = draft ?? range
  // klaude: D1 — wheel zooms px-per-unit around the cursor; a horizontal delta
  // (trackpad) scrolls instead. `preventDefault` keeps the page still either way.
  useEffect(() => {
    const root = rootRef.current
    if (root === null) return
    const onWheel = (event: globalThis.WheelEvent): void => {
      event.preventDefault()
      const track = trackRef.current
      if (track === null || model === null) return
      cancelReveal()
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        scrollTrackTo(track, track.scrollLeft + event.deltaX)
        return
      }
      const nextPxPerUnit = timelineZoomPxPerUnit(scale, event.deltaY)
      if (nextPxPerUnit === scale.pxPerUnit) return
      const next = timelineScale({
        containerWidth,
        fullDuration,
        mode,
        pxPerUnit: nextPxPerUnit,
      })
      const rect = track.getBoundingClientRect()
      pendingScrollRef.current = timelineZoomScrollLeft({
        cursorOffset: Math.min(Math.max(event.clientX - rect.left, 0), rect.width),
        maxScrollLeft: next.maxScrollLeft,
        nextPxPerUnit: next.pxPerUnit,
        pxPerUnit: scale.pxPerUnit,
        scrollLeft: track.scrollLeft,
      })
      setZoom({ mode, pxPerUnit: nextPxPerUnit })
    }
    root.addEventListener('wheel', onWheel, { passive: false })
    return () => { root.removeEventListener('wheel', onWheel) }
  }, [cancelReveal, containerWidth, fullDuration, mode, model, scale, scrollTrackTo])

  if (model === null) {
    return (
      <section ref={rootRef} className={css.root} aria-label={t('timeline.aria')}>
        <div className={css.plot}>
          <LaneLabels t={t} />
          <div className={css.track}>
            <span className={css.empty}>{t('timeline.noTimingData')}</span>
            {hasEarlierRecords && (
              <EarlierHistoryBoundary
                loading={loadingEarlier}
                onHover={() => { setHover(null) }}
                onLoad={loadEarlier}
                t={t}
              />
            )}
          </div>
        </div>
      </section>
    )
  }

  const minimumSelectionDuration = Math.min(
    scale.visibleDuration, // klaude: D1 — was the domain window's duration
    fullDuration / model.spans.length,
  )
  // klaude: D1 — cull to the scrolled window instead of the domain window.
  const windowLeft = scrollWindow.left - SPAN_WINDOW_MARGIN_PX
  const windowRight = scrollWindow.left + containerWidth + SPAN_WINDOW_MARGIN_PX

  const contentXAt = (event: PointerEvent<HTMLDivElement>): number => {
    const track = event.currentTarget
    const rect = track.getBoundingClientRect()
    return Math.min(
      Math.max(event.clientX - rect.left + track.scrollLeft, 0),
      scale.contentWidth,
    )
  }

  const unitAt = (contentX: number): number =>
    domainStart + contentX / Math.max(scale.pxPerUnit, Number.EPSILON)

  const recordIndexAt = (event: PointerEvent<HTMLDivElement>): number | null => {
    const target = event.target instanceof HTMLElement ? event.target : null
    const value = target?.closest<HTMLElement>('[data-timeline-record-index]')
      ?.dataset.timelineRecordIndex
    if (value === undefined) return null
    const index = Number(value)
    return Number.isFinite(index) ? index : null
  }

  const commit = (nextRange: TrajectoryTimeRange) => {
    onRangeChange(nextRange)
  }

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    cancelReveal()
    if (event.button === 2) {
      panRef.current = {
        anchorClientX: event.clientX,
        // klaude: D1 — pan anchors on the scroll offset, not on the domain start
        anchorScrollLeft: event.currentTarget.scrollLeft,
        moved: false,
        pannable: maxScrollLeftOf(event.currentTarget) > 0,
        pointerId: event.pointerId,
      }
      setPanning(true)
      if (typeof event.currentTarget.setPointerCapture === 'function') {
        event.currentTarget.setPointerCapture(event.pointerId)
      }
      return
    }
    if (event.button !== 0) return
    const contentX = contentXAt(event)
    const anchorTime = unitAt(contentX)
    const recordIndex = recordIndexAt(event)
    setHover({ contentX, recordIndex })
    dragRef.current = {
      pointerId: event.pointerId,
      anchorTime,
      anchorClientX: event.clientX,
      recordIndex,
    }
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    setDraft({ start: anchorTime, end: anchorTime })
  }

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const track = event.currentTarget
    const rect = track.getBoundingClientRect()
    setHover({ contentX: contentXAt(event), recordIndex: recordIndexAt(event) })
    const pan = panRef.current
    if (pan !== null && pan.pointerId === event.pointerId) {
      if (Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX) {
        pan.moved = true
      }
      if (!pan.pannable) return
      // klaude: D1 — 1:1 with the pointer, since the content is laid out in px.
      scrollTrackTo(track, pan.anchorScrollLeft - (event.clientX - pan.anchorClientX))
      return
    }
    const drag = dragRef.current
    if (drag === null || drag.pointerId !== event.pointerId) return
    // klaude: D1 — edge auto-pan steps `scrollLeft` by the same 2.5% of the
    // viewport upstream stepped the domain window by.
    if (maxScrollLeftOf(track) > 0) {
      const localX = event.clientX - rect.left
      const edgeWidth = Math.min(
        MAXIMUM_EDGE_PAN_PX,
        Math.max(1, rect.width * EDGE_PAN_ZONE_FRACTION),
      )
      const direction = localX < edgeWidth
        ? -1
        : localX > rect.width - edgeWidth ? 1 : 0
      if (direction !== 0) {
        const edgeDistance = direction < 0
          ? edgeWidth - localX
          : localX - (rect.width - edgeWidth)
        const strength = clampFraction(edgeDistance / edgeWidth)
        scrollTrackTo(
          track,
          track.scrollLeft
          + direction * rect.width * EDGE_PAN_STEP_FRACTION * Math.max(0.2, strength),
        )
      }
    }
    setDraft(orderedRange(drag.anchorTime, unitAt(contentXAt(event))))
  }

  const onPointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    const pan = panRef.current
    if (pan !== null && pan.pointerId === event.pointerId) {
      const moved = pan.moved
        || Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX
      panRef.current = null
      setPanning(false)
      if (!moved) onRangeChange(null)
      return
    }
    const drag = dragRef.current
    if (drag === null || drag.pointerId !== event.pointerId) return
    const contentX = contentXAt(event)
    const selected = orderedRange(drag.anchorTime, unitAt(contentX))
    setHover({ contentX, recordIndex: recordIndexAt(event) })
    dragRef.current = null
    setDraft(null)
    const click = Math.abs(event.clientX - drag.anchorClientX) < MINIMUM_DRAG_PX
    const clickedSpan = click && drag.recordIndex !== null
      ? model.spans.find(span => span.index === drag.recordIndex)
      : undefined
    if (clickedSpan !== undefined) {
      onRangeChange(null)
      onRecordSelect?.(clickedSpan.index)
      return
    }
    const committedRange = selected.end - selected.start < minimumSelectionDuration
      ? centeredRange(
        click ? selected.start : (selected.start + selected.end) / 2,
        minimumSelectionDuration,
        model.start,
        model.end,
      )
      : selected
    commit(committedRange)
    if (click) {
      const timelinePoint = selected.start
      const nearest = model.spans.reduce((candidate, span) => {
        const candidateDistance = timelinePoint < candidate.start
          ? candidate.start - timelinePoint
          : timelinePoint > candidate.end ? timelinePoint - candidate.end : 0
        const spanDistance = timelinePoint < span.start
          ? span.start - timelinePoint
          : timelinePoint > span.end ? timelinePoint - span.end : 0
        return spanDistance < candidateDistance ? span : candidate
      })
      onRecordFocus?.(nearest.index)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Escape' || range === null) return
    event.preventDefault()
    onRangeChange(null)
  }

  const onPointerCancel = () => {
    dragRef.current = null
    panRef.current = null
    setDraft(null)
    setHover(null)
    setPanning(false)
  }

  return (
    <section ref={rootRef} className={css.root} aria-label={t('timeline.aria')}>
      <div className={css.plot}>
        <LaneLabels t={t} />
        <div
          ref={trackRef}
          className={css.track}
          data-panning={panning || undefined}
          data-timeline-scroller // klaude: D1 — the track is the scroll container
          aria-label={t('timeline.overviewAria')}
          tabIndex={0}
          style={contentStyle}
          onKeyDown={onKeyDown}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerCancel}
          onScroll={(event) => {
            // klaude: D1 — native scrollbar drags and momentum land here too.
            const track = event.currentTarget
            followsTailRef.current = timelineFollowsTail(
              track.scrollLeft,
              maxScrollLeftOf(track),
            )
            syncScrollWindow(track)
          }}
          onPointerLeave={() => {
            if (dragRef.current === null && panRef.current === null) setHover(null)
          }}
          onDoubleClick={(event) => {
            event.preventDefault()
            onRangeChange(null)
          }}
          onContextMenu={(event) => {
            event.preventDefault()
          }}
        >
          {showsEarlierBoundary && (
            <EarlierHistoryBoundary
              loading={loadingEarlier}
              onHover={() => { setHover(null) }}
              onLoad={loadEarlier}
              t={t}
            />
          )}
          {hover !== null && hover.recordIndex === null && draft === null && (
            <div
              className={css.hoverLine}
              data-timeline-hover-line
              aria-hidden="true"
              style={{
                // klaude: D1 — content px, was a viewport percentage
                '--trajectory-hover-left': `${hover.contentX}px`,
              } as CSSProperties}
            />
          )}
          {visibleRange !== null && (
            <>
              <div
                className={css.selection}
                data-dragging={draft === null ? undefined : 'true'}
                aria-hidden="true"
                style={{
                  // klaude: D1 — content px, was a viewport percentage
                  '--trajectory-selection-left': `${visibleRange.start}px`,
                  '--trajectory-selection-width': `${visibleRange.end - visibleRange.start}px`,
                } as CSSProperties}
              />
              <div
                className={css.selectionEdges}
                data-dragging={draft === null ? undefined : 'true'}
                aria-hidden="true"
                style={{
                  '--trajectory-selection-left': `${visibleRange.start}px`,
                  '--trajectory-selection-width': `${visibleRange.end - visibleRange.start}px`,
                } as CSSProperties}
              />
            </>
          )}
          <div
            className={css.turnBoundaries}
            data-timeline-content // klaude: D1 — sized by --trajectory-content-width
            aria-hidden="true"
          >
            {model.turnBoundaries
              .filter(boundary =>
                boundary.time > model.start
                && contentPx(boundary.time) >= windowLeft
                && contentPx(boundary.time) <= windowRight)
              .map(boundary => (
                <span
                  className={css.turnBoundary}
                  data-turn={boundary.turn}
                  key={boundary.turn}
                  style={{
                    '--trajectory-turn-left':
                      `${(boundary.time - model.start) / fullDuration * 100}%`,
                  } as CSSProperties}
                />
              ))}
          </div>
          <div
            className={css.lanes}
            data-timeline-content // klaude: D1 — sized by --trajectory-content-width
            data-timeline-domain
          >
            {model.spans
              .filter(span =>
                span.index === selectedIndex
                || (contentPx(span.end) >= windowLeft
                  && contentPx(span.start) <= windowRight))
              .map((span) => {
                const left = (span.start - model.start) / fullDuration
                const width = (span.end - span.start) / fullDuration
                const widthPercent = width * 100
                const detail = detailByIndex.get(span.index)
                const ttftMs = detail?.ttftMs
                const decodingMs = detail?.decodingMs
                const ttftFraction = ttftMs === undefined
                  || decodingMs === undefined
                  || ttftMs + decodingMs <= 0
                  ? null
                  : ttftMs / (ttftMs + decodingMs)
                return (
                  <Tooltip
                    key={span.index}
                    label={() => timelineTooltipLabel(span.kind, detail, t)}
                    side="bottom"
                    delayMs={TIMELINE_TOOLTIP_DELAY_MS}
                  >
                    <span
                      aria-hidden="true"
                      className={css.span}
                      data-timeline-span={span.kind}
                      data-timeline-record-index={span.index}
                      data-assistant-timing={ttftFraction === null ? undefined : 'true'}
                      data-error={span.isError || undefined}
                      // klaude: UX spec D3
                      data-discarded={span.discarded || undefined}
                      data-equal-duration={mode === 'time' || undefined}
                      data-current={span.index === selectedIndex || undefined}
                      data-hovered={hover?.recordIndex === span.index || undefined}
                      data-search-match={searchMatchIndexes === null
                        ? undefined
                        : searchMatchIndexes.has(span.index) ? 'true' : 'false'}
                      data-selected={activeRange === null
                        ? undefined
                        : span.start <= activeRange.end && span.end >= activeRange.start
                          ? 'true'
                          : 'false'}
                      style={{
                        '--trajectory-span-left': `${left * 100}%`,
                        '--trajectory-span-width': `${widthPercent}%`,
                        '--trajectory-span-gap': `min(${widthPercent * 0.08}%, 1px)`,
                        '--trajectory-span-lane': span.lane,
                        ...(ttftFraction === null
                          ? {}
                          : { '--trajectory-assistant-ttft': `${ttftFraction * 100}%` }),
                      } as CSSProperties}
                    />
                  </Tooltip>
                )
              })}
          </div>
        </div>
      </div>
    </section>
  )
})
