/**
 * Ledger line -> folded record, for the M5 search jump.
 *
 * The server search answers in `line_index`; the vendored table scrolls by
 * *record index* (`TrajectoryCellProps.index`), which only exists after the
 * fold. `annotate.ts` already stamps every cell with the line it came from, so
 * the map is a scan over the folded layout — no second index to keep in sync.
 *
 * Two properties of `TrajectoryTable` shape everything here:
 *
 * - It de-duplicates `recordFocus` **by reference**, so a fresh object on every
 *   render would re-scroll forever and a shared one would never scroll twice.
 * - It only re-runs its scroll effect when the rows themselves change. A jump
 *   command is therefore issued *before* the older pages are fetched and must
 *   resolve to nothing until the page holding its line lands — that landing is
 *   the commit that both rebuilds the rows and answers the command.
 */

import type { TrajectoryTurnModel } from '../trajectory/layout.ts'
import type { TrajectoryCellProps } from '../trajectory/trajectory-record.ts'
import { trajectoryRecordId } from '../trajectory/trajectory-record.ts'

/** One-shot "scroll here" command, addressed by raw ledger line. */
export interface TrajectoryLineFocus {
  readonly line: number
}

/** What `TrajectoryTable.recordFocus` accepts. */
export interface TrajectoryRecordFocus {
  readonly index: number
}

/**
 * How far from the wanted line a row may sit and still answer for it.
 *
 * Some lines never grow a row of their own: an `LLMRequestEntry` is a dot, a
 * legacy checkpoint reminder is hidden. Their neighbours are a line or two
 * away, so a small radius keeps the jump useful without letting a distant row
 * impersonate the target.
 */
export const FOCUS_NEAR_LINES = 3

interface CacheEntry {
  readonly turns: readonly TrajectoryTurnModel[]
  /** Projection-stable identity of the record the command resolved to. */
  readonly recordId: string | null
  readonly focus: TrajectoryRecordFocus | null
}

const RESOLVED = new WeakMap<TrajectoryLineFocus, CacheEntry>()

/**
 * The loaded record that best answers for one ledger line.
 *
 * An exact hit wins; otherwise the nearest row within {@link FOCUS_NEAR_LINES}
 * does, but only once the window actually reaches down to the line — while
 * every loaded row is *below* it, its page is simply not here yet and the
 * honest answer is "nothing". Request-only anchors are skipped: they are
 * zero-height rows with nothing to look at.
 * @param turns - Folded, annotated layout.
 * @param line - Raw `events.jsonl` line to reach.
 * @returns The cell, or null when no loaded row answers for the line.
 */
function nearestCell(
  turns: readonly TrajectoryTurnModel[],
  line: number,
): TrajectoryCellProps | null {
  let best: { cell: TrajectoryCellProps, distance: number } | null = null
  let reachesLine = false
  for (const turn of turns) {
    for (const group of turn.groups) {
      for (const cell of group.cells) {
        if (cell.lineIndex === undefined || cell.requestOnly === true) continue
        if (cell.lineIndex === line) return cell
        if (cell.lineIndex < line) reachesLine = true
        const distance = Math.abs(cell.lineIndex - line)
        if (distance > FOCUS_NEAR_LINES) continue
        if (best === null || distance < best.distance) best = { cell, distance }
      }
    }
  }
  return reachesLine ? best?.cell ?? null : null
}

/**
 * Find the record index that answers for one ledger line.
 * @param turns - Folded, annotated layout.
 * @param line - Raw `events.jsonl` line to reach.
 * @returns The record index, or null when no loaded row answers for the line.
 */
export function trajectoryRecordIndexForLine(
  turns: readonly TrajectoryTurnModel[],
  line: number,
): number | null {
  return nearestCell(turns, line)?.index ?? null
}

/**
 * Resolve a host focus command against the current layout, stably.
 *
 * The answer changes identity only when it starts pointing at a **different
 * record** — not when a prepended page renumbers the one it already points at.
 * So the ledger scrolls once, in the commit the target's page landed, and
 * every later fold leaves it alone.
 * @param turns - Folded, annotated layout.
 * @param command - The host's one-shot command, or null for "no request".
 * @returns The focus to hand `TrajectoryTable`, or null.
 */
export function trajectoryRecordFocus(
  turns: readonly TrajectoryTurnModel[],
  command: TrajectoryLineFocus | null | undefined,
): TrajectoryRecordFocus | null {
  if (command === null || command === undefined) return null
  const cached = RESOLVED.get(command)
  if (cached !== undefined && cached.turns === turns) return cached.focus
  const cell = nearestCell(turns, command.line)
  const recordId = cell === null ? null : trajectoryRecordId(cell)
  // Same record as last time: keep the object the table already acted on.
  const focus = cached !== undefined && cached.recordId === recordId
    ? cached.focus
    : (cell === null ? null : { index: cell.index })
  RESOLVED.set(command, { turns, recordId, focus })
  return focus
}
