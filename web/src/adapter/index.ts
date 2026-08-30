/** klaude REST ledger -> trajectory snapshot adapter. */

export { buildTrajectorySnapshot } from './snapshot.ts'
export type { BuildSnapshotOptions } from './snapshot.ts'
export { applyTrajectoryAnnotations } from './annotate.ts'
export { localImageUrl } from './images.ts'
export {
  SEQ_SLOTS_PER_LINE, lineIndexOfSeq, nodeSeq, requestSeq, seqBase,
} from './seq.ts'
export { autoUserReason, isCheckpointReminder } from './classify.ts'
export type { AutoUserReason } from './classify.ts'
export { decodeUsage, toAssistantTiming, toUsageLike } from './usage.ts'
export type { KlaudeUsage, UsageLike } from './usage.ts'
export { decodeLLMRequest, requestOptions } from './llm-request.ts'
export type { LLMRequestRecord, LLMRequestStatus } from './llm-request.ts'
export {
  REBUILT_CAVEAT_KEY, promptConfig, promptSnapshot, promptTools, toolSchemasByName,
} from './system-context.ts'
export type {
  HistoryPage, HistoryRow, HistoryRowStatus, RawEntry, SessionListRow, SessionMeta,
  SessionState, SystemContext, SystemContextModel, SystemContextTool,
} from './wire.ts'
