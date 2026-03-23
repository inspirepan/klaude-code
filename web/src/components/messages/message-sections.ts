import type { MessageItem, DeveloperMessageItem } from "../../types/message";
import { isQuestionSummaryUIExtra } from "./message-ui-extra";
import { isToolBlock } from "./message-list-ui";

export interface SectionItemBlock {
  type: "item";
  item: MessageItem;
}

export interface SectionSubAgentBlock {
  type: "sub_agent_group";
  groupId: string;
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  sourceSessionFork: boolean;
  toolCount: number;
}

export interface SectionCollapseGroupBlock {
  type: "collapse_group";
  id: string;
  items: MessageItem[];
}

export interface SectionDevGroupBlock {
  type: "dev_group";
  id: string;
  items: DeveloperMessageItem[];
}

export type SectionBlock =
  | SectionItemBlock
  | SectionSubAgentBlock
  | SectionCollapseGroupBlock
  | SectionDevGroupBlock;

const NON_COLLAPSIBLE_TOOLS = new Set(["TodoWrite"]);

function isCollapsibleItem(item: MessageItem): boolean {
  if (item.type === "tool_block") {
    return !isQuestionSummaryUIExtra(item.uiExtra) && !NON_COLLAPSIBLE_TOOLS.has(item.toolName);
  }
  return item.type === "thinking" || item.type === "developer_message";
}

export function extractSearchableText(item: MessageItem): string {
  switch (item.type) {
    case "user_message":
      return item.content;
    case "thinking":
      return item.content;
    case "assistant_text":
      return item.content;
    case "tool_block":
      return `${item.toolName}\n${item.arguments}\n${item.result ?? ""}`;
    case "developer_message":
      return "";
    case "task_metadata":
      return "";
    case "error":
      return item.message;
    case "interrupt":
      return "Interrupted by user";
    case "compaction_summary":
      return item.content;
    case "unknown_event":
      return `${item.eventType}\n${JSON.stringify(item.rawEvent)}`;
  }
}

export function findMatchingItemIds(items: MessageItem[], query: string): string[] {
  if (!query.trim()) return [];
  const lower = query.toLowerCase();
  return items
    .filter((item) => extractSearchableText(item).toLowerCase().includes(lower))
    .map((item) => item.id);
}

/** Split visible items into sections starting at each effective-session user message. */
export function buildSections(
  visibleItems: MessageItem[],
  sessionId: string,
  effectiveSessionId: string,
): MessageItem[][] {
  const result: MessageItem[][] = [];
  let current: MessageItem[] = [];
  for (const item of visibleItems) {
    const sourceSessionId = item.sessionId ?? sessionId;
    const isEffectiveUserMessage =
      item.type === "user_message" && sourceSessionId === effectiveSessionId;
    if (isEffectiveUserMessage && current.length > 0) {
      result.push(current);
      current = [];
    }
    current.push(item);
  }
  if (current.length > 0) result.push(current);
  return result;
}

/** Build section blocks: group sub-agent items, then merge consecutive collapsible items. */
export function buildSectionBlocks(
  sections: MessageItem[][],
  sessionId: string,
  effectiveSessionId: string,
  subAgentDescBySessionId: Record<string, string>,
  subAgentTypeBySessionId: Record<string, string>,
  subAgentForkBySessionId: Record<string, boolean>,
): SectionBlock[][] {
  return sections.map((section) => {
    // First pass: group sub-agent items
    const rawBlocks: SectionBlock[] = [];
    const subAgentBlockIndexBySessionId = new Map<string, number>();
    let i = 0;
    while (i < section.length) {
      const item = section[i];
      const sourceSessionId = item.sessionId ?? sessionId;
      if (sourceSessionId === effectiveSessionId) {
        rawBlocks.push({ type: "item", item });
        i += 1;
        continue;
      }

      const existingBlockIndex = subAgentBlockIndexBySessionId.get(sourceSessionId);
      if (existingBlockIndex !== undefined) {
        const existingBlock = rawBlocks[existingBlockIndex];
        if (existingBlock?.type === "sub_agent_group" && item.type === "tool_block") {
          existingBlock.toolCount += 1;
        }
        i += 1;
        continue;
      }

      const blockIndex = rawBlocks.length;
      rawBlocks.push({
        type: "sub_agent_group",
        groupId: `${effectiveSessionId}-${section[0]?.id ?? sourceSessionId}-${sourceSessionId}`,
        sourceSessionId,
        sourceSessionType: subAgentTypeBySessionId[sourceSessionId] ?? null,
        sourceSessionDesc: subAgentDescBySessionId[sourceSessionId] ?? null,
        sourceSessionFork: subAgentForkBySessionId[sourceSessionId] === true,
        toolCount: isToolBlock(item) ? 1 : 0,
      });
      subAgentBlockIndexBySessionId.set(sourceSessionId, blockIndex);
      i += 1;
    }

    // Second pass: merge consecutive thinking/tool_block items into collapse groups
    const blocks: SectionBlock[] = [];
    let pending: MessageItem[] = [];

    const flushPending = (): void => {
      if (pending.length === 0) return;
      const hasToolBlock = pending.some((item) => item.type === "tool_block");
      if (hasToolBlock) {
        blocks.push({
          type: "collapse_group",
          id: `cg-${effectiveSessionId}-${pending[0].id}`,
          items: pending,
        });
      } else {
        // Split apart, but merge consecutive developer_message items
        for (const item of pending) {
          if (item.type === "developer_message") {
            const last = blocks[blocks.length - 1];
            if (last?.type === "dev_group") {
              last.items.push(item);
            } else {
              blocks.push({ type: "dev_group", id: item.id, items: [item] });
            }
          } else {
            blocks.push({ type: "item", item });
          }
        }
      }
      pending = [];
    };

    for (const block of rawBlocks) {
      if (block.type === "item" && isCollapsibleItem(block.item)) {
        pending.push(block.item);
      } else {
        flushPending();
        blocks.push(block);
      }
    }
    flushPending();
    return blocks;
  });
}
