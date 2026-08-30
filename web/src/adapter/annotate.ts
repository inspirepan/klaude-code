/**
 * Apply the adapter's per-record annotations to a folded layout.
 *
 * `layout.ts` builds cells out of conversation nodes alone, so the facts that
 * only the ledger knows — the raw line, the discarded status, the two
 * klaude-only row kinds and the sub-agent link — are attached here, once,
 * between the fold and every consumer (table, timeline, search index).
 *
 * Cells are addressed by the identities they keep: `sourceSeq` for
 * message-backed rows, `callId` for tool rows (which carry no seq). Neither
 * changes when an older page is prepended.
 */

import type { TrajectoryAnnotations } from '../contract/index.ts'
import type { TrajectoryTurnModel } from '../trajectory/layout.ts'
import type { TrajectoryCellProps } from '../trajectory/trajectory-record.ts'

/**
 * Decorate every cell that has an annotation.
 * @param turns - Folded layout from `deriveTrajectoryLayout`.
 * @param annotations - Adapter annotations, or undefined for a bare snapshot.
 * @returns The same array when nothing applies, else a decorated copy.
 */
export function applyTrajectoryAnnotations(
  turns: readonly TrajectoryTurnModel[],
  annotations: TrajectoryAnnotations | undefined,
): readonly TrajectoryTurnModel[] {
  if (annotations === undefined) return turns
  if (annotations.bySeq.size === 0 && annotations.byCallId.size === 0) return turns
  let changed = false
  const decorated = turns.map(turn => ({
    ...turn,
    groups: turn.groups.map(group => ({
      ...group,
      cells: group.cells.map((cell) => {
        const next = annotateCell(cell, annotations)
        if (next !== cell) changed = true
        return next
      }),
    })),
  }))
  return changed ? decorated : turns
}

function annotateCell(
  cell: TrajectoryCellProps,
  annotations: TrajectoryAnnotations,
): TrajectoryCellProps {
  const annotation = (cell.sourceSeq === undefined
    ? undefined
    : annotations.bySeq.get(cell.sourceSeq))
    ?? (cell.callId === undefined ? undefined : annotations.byCallId.get(cell.callId))
  if (annotation === undefined) return cell
  return {
    ...cell,
    ...(annotation.kind === undefined ? {} : { kind: annotation.kind }),
    ...(annotation.lineIndex === undefined ? {} : { lineIndex: annotation.lineIndex }),
    ...(annotation.discarded === undefined ? {} : { discarded: annotation.discarded }),
    ...(annotation.auto === undefined ? {} : { auto: annotation.auto }),
    ...(annotation.subAgent === undefined ? {} : { subAgent: annotation.subAgent }),
  }
}
