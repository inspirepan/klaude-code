import type { MessageItem as MessageItemType } from "../../types/message";
import { UserMessage } from "./UserMessage";
import { ThinkingBlock } from "./ThinkingBlock";
import { AssistantText } from "./AssistantText";
import { ToolBlock } from "./ToolBlock";
import { DeveloperMessage } from "./DeveloperMessage";
import { TaskWorked } from "./TaskWorked";
import { CompactionSummary } from "./CompactionSummary";
import { UnknownEvent } from "./UnknownEvent";

interface MessageItemProps {
  item: MessageItemType;
  compact?: boolean;
}

export function MessageItem({ item, compact = false }: MessageItemProps): JSX.Element {
  switch (item.type) {
    case "user_message":
      return <UserMessage key={item.id} item={item} compact={compact} />;
    case "thinking":
      return <ThinkingBlock item={item} />;
    case "assistant_text":
      return <AssistantText item={item} compact={compact} />;
    case "tool_block":
      return <ToolBlock item={item} compact={compact} />;
    case "developer_message":
      return <DeveloperMessage item={item} />;
    case "task_worked":
      return <TaskWorked item={item} compact={compact} />;
    case "compaction_summary":
      return <CompactionSummary item={item} />;
    case "unknown_event":
      return <UnknownEvent item={item} compact={compact} />;
  }
}
