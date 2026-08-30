/** Operation-sequence and recorded-time projections for the trajectory overview. */

import type { TrajectoryTurnModel } from './layout.ts'
import type { TrajectoryTranslate } from './locales.ts'
import { formatDurationMillis } from './trajectory-record.ts'
import type { TrajectoryCellKind, TrajectoryCellProps } from './trajectory-record.ts'

/** Horizontal projection used by the trajectory timeline. */
export type TrajectoryTimelineMode = 'sequence' | 'duration' | 'time' | 'actual'

/** Inclusive selection in the active timeline projection's domain. */
export interface TrajectoryTimeRange {
  start: number
  end: number
}

/** One ledger record projected into the active timeline domain. */
export interface TrajectoryTimelineSpan extends TrajectoryTimeRange {
  index: number
  isError: boolean
  kind: TrajectoryCellKind
  label: string
  lane: number
  /** klaude: set when the record's row is discarded (UX spec D3). */
  discarded?: true
}

/** One turn boundary in the active timeline domain. */
export interface TrajectoryTimelineTurnBoundary {
  turn: number
  time: number
}

/** Full-domain model used by the overview. */
export interface TrajectoryTimelineModel extends TrajectoryTimeRange {
  spans: readonly TrajectoryTimelineSpan[]
  turnBoundaries: readonly TrajectoryTimelineTurnBoundary[]
}

/**
 * Format a timeline duration as an integer-millisecond label.
 * @param milliseconds - Non-negative duration in milliseconds.
 * @param t - Trajectory locale translator.
 * @returns Millisecond label with thousands separators.
 */
export function formatTimelineOffset(
  milliseconds: number,
  t: TrajectoryTranslate,
): string {
  return formatDurationMillis(milliseconds, t)
}

function laneFor(kind: TrajectoryCellKind): number {
  // klaude: the upstream nested-call kind dropped (UX spec D2); 'rewind' and 'btw' take the Input
  // lane through the default below.
  if (kind === 'tool') return 2
  if (kind === 'message' || kind === 'compacted') return 1
  return 0
}

function finite(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value)
}

function cellRange(cell: TrajectoryCellProps): TrajectoryTimeRange | null {
  if (!finite(cell.startedAt)) return null
  const durationMs = finite(cell.timeSeconds)
    ? Math.max(0, cell.timeSeconds * 1_000)
    : 0
  return { start: cell.startedAt, end: cell.startedAt + durationMs }
}

/**
 * Project every visible record into a stable three-lane timeline.
 * @param turns - Unfiltered trajectory layout.
 * @param mode - Independent equal/recorded duration and compressed/complete time projection.
 * @returns Timeline model, or `null` when no record is visible.
 */
export function deriveTrajectoryTimeline(
  turns: readonly TrajectoryTurnModel[],
  mode: TrajectoryTimelineMode = 'sequence',
): TrajectoryTimelineModel | null {
  if (mode !== 'sequence') {
    return deriveTimedTimeline(
      turns,
      mode === 'duration' || mode === 'actual',
      mode === 'duration',
    )
  }
  const spans: TrajectoryTimelineSpan[] = []
  const turnBoundaries: TrajectoryTimelineTurnBoundary[] = []

  for (const turn of turns) {
    const cells = turn.groups.flatMap(group =>
      group.cells.filter(cell => cell.requestOnly !== true),
    )
    if (cells.length === 0) continue
    if (turn.turn !== null) {
      turnBoundaries.push({
        turn: turn.turn,
        time: spans.length,
      })
    }
    spans.push(...cells.map((cell, offset): TrajectoryTimelineSpan => ({
      start: spans.length + offset,
      end: spans.length + offset + 1,
      index: cell.index,
      isError: cell.isError === true,
      kind: cell.kind,
      label: cell.text,
      lane: laneFor(cell.kind),
      ...(cell.discarded === undefined ? {} : { discarded: true as const }), // klaude: D3
    })))
  }

  if (spans.length === 0) return null
  return {
    start: 0,
    end: spans.length,
    spans,
    turnBoundaries,
  }
}

