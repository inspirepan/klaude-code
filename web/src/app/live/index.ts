/** Live (WebSocket) state for an online session: `partial` + `runningCalls`. */

export { parseLiveFrames, parseLiveMessage } from './frames.ts'
export type { LiveControlFrame, LiveEnvelope, LiveFrame } from './frames.ts'
export {
  applyLandedRows, initialLiveState, liveReducer, liveSocketClosed, liveSocketOpened,
  reduceLiveFrames,
} from './reducer.ts'
export type { LivePartial, LiveState, LiveToolCall } from './reducer.ts'
export { hasStatusMarker, mergeHistoryTail, refreshRowStatuses } from './merge.ts'
export type {
  HistoryMergeResult, HistoryPageFetcher, HistoryPageQuery, LoadedWindow,
} from './merge.ts'
export { spliceLiveSnapshot, trajectoryAnchor } from './splice.ts'
export type { TrajectoryAnchor } from './splice.ts'
export { liveSocketUrl, useLiveSession } from './use-live-session.ts'
export type { LiveSession } from './use-live-session.ts'
