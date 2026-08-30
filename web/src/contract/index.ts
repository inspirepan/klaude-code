/**
 * Conversation contract barrel: the seam the vendored trajectory UI imports
 * instead of the upstream ui-conversation client package.
 */

export type {
  ImageAttachmentRef,
  ImageMediaType,
  ContentBlock,
  ToolSchema,
  MessageId,
  ConversationLocation,
  MessageImageSource,
  MessageImagesOwnerProps,
  RenderMessageImages,
} from './types.ts'

export type {
  ContextRole,
  ContextProvenanceView,
  KnownContextForm,
} from './context-provenance.ts'

export type {
  AssistantRequestConfig,
  AssistantProvenanceView,
  AssistantBlock,
  UserMessageNode,
  AssistantTiming,
  AssistantMessageNode,
  SteeringMessageNode,
  ContextMessageNode,
  ToolResultNode,
  CompactionSummaryNode,
  ConversationNode,
  RunningToolCall,
  ToolCallBlock,
  PartialAssistant,
} from './records.ts'

export type {
  ConversationPromptSnapshot,
  RequestPromptChange,
  RequestPromptInspection,
  RequestView,
  RequestInspectionSnapshot,
} from './request-inspection.ts'