function deriveTimedTimeline(
  turns: readonly TrajectoryTurnModel[],
  actualDuration: boolean,
  compressIdle: boolean,
): TrajectoryTimelineModel | null {
  const timedTurns = turns.flatMap((turn) => {
    const rawSpans = turn.groups.flatMap(group =>
      group.cells.flatMap((cell): TrajectoryTimelineSpan[] => {
        if (cell.requestOnly === true) return []
        const range = cellRange(cell)
        return range === null
          ? []
          : [{
            ...range,
            index: cell.index,
            isError: cell.isError === true,
            kind: cell.kind,
            label: cell.text,
            lane: laneFor(cell.kind),
            ...(cell.discarded === undefined ? {} : { discarded: true as const }), // klaude: D3
          }]
      }),
    )
    return rawSpans.length === 0 ? [] : [{ turn: turn.turn, rawSpans }]
  })
  const rawSpans = timedTurns.flatMap(turn => turn.rawSpans)
  if (rawSpans.length === 0) return null

  const removedIdleBySpan = new Map<TrajectoryTimelineSpan, number>()
  let removedIdle = 0
  let coveredUntil: number | null = null
  for (const span of [...rawSpans].sort((left, right) =>
    left.start - right.start || left.end - right.end)) {
    if (compressIdle && coveredUntil !== null && span.start > coveredUntil) {
      removedIdle += span.start - coveredUntil
    }
    removedIdleBySpan.set(span, removedIdle)
    coveredUntil = coveredUntil === null ? span.end : Math.max(coveredUntil, span.end)
  }

  const spans: TrajectoryTimelineSpan[] = []
  const turnBoundaries: TrajectoryTimelineTurnBoundary[] = []
  for (const turn of timedTurns) {
    const projected = turn.rawSpans.map((span): TrajectoryTimelineSpan => {
      const offset = removedIdleBySpan.get(span) ?? 0
      return {
        ...span,
        start: span.start - offset,
        end: (actualDuration ? span.end : span.start) - offset,
      }
    })
    spans.push(...projected)
    if (turn.turn !== null) {
      turnBoundaries.push({
        turn: turn.turn,
        time: Math.min(...projected.map(span => span.start)),
      })
    }
  }

  return {
    start: Math.min(...spans.map(span => span.start)),
    end: Math.max(...spans.map(span => span.end)),
    spans,
    turnBoundaries,
  }
}

/**
 * Identify records active at any point inside an inclusive selected interval.
 * @param turns - Unfiltered trajectory layout.
 * @param range - Selected interval in the active projection.
 * @param mode - Independent equal/recorded duration and compressed/complete time projection.
 * @returns Record indexes inside the focus interval.
 */
export function trajectoryTimelineFocusIndexes(
  turns: readonly TrajectoryTurnModel[],
  range: TrajectoryTimeRange,
  mode: TrajectoryTimelineMode = 'sequence',
): ReadonlySet<number> {
  const model = deriveTrajectoryTimeline(turns, mode)
  return new Set(
    model?.spans
      .filter(span => span.start <= range.end && span.end >= range.start)
      .map(span => span.index),
  )
}

/* -------------------------------------------------------------------------- *
 * klaude: UX spec D1 — the strip is a horizontal scroller, not a domain window.
 * Upstream fits the whole domain into the container and zooms by shrinking a
 * viewport `[domainStart, domainEnd]`; the fork keeps a px-per-domain-unit
 * scale, lays the content out at `fullDuration * pxPerUnit` and moves the
 * viewport with `scrollLeft`. Everything below is that scale model as pure
 * functions so it can be unit-tested away from the DOM (timeline-scale.test.ts).
 * -------------------------------------------------------------------------- */

/** klaude: D1 — default `sequence` scale: px of track per record, gap included. */
export const TIMELINE_PX_PER_RECORD = 6
/**
 * klaude: D1 — default timed scale: px of track per millisecond. 0.004 px/ms is
 * 240 px per minute, so a 10-minute session opens about two 1200 px screens wide.
 */
