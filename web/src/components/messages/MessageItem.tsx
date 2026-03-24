import { memo } from "react";

import type { MessageItem as MessageItemType } from "../../types/message";
import { UserMessage } from "./UserMessage";
import { ThinkingBlock } from "./ThinkingBlock";
import { AssistantText } from "./AssistantText";
import { ToolBlock } from "./ToolBlock";
import { DeveloperMessage } from "./DeveloperMessage";
import { TaskMetadata } from "./TaskMetadata";
import { ErrorMessage } from "./ErrorMessage";
import { InterruptMessage } from "./InterruptMessage";
import { CompactionSummary } from "./CompactionSummary";
import { RewindSummary } from "./RewindSummary";
import { UnknownEvent } from "./UnknownEvent";

interface MessageItemProps {
  item: MessageItemType;
  workDir?: string;
}

function MessageItemInner({ item, workDir }: MessageItemProps): React.JSX.Element {
  switch (item.type) {
    case "user_message":
      return <UserMessage key={item.id} item={item} />;
    case "thinking":
      return <ThinkingBlock item={item} />;
    case "assistant_text":
      return <AssistantText item={item} />;
    case "tool_block":
      return <ToolBlock item={item} workDir={workDir} />;
    case "developer_message":
      return <DeveloperMessage items={[item]} />;
    case "task_metadata":
      return <TaskMetadata item={item} />;
    case "error":
      return <ErrorMessage item={item} />;
    case "interrupt":
      return <InterruptMessage item={item} />;
    case "compaction_summary":
      return <CompactionSummary item={item} />;
    case "rewind_summary":
      return <RewindSummary item={item} />;
    case "unknown_event":
      return <UnknownEvent item={item} />;
  }
}

export const MessageItem = memo(
  MessageItemInner,
  (prev, next) => prev.item === next.item && prev.workDir === next.workDir,
);
