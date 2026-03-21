import type { SessionStatusState } from "../../stores/event-reducer";
import type {
  AssistantTextItem,
  ItemTimestamp,
  MessageItem as MessageItemType,
  ToolBlockItem,
} from "../../types/message";

const COMPACT_NUMBER_FORMATTER = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export interface SubAgentMetaRow {
  label: string;
  value: string;
}

export function shortSessionId(id: string): string {
  return id.slice(0, 8);
}

export function formatSubAgentTypeLabel(type: string | null): string {
  if (type === null || type.trim().length === 0) {
    return "Agent";
  }
  return type.charAt(0).toUpperCase() + type.slice(1);
}

export function formatTime(ts: ItemTimestamp): string | null {
  if (ts === null) return null;
  const date = new Date(ts * 1000);
  const time = date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const day = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${day} ${time}`;
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

function formatCurrency(total: number, currency: string): string {
  const symbol = currency === "CNY" ? "¥" : "$";
  return `${symbol}${total.toFixed(4)}`;
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

export function getSessionSummaryParts(
  status: SessionStatusState | null,
  nowSeconds: number,
): string[] {
  if (status === null) return [];

  const parts: string[] = [];
  if (status.contextPercent !== null) {
    parts.push(`${status.contextPercent.toFixed(1)}%`);
  }
  if (status.totalCost !== null) {
    parts.push(formatCurrency(status.totalCost, status.currency));
  }
  if (
    status.taskStartedAt !== null &&
    (status.taskActive || status.awaitingInput || status.compacting)
  ) {
    parts.push(formatElapsed(nowSeconds - status.taskStartedAt));
  }
  return parts;
}

export function getSessionMetaRows(
  status: SessionStatusState | null,
  nowSeconds: number,
): SubAgentMetaRow[] {
  if (status === null) return [];

  const rows: SubAgentMetaRow[] = [];
  if (status.tokenInput !== null) {
    rows.push({ label: "Input", value: formatCompactNumber(status.tokenInput) });
  }
  if ((status.tokenCached ?? 0) > 0) {
    rows.push({ label: "Cached Read", value: formatCompactNumber(status.tokenCached ?? 0) });
  }
  if (status.cacheHitRate !== null) {
    rows.push({ label: "Cache Hit Rate", value: `${Math.round(status.cacheHitRate * 100)}%` });
  }
  if ((status.tokenCacheWrite ?? 0) > 0) {
    rows.push({ label: "Cached Write", value: formatCompactNumber(status.tokenCacheWrite ?? 0) });
  }
  if (status.tokenOutput !== null) {
    rows.push({ label: "Output", value: formatCompactNumber(status.tokenOutput) });
  }
  if ((status.tokenThought ?? 0) > 0) {
    rows.push({ label: "Thought", value: formatCompactNumber(status.tokenThought ?? 0) });
  }
  if (
    status.contextSize !== null &&
    status.contextEffectiveLimit !== null &&
    status.contextPercent !== null
  ) {
    rows.push({
      label: "Context",
      value: `${formatCompactNumber(status.contextSize)}/${formatCompactNumber(status.contextEffectiveLimit)} (${status.contextPercent.toFixed(1)}%)`,
    });
  }
  if (status.totalCost !== null) {
    rows.push({ label: "Cost", value: formatCurrency(status.totalCost, status.currency) });
  }
  if (
    status.taskStartedAt !== null &&
    (status.taskActive || status.awaitingInput || status.compacting)
  ) {
    rows.push({ label: "Elapsed", value: formatElapsed(nowSeconds - status.taskStartedAt) });
  }
  return rows;
}

export function isCopyableAssistantText(item: MessageItemType): item is AssistantTextItem {
  return item.type === "assistant_text" && !item.isStreaming && item.content.split("\n").length > 5;
}

export function isToolBlock(item: MessageItemType): item is ToolBlockItem {
  return item.type === "tool_block";
}
