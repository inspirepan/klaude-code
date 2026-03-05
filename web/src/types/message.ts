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
}

export type MessageImagePart = MessageImageURLPart | MessageImageFilePart;

export interface UserMessageItem {
  id: MessageItemId;
  type: "user_message";
  timestamp: ItemTimestamp;
  content: string;
  images: MessageImagePart[];
}

export interface ThinkingBlockItem {
  id: MessageItemId;
  type: "thinking";
  timestamp: ItemTimestamp;
  content: string;
  isStreaming: boolean;
}

export interface AssistantTextItem {
  id: MessageItemId;
  type: "assistant_text";
  timestamp: ItemTimestamp;
  content: string;
  isStreaming: boolean;
}

export interface ToolBlockItem {
  id: MessageItemId;
  type: "tool_block";
  timestamp: ItemTimestamp;
  toolCallId: string;
  toolName: string;
  arguments: string;
  result: string | null;
  resultStatus: "success" | "error" | "aborted" | null;
  uiExtra: Record<string, unknown> | null;
  isStreaming: boolean;
}

export interface UnknownEventItem {
  id: MessageItemId;
  type: "unknown_event";
  timestamp: ItemTimestamp;
  eventType: string;
  rawEvent: Record<string, unknown>;
}

export type MessageItem =
  | UserMessageItem
  | ThinkingBlockItem
  | AssistantTextItem
  | ToolBlockItem
  | UnknownEventItem;
