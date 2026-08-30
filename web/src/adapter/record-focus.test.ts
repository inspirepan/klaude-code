import { describe, expect, it } from 'vitest'
import type { TrajectoryTurnModel } from '../trajectory/layout.ts'
import {
  FOCUS_NEAR_LINES, trajectoryRecordFocus, trajectoryRecordIndexForLine,
} from './record-focus.ts'

/** A folded layout with one cell per entry: `[index, lineIndex]`. */
function turns(
  cells: readonly (readonly [number, number | undefined, boolean?])[],
): readonly TrajectoryTurnModel[] {
  return [{
    turn: 1,
    groups: [{
      title: 'Step 1',
      cells: cells.map(([index, lineIndex, requestOnly]) => ({
        index,
        kind: 'message' as const,
        text: `record ${index}`,
        timeSeconds: 0.1,
        ...(lineIndex === undefined ? {} : { lineIndex }),
        ...(requestOnly === true ? { requestOnly: true } : {}),
      })),
    }],
  }]
}

describe('trajectoryRecordIndexForLine', () => {
  it('takes the exact line, and the first cell that owns it', () => {
    // An assistant line folds into a message cell plus one cell per tool call.
    const layout = turns([[1, 40], [2, 41], [3, 41], [4, 42]])
    expect(trajectoryRecordIndexForLine(layout, 41)).toBe(2)
  })

  it('falls back to the nearest row when the line has none of its own', () => {
    // Line 7 is an LLMRequestEntry: a dot, no row.
    const layout = turns([[1, 5], [2, 9]])
    expect(trajectoryRecordIndexForLine(layout, 7)).toBe(1)
    expect(trajectoryRecordIndexForLine(layout, 8)).toBe(2)
  })

  it('never lands on a request-only anchor', () => {
    // Line 12 is an out-of-step LLM call: a zero-height dot row, plus real
    // rows on either side.
    const layout = turns([[1, 11], [2, 12, true], [3, 13]])
    expect(trajectoryRecordIndexForLine(layout, 12)).toBe(1)
  })

  it('answers nothing while every loaded row is below the line', () => {
    // The line is still in an unfetched page, even though a row sits close by.
    expect(trajectoryRecordIndexForLine(turns([[1, 13], [2, 14]]), 12)).toBeNull()
  })

  it('answers null for a line no loaded row is near', () => {
    // The page holding line 3 is not in the window yet; the rows that are must
    // not stand in for it.
    const layout = turns([[1, 3 + FOCUS_NEAR_LINES + 1], [2, 400]])
    expect(trajectoryRecordIndexForLine(layout, 3)).toBeNull()
  })

  it('answers null when no cell carries a line', () => {
    expect(trajectoryRecordIndexForLine(turns([[1, undefined]]), 3)).toBeNull()
    expect(trajectoryRecordIndexForLine([], 3)).toBeNull()
  })
})

describe('trajectoryRecordFocus', () => {
  it('is null without a command', () => {
    expect(trajectoryRecordFocus(turns([[1, 4]]), null)).toBeNull()
    expect(trajectoryRecordFocus(turns([[1, 4]]), undefined)).toBeNull()
  })

  it('keeps one identity per command, so the table scrolls once', () => {
    const layout = turns([[1, 4], [2, 5]])
    const command = { line: 5 }
    const first = trajectoryRecordFocus(layout, command)
    expect(first).toEqual({ index: 2 })
    expect(trajectoryRecordFocus(layout, command)).toBe(first)
    // A prepended page rebuilds the layout; the answer did not move, so the
    // object must not either.
    const grown = turns([[1, 4], [2, 5], [3, 6]])
    expect(trajectoryRecordFocus(grown, command)).toBe(first)
  })

  it('re-resolves when the record moved', () => {
    const command = { line: 5 }
    const before = trajectoryRecordFocus(turns([[1, 5]]), command)
    const after = trajectoryRecordFocus(turns([[7, 5]]), command)
    expect(before).toEqual({ index: 1 })
    expect(after).toEqual({ index: 7 })
  })

  it('gives a new command its own identity, so the same line scrolls again', () => {
    const layout = turns([[1, 5]])
    const first = trajectoryRecordFocus(layout, { line: 5 })
    const second = trajectoryRecordFocus(layout, { line: 5 })
    expect(second).toEqual(first)
    expect(second).not.toBe(first)
  })
})
