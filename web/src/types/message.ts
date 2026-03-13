export type MessageItemId = string;

/** Unix timestamp in seconds, null if unavailable */
export type ItemTimestamp = number | null;

export interface MessageImageURLPart {
  type: "image_url";
  url: string;
}

export interface MessageImageFilePart {
  type: "image_file";
  file_path: string;
  mime_type?: string | null;
  byte_size?: number | null;
  sha256?: string | null;
}

export type MessageImagePart = MessageImageURLPart | MessageImageFilePart;

export interface UserMessageItem {
  id: MessageItemId;
  type: "user_message";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  content: string;
  images: MessageImagePart[];
}

export interface ThinkingBlockItem {
  id: MessageItemId;
  type: "thinking";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  content: string;
  isStreaming: boolean;
}

export interface AssistantTextItem {
  id: MessageItemId;
  type: "assistant_text";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  responseId: string | null;
  content: string;
  isStreaming: boolean;
}

export interface ToolBlockItem {
  id: MessageItemId;
  type: "tool_block";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  toolCallId: string;
  toolName: string;
  arguments: string;
  result: string | null;
  resultStatus: "success" | "error" | "aborted" | null;
  uiExtra: Record<string, unknown> | null;
  isStreaming: boolean;
  /** Incremental output received via tool.output.delta while the tool is still running. */
  streamingContent: string;
}

export interface MemoryLoadedUIItem {
  type: "memory_loaded";
  files: Array<{
    path: string;
    mentioned_patterns: string[];
  }>;
}

export interface ExternalFileChangesUIItem {
  type: "external_file_changes";
  paths: string[];
}

export interface TodoReminderUIItem {
  type: "todo_reminder";
  reason: "empty" | "not_used_recently";
}

export interface AtFileOp {
  operation: "Read" | "List";
  path: string;
  mentioned_in: string | null;
}

export interface AtFileOpsUIItem {
  type: "at_file_ops";
  ops: AtFileOp[];
}

export interface UserImagesUIItem {
  type: "user_images";
  count: number;
  paths: string[];
}

export interface SkillActivatedUIItem {
  type: "skill_activated";
  name: string;
}

export interface AtFileImagesUIItem {
  type: "at_file_images";
  paths: string[];
}

export type DeveloperUIItem =
  | MemoryLoadedUIItem
  | ExternalFileChangesUIItem
  | TodoReminderUIItem
  | AtFileOpsUIItem
  | UserImagesUIItem
  | SkillActivatedUIItem
  | AtFileImagesUIItem;

export interface DeveloperMessageItem {
  id: MessageItemId;
  type: "developer_message";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  items: DeveloperUIItem[];
}

export interface TaskWorkedItem {
  id: MessageItemId;
  type: "task_worked";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  durationSeconds: number;
  turnCount: number;
}

export interface InterruptItem {
  id: MessageItemId;
  type: "interrupt";
  timestamp: ItemTimestamp;
  sessionId: string | null;
}

export interface ErrorItem {
  id: MessageItemId;
  type: "error";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  message: string;
  canRetry: boolean;
}

export interface CompactionSummaryItem {
  id: MessageItemId;
  type: "compaction_summary";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  content: string;
}

export interface UnknownEventItem {
  id: MessageItemId;
  type: "unknown_event";
  timestamp: ItemTimestamp;
  sessionId: string | null;
  eventType: string;
  rawEvent: Record<string, unknown>;
}

export type MessageItem =
  | UserMessageItem
  | ThinkingBlockItem
  | AssistantTextItem
  | ToolBlockItem
  | DeveloperMessageItem
  | ErrorItem
  | InterruptItem
  | CompactionSummaryItem
  | TaskWorkedItem
  | UnknownEventItem;
