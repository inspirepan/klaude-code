/**
 * Seq scheme.
 *
 * `layout.ts` interleaves conversation nodes and requests on one integer axis
 * (`node.seq` vs `RequestView.startSeq`) and `TrajectoryView` numbers requests
 * by that same order, so a request header has to be able to sit *between* two
 * nodes. klaude's stable coordinate is the zero-based `events.jsonl` line, so
 * every line owns a block of `SEQ_SLOTS_PER_LINE` seqs:
 *
 * | offset | slot                                             |
 * |--------|--------------------------------------------------|
 * | +0     | the request that produced the line (request dot) |
 * | +1     | the conversation node built from the line        |
 * | +2     | step end / reserved                              |
 * | +3..+7 | reserved (live partial rows, future sidecars)    |
 *
 * Because a request sorts before its own node and after the previous line's
 * node, request headers land exactly where the model call happened, with no
 * fractional seqs. Prepending an older page never renumbers anything: seqs are
 * a pure function of `line_index`.
 */

/** Seq slots reserved per raw `events.jsonl` line. */
export const SEQ_SLOTS_PER_LINE = 8

/** Offset of the request that produced a line. */
export const SEQ_OFFSET_REQUEST = 0

/** Offset of the conversation node built from a line. */
export const SEQ_OFFSET_NODE = 1

/** Offset reserved for a step-end marker. */
export const SEQ_OFFSET_STEP_END = 2

/**
 * First seq owned by one ledger line.
 * @param lineIndex - Zero-based `events.jsonl` line.
 * @returns The line's seq block base.
 */
export function seqBase(lineIndex: number): number {
  return lineIndex * SEQ_SLOTS_PER_LINE
}

/**
 * Seq of the request anchored on one line.
 * @param lineIndex - Zero-based `events.jsonl` line.
 * @returns Request seq for that line.
 */
export function requestSeq(lineIndex: number): number {
  return seqBase(lineIndex) + SEQ_OFFSET_REQUEST
}

/**
 * Seq of the conversation node built from one line.
 * @param lineIndex - Zero-based `events.jsonl` line.
 * @returns Node seq for that line.
 */
export function nodeSeq(lineIndex: number): number {
  return seqBase(lineIndex) + SEQ_OFFSET_NODE
}

/**
 * Line that owns one seq.
 * @param seq - Any seq produced by this module.
 * @returns The zero-based `events.jsonl` line.
 */
export function lineIndexOfSeq(seq: number): number {
  return Math.floor(seq / SEQ_SLOTS_PER_LINE)
}
