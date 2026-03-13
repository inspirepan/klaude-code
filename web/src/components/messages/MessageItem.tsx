import { memo } from "react";

import type { MessageItem as MessageItemType } from "../../types/message";
import { UserMessage } from "./UserMessage";
import { ThinkingBlock } from "./ThinkingBlock";
import { AssistantText } from "./AssistantText";
import { ToolBlock } from "./ToolBlock";
import { DeveloperMessage } from "./DeveloperMessage";
import { TaskWorked } from "./TaskWorked";
import { ErrorMessage } from "./ErrorMessage";
import { InterruptMessage } from "./InterruptMessage";
import { CompactionSummary } from "./CompactionSummary";
import { UnknownEvent } from "./UnknownEvent";

interface MessageItemProps {
  item: MessageItemType;
  compact?: boolean;
  workDir?: string;
}

function MessageItemInner({ item, compact = false, workDir }: MessageItemProps): JSX.Element {
  switch (item.type) {
    case "user_message":
      return <UserMessage key={item.id} item={item} compact={compact} />;
    case "thinking":
      return <ThinkingBlock item={item} />;
    case "assistant_text":
      return <AssistantText item={item} compact={compact} />;
    case "tool_block":
      return <ToolBlock item={item} compact={compact} workDir={workDir} />;
    case "developer_message":
      return <DeveloperMessage items={[item]} />;
    case "task_worked":
      return <TaskWorked item={item} compact={compact} />;
    case "error":
      return <ErrorMessage item={item} compact={compact} />;
    case "interrupt":
      return <InterruptMessage item={item} compact={compact} />;
    case "compaction_summary":
      return <CompactionSummary item={item} />;
    case "unknown_event":
      return <UnknownEvent item={item} compact={compact} />;
  }
}

export const MessageItem = memo(
  MessageItemInner,
  (prev, next) =>
    prev.item === next.item && prev.compact === next.compact && prev.workDir === next.workDir,
);