export const TIMELINE_PX_PER_MS = 0.004
/** klaude: D1 — zoom-in stop, `sequence`: this many records fill the container. */
export const TIMELINE_MINIMUM_ZOOM_RECORDS = 4
/** klaude: D1 — zoom-in stop, timed modes: this many milliseconds fill the container. */
export const TIMELINE_MINIMUM_ZOOM_MS = 20
/** klaude: D1 — wheel zoom exponent, unchanged from upstream's `exp(deltaY * k)`. */
export const TIMELINE_ZOOM_EXPONENT = 0.0015
/** klaude: D1 — a scroller this close to its right edge still counts as "at the tail". */
export const TIMELINE_TAIL_FOLLOW_PX = 2
/** klaude: D1 — reveal animation, matching upstream's 180ms viewport transition. */
export const TIMELINE_REVEAL_MS = 180

/** Scale and scroll geometry of the timeline track at one zoom level. */
export interface TrajectoryTimelineScale {
  /** Track pixels per domain unit (record in `sequence`, millisecond otherwise). */
  pxPerUnit: number
  /** Scale at which the whole domain fits the container; zooming out stops here. */
  minimumPxPerUnit: number
  /** Scale at which the zoom-in floor fills the container. */
  maximumPxPerUnit: number
  /** Width of the scrolled content layer, never below the container. */
  contentWidth: number
  /** Largest legal `scrollLeft`. */
  maxScrollLeft: number
  /** Domain units the container shows at this scale. */
  visibleDuration: number
}

/** Inputs of {@link timelineScale}. */
export interface TrajectoryTimelineScaleInput {
  /** Active projection; picks the default scale and the zoom-in floor. */
  mode: TrajectoryTimelineMode
  /** `model.end - model.start`, in domain units. */
  fullDuration: number
  /** Measured track width in px; 0 before the first measurement. */
  containerWidth: number
  /** Zoom held by the view, or null for this mode's default. */
  pxPerUnit: number | null
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}

/**
 * Domain units a wheel zoom refuses to shrink the container below.
 * @param mode - Active timeline projection.
 * @returns Records for `sequence`, milliseconds otherwise.
 */
export function timelineZoomFloorUnits(mode: TrajectoryTimelineMode): number {
  return mode === 'sequence' ? TIMELINE_MINIMUM_ZOOM_RECORDS : TIMELINE_MINIMUM_ZOOM_MS
}

/**
 * Scale a freshly opened timeline starts at.
 * @param mode - Active timeline projection.
 * @returns Track pixels per domain unit.
 */
export function timelineDefaultPxPerUnit(mode: TrajectoryTimelineMode): number {
  return mode === 'sequence' ? TIMELINE_PX_PER_RECORD : TIMELINE_PX_PER_MS
}

/**
 * Resolve the track geometry for one zoom level.
 * @param input - Mode, domain length, container width and the held zoom.
 * @returns Clamped scale plus the content width and scroll range it implies.
 */
export function timelineScale(
  input: TrajectoryTimelineScaleInput,
): TrajectoryTimelineScale {
  const fullDuration = Math.max(1, input.fullDuration)
  const containerWidth = Math.max(0, input.containerWidth)
  const requested = input.pxPerUnit === null
    || !Number.isFinite(input.pxPerUnit)
    || input.pxPerUnit <= 0
    ? timelineDefaultPxPerUnit(input.mode)
    : input.pxPerUnit
  // Before the first measurement nothing constrains the scale: the content layer
  // carries `min-width: 100%`, so an under-wide layer still covers the track.
  const minimumPxPerUnit = containerWidth === 0 ? 0 : containerWidth / fullDuration
  const maximumPxPerUnit = containerWidth === 0
    ? Number.POSITIVE_INFINITY
    : containerWidth / Math.min(timelineZoomFloorUnits(input.mode), fullDuration)
  const pxPerUnit = clampNumber(requested, minimumPxPerUnit, maximumPxPerUnit)
  const contentWidth = Math.max(containerWidth, fullDuration * pxPerUnit)
  return {
    contentWidth,
    maxScrollLeft: Math.max(0, contentWidth - containerWidth),
    maximumPxPerUnit,
    minimumPxPerUnit,
    pxPerUnit,
    visibleDuration: containerWidth === 0
      ? fullDuration
      : Math.min(fullDuration, containerWidth / pxPerUnit),
  }
}

