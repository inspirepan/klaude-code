/**
 * Splice the live projection into the REST-built snapshot.
 *
 * The wire carries no absolute turn ordinal — `session/ledger.py` numbers only
 * lines that landed on disk — so the in-flight rows are anchored on the last
 * landed row instead: the streaming response is the step *after* the newest
 * one in the ledger, inside the same turn. Since `history.appended` refreshes
 * the tail within a flush of the row landing, that anchor is never more than
 * one row stale.
 */

import type { PartialAssistant, RunningToolCall } from '../../contract/index.ts'
import type { TrajectorySnapshot } from '../../trajectory/trajectory-contract.ts'
import type { LiveState } from './reducer.ts'

/** Turn/step of the newest landed row. */
export interface TrajectoryAnchor {
  readonly turn: number
  /** 0 when the newest row opened a turn but no assistant answered yet. */
  readonly step: number
}

const FIRST_TURN: TrajectoryAnchor = { turn: 1, step: 0 }

/**
 * Turn/step of the last row that carries a location.
 * @param snapshot - The REST-built snapshot.
 * @returns The anchor; turn 1 / step 0 for an empty snapshot.
 */
export function trajectoryAnchor(snapshot: TrajectorySnapshot): TrajectoryAnchor {
  for (let index = snapshot.eventNodes.length - 1; index >= 0; index -= 1) {
    const node = snapshot.eventNodes[index]
    if (node === undefined) continue
    if (node.kind === 'assistant') return { turn: node.turn, step: node.step }
    const location = snapshot.eventLocations.get(node.seq)
    if (location === undefined) continue
    if (location.kind === 'step') return { turn: location.turn.turn, step: location.step.step }
    if (location.kind === 'turn') return { turn: location.turn.turn, step: 0 }
  }
  return FIRST_TURN
}

/**
 * Add `partial` and `runningCalls` to a snapshot built from landed rows.
 *
 * Returns the input untouched when nothing is in flight, so the trajectory
 * view's memos keep their identity on a cold session.
 * @param snapshot - Snapshot from `buildTrajectorySnapshot`.
 * @param live - Live state for the same session.
 * @returns The snapshot the trajectory view should render.
 */
export function spliceLiveSnapshot(
  snapshot: TrajectorySnapshot,
  live: LiveState,
): TrajectorySnapshot {
  if (live.partial === null && live.runningCalls.length === 0) return snapshot
  const anchor = trajectoryAnchor(snapshot)
  const partialStep = anchor.step + 1
  const partial: PartialAssistant | null = live.partial === null
    ? null
    : { turn: anchor.turn, step: partialStep, blocks: live.partial.blocks }
  // A call streams inside the response that emitted it. When that response has
  // already landed, the call belongs to the landed step, not the next one.
  const callStep = Math.max(1, live.partial === null ? anchor.step : partialStep)
  const runningCalls: readonly RunningToolCall[] = live.runningCalls.map(call => ({
    callId: call.callId,
    name: call.name,
    argsRaw: call.argsRaw,
    turn: anchor.turn,
    step: callStep,
    time: call.time,
    subCalls: [],
  }))
  return { ...snapshot, partial, runningCalls }
}
