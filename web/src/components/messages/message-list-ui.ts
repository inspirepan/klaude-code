import type { SessionStatusState } from "../../stores/event-reducer";
import type {
  AssistantTextItem,
  MessageItem as MessageItemType,
  ToolBlockItem,
} from "../../types/message";

const COMPACT_NUMBER_FORMATTER = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function shortSessionId(id: string): string {
  return id.slice(0, 8);
}

export function formatSubAgentTypeLabel(type: string | null): string {
  if (type === null || type.trim().length === 0) {
    return "Agent";
  }
  return type.charAt(0).toUpperCase() + type.slice(1);
}

export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  if (Math.abs(value) < 1000) return Math.round(value).toString();
  return COMPACT_NUMBER_FORMATTER.format(value);
}

export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m${remainingSeconds.toString().padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h${remainingMinutes.toString().padStart(2, "0")}m`;
}

export function getSessionActivityText(status: SessionStatusState | null): string | null {
  if (status === null) return null;
  return status.awaitingInput
    ? "Waiting for input …"
    : status.compacting
      ? "Compacting …"
      : status.thinkingActive
        ? "Thinking …"
        : status.isComposing
          ? "Typing …"
          : status.taskActive
            ? "Running …"
            : null;
}

export function isCopyableAssistantText(item: MessageItemType): item is AssistantTextItem {
  return item.type === "assistant_text" && !item.isStreaming && item.content.split("\n").length > 5;
}

export function isToolBlock(item: MessageItemType): item is ToolBlockItem {
  return item.type === "tool_block";
}
