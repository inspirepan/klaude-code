import type { MessageItem as MessageItemType } from "../../types/message";
import { UserMessage } from "./UserMessage";
import { ThinkingBlock } from "./ThinkingBlock";
import { AssistantText } from "./AssistantText";
import { ToolBlock } from "./ToolBlock";
import { DeveloperMessage } from "./DeveloperMessage";
import { TaskWorked } from "./TaskWorked";
import { UnknownEvent } from "./UnknownEvent";

interface MessageItemProps {
  item: MessageItemType;
}

export function MessageItem({ item }: MessageItemProps): JSX.Element {
  switch (item.type) {
    case "user_message":
      return <UserMessage item={item} />;
    case "thinking":
      return <ThinkingBlock item={item} />;
    case "assistant_text":
      return <AssistantText item={item} />;
    case "tool_block":
      return <ToolBlock item={item} />;
    case "developer_message":
      return <DeveloperMessage item={item} />;
    case "task_worked":
      return <TaskWorked item={item} />;
    case "unknown_event":
      return <UnknownEvent item={item} />;
  }
}