/**
 * Apply one wheel notch to the zoom.
 * @param scale - Current track geometry.
 * @param deltaY - Wheel delta; positive (scroll down) zooms out, as upstream.
 * @returns Next px per domain unit, clamped to the scale's own bounds.
 */
export function timelineZoomPxPerUnit(
  scale: TrajectoryTimelineScale,
  deltaY: number,
): number {
  // Upstream grew the visible *duration* by exp(deltaY * k); px per unit is its
  // reciprocal, hence the negated exponent for the same gesture direction.
  return clampNumber(
    scale.pxPerUnit * Math.exp(-deltaY * TIMELINE_ZOOM_EXPONENT),
    scale.minimumPxPerUnit,
    scale.maximumPxPerUnit,
  )
}

/**
 * Keep the content point under the cursor fixed across a zoom.
 * @param input - Scroll offset, cursor offset inside the track and both scales.
 * @returns `scrollLeft` to apply once the content layer has its new width.
 */
export function timelineZoomScrollLeft(input: {
  scrollLeft: number
  /** Cursor distance from the track's left edge, in px. */
  cursorOffset: number
  pxPerUnit: number
  nextPxPerUnit: number
  maxScrollLeft: number
}): number {
  const anchorUnits = (input.scrollLeft + input.cursorOffset)
    / Math.max(input.pxPerUnit, Number.EPSILON)
  return clampNumber(
    anchorUnits * input.nextPxPerUnit - input.cursorOffset,
    0,
    Math.max(0, input.maxScrollLeft),
  )
}

/**
 * Decide whether growth should keep the track pinned to its right edge.
 * @param scrollLeft - Current scroll offset.
 * @param maxScrollLeft - Largest legal scroll offset.
 * @returns True while the viewport sits at (or within 2px of) the tail.
 */
export function timelineFollowsTail(
  scrollLeft: number,
  maxScrollLeft: number,
): boolean {
  return maxScrollLeft - scrollLeft <= TIMELINE_TAIL_FOLLOW_PX
}

/**
 * Smallest scroll that brings a span into view, mirroring upstream's reveal rule.
 * @param input - Viewport geometry and the span's content-relative px range.
 * @returns Target `scrollLeft`; unchanged when the span already intersects the viewport.
 */
export function timelineRevealScrollLeft(input: {
  scrollLeft: number
  containerWidth: number
  spanLeft: number
  spanRight: number
  maxScrollLeft: number
}): number {
  const maxScrollLeft = Math.max(0, input.maxScrollLeft)
  const scrollLeft = clampNumber(input.scrollLeft, 0, maxScrollLeft)
  if (input.containerWidth <= 0) return scrollLeft
  const visibleRight = scrollLeft + input.containerWidth
  if (input.spanRight > scrollLeft && input.spanLeft < visibleRight) return scrollLeft
  return clampNumber(
    input.spanRight <= scrollLeft
      ? input.spanLeft
      : input.spanRight - input.containerWidth,
    0,
    maxScrollLeft,
  )
}

/**
 * Hold the viewport on the same records after an earlier-history page is prepended.
 * @param input - Scroll offset and content width captured before the load, plus the new geometry.
 * @returns `scrollLeft` that leaves the previously visible records where they were.
 */
export function timelineEarlierScrollLeft(input: {
  scrollLeft: number
  previousContentWidth: number
  nextContentWidth: number
  maxScrollLeft: number
}): number {
  // Older rows only ever land left of what is loaded, and idle compression moves
  // every existing span by the same constant, so the width delta *is* the shift.
  return clampNumber(
    input.scrollLeft + (input.nextContentWidth - input.previousContentWidth),
    0,
    Math.max(0, input.maxScrollLeft),
  )
}
