// klaude: upstream cross-package imports -> the local flattened contract
import type {
  ConversationLocation, ConversationNode, ConversationPromptSnapshot, PartialAssistant,
  RequestPromptChange, RequestView, RunningToolCall, TrajectoryAnnotations,
} from '../contract/index.ts'

/** Request-header facts retained by the Trajectory target. */
export interface TrajectoryRequestHeaderState {
  readonly seq: number
  readonly time: number
  readonly prompt: ConversationPromptSnapshot
  readonly change?: RequestPromptChange
  readonly location: ConversationLocation
}

// klaude: TrajectoryContribution / TrajectoryConversationViewNode / UseTrajectory and
// the two `declare module` augmentations dropped — they belong to the upstream
// Definition pipeline and slot registry, which this fork replaces with an adapter

/** Stage-oriented Trajectory data assembled from registered business Contexts. */
export interface TrajectorySnapshot {
  readonly eventNodes: readonly ConversationNode[]
  readonly eventLocations: ReadonlyMap<number, ConversationLocation>
  readonly requests: readonly RequestView[]
  readonly callSchemas: ReadonlyMap<string, ConversationPromptSnapshot['tools'][number]>
  readonly partial: PartialAssistant | null
  readonly runningCalls: readonly RunningToolCall[]
  /** klaude: per-record ledger facts `layout.ts` cannot derive (src/adapter). */
  readonly annotations?: TrajectoryAnnotations
}
