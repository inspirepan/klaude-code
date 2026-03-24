import type { MessageItem, DeveloperMessageItem } from "../../types/message";
import { isQuestionSummaryUIExtra, isTodoListUIExtra } from "./message-ui-extra";
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

export type CollapseGroupEntry = MessageItem | SectionSubAgentBlock;

export interface SectionCollapseGroupBlock {
  type: "collapse_group";
  id: string;
  entries: CollapseGroupEntry[];
}

export interface SectionDevGroupBlock {
  type: "dev_group";
  id: string;
  items: DeveloperMessageItem[];
}

export type PlannedInnerBlock = SectionItemBlock | SectionSubAgentBlock | SectionDevGroupBlock;

export interface PlannedTodoItem {
  content: string;
  completed: boolean;
}

export interface SectionPlannedGroupBlock {
  type: "planned_group";
  id: string;
  todos: PlannedTodoItem[];
  blocks: PlannedInnerBlock[];
}

export type SectionBlock =
  | SectionItemBlock
  | SectionSubAgentBlock
  | SectionCollapseGroupBlock
  | SectionDevGroupBlock
  | SectionPlannedGroupBlock;

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

function isTodoWriteBlock(block: SectionBlock): block is SectionItemBlock {
  return (
    block.type === "item" && block.item.type === "tool_block" && block.item.toolName === "TodoWrite"
  );
}

function todoWriteHasInProgress(item: MessageItem): boolean {
  if (item.type !== "tool_block" || !item.uiExtra || !isTodoListUIExtra(item.uiExtra)) return false;
  return item.uiExtra.todo_list.todos.some((t) => t.status === "in_progress");
}


function getInProgressTodoContents(item: MessageItem): string[] {
  if (item.type !== "tool_block" || !item.uiExtra || !isTodoListUIExtra(item.uiExtra)) return [];
  return item.uiExtra.todo_list.todos
    .filter((t) => t.status === "in_progress")
    .map((t) => t.content);
}

/** Build PlannedTodoItems by comparing in_progress items against the next TodoWrite's state. */
function buildPlannedTodos(
  startItem: MessageItem,
  nextTodoWriteItem: MessageItem | null,
): PlannedTodoItem[] {
  const contents = getInProgressTodoContents(startItem);
  if (contents.length === 0) return [];

  // Build a set of completed contents from the next TodoWrite (if it exists)
  const completedSet = new Set<string>();
  if (
    nextTodoWriteItem &&
    nextTodoWriteItem.type === "tool_block" &&
    nextTodoWriteItem.uiExtra &&
    isTodoListUIExtra(nextTodoWriteItem.uiExtra)
  ) {
    for (const t of nextTodoWriteItem.uiExtra.todo_list.todos) {
      if (t.status === "completed") completedSet.add(t.content);
    }
  }

  return contents.map((content) => ({
    content,
    completed: completedSet.has(content),
  }));
}

function collapseEntryId(entry: CollapseGroupEntry): string {
  return entry.type === "sub_agent_group" ? entry.groupId : entry.id;
}

/** Apply the standard collapsible-merging pass to a slice of raw blocks. */
function mergeCollapsibleBlocks(
  rawBlocks: SectionBlock[],
  effectiveSessionId: string,
): SectionBlock[] {
  const blocks: SectionBlock[] = [];
  let pending: CollapseGroupEntry[] = [];

  const flushPending = (): void => {
    if (pending.length === 0) return;
    const hasToolOrSubAgent = pending.some(
      (e) => e.type === "tool_block" || e.type === "sub_agent_group",
    );
    if (hasToolOrSubAgent) {
      blocks.push({
        type: "collapse_group",
        id: `cg-${effectiveSessionId}-${collapseEntryId(pending[0])}`,
        entries: pending,
      });
    } else {
      // Only thinking / developer_message items remain
      for (const entry of pending) {
        const item = entry as MessageItem;
        if (item.type === "developer_message") {
          const last = blocks.at(-1);
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
    } else if (block.type === "sub_agent_group") {
      pending.push(block);
    } else {
      flushPending();
      blocks.push(block);
    }
  }
  flushPending();
  return blocks;
}

/** Collect raw blocks into planned-group inner blocks (flat, merging consecutive dev messages). */
function buildPlannedInnerBlocks(
  rawBlocks: SectionBlock[],
  start: number,
  end: number,
): PlannedInnerBlock[] {
  const inner: PlannedInnerBlock[] = [];
  for (let j = start; j < end; j++) {
    const b = rawBlocks[j];
    if (b.type === "item" && b.item.type === "developer_message") {
      const last = inner.at(-1);
      if (last?.type === "dev_group") {
        last.items.push(b.item);
      } else {
        inner.push({ type: "dev_group", id: b.item.id, items: [b.item] });
      }
    } else if (b.type === "item" || b.type === "sub_agent_group") {
      inner.push(b);
    }
  }
  return inner;
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
        const existingBlock = rawBlocks.at(existingBlockIndex);
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
        sourceSessionFork: subAgentForkBySessionId[sourceSessionId],
        toolCount: isToolBlock(item) ? 1 : 0,
      });
      subAgentBlockIndexBySessionId.set(sourceSessionId, blockIndex);
      i += 1;
    }

    // Second pass: identify planned intervals, then merge remaining collapsible items

    // Find TodoWrite block indices
    const todoWriteIndices: number[] = [];
    for (let k = 0; k < rawBlocks.length; k++) {
      if (isTodoWriteBlock(rawBlocks[k])) todoWriteIndices.push(k);
    }

    // Identify planned intervals: [in_progress TodoWrite, next TodoWrite)
    interface PlannedInterval {
      start: number;
      end: number;
      nextTodoWriteIdx: number | null;
    }
    const plannedIntervals: PlannedInterval[] = [];
    for (let t = 0; t < todoWriteIndices.length; t++) {
      const idx = todoWriteIndices[t];
      const block = rawBlocks[idx] as SectionItemBlock;
      if (todoWriteHasInProgress(block.item)) {
        const hasNext = t + 1 < todoWriteIndices.length;
        const end = hasNext ? todoWriteIndices[t + 1] : rawBlocks.length;
        plannedIntervals.push({
          start: idx,
          end,
          nextTodoWriteIdx: hasNext ? todoWriteIndices[t + 1] : null,
        });
      }
    }

    // Group adjacent planned intervals into chains.
    // Each chain gets a single overview card (using the latest TodoWrite state)
    // and all TodoWrites before/after the chain that belong to the same plan are suppressed.
    interface PlannedChain {
      intervals: PlannedInterval[];
    }
    const chains: PlannedChain[] = [];
    for (const interval of plannedIntervals) {
      const lastChain = chains.at(-1);
      const lastInterval = lastChain?.intervals.at(-1);
      if (lastInterval && lastInterval.end === interval.start) {
        lastChain.intervals.push(interval);
      } else {
        chains.push({ intervals: [interval] });
      }
    }

    // Build final blocks
    const blocks: SectionBlock[] = [];
    let cursor = 0;

    for (const chain of chains) {
      const chainStart = chain.intervals[0].start;
      const lastInterval = chain.intervals[chain.intervals.length - 1];
      const chainEnd = lastInterval.end;

      // Determine the overview item: use the summary TodoWrite after the chain if
      // available, otherwise fall back to the last interval's start item.
      let overviewItem: MessageItem;
      let summaryIdx: number | null = null;
      const summaryBlock = chainEnd < rawBlocks.length ? rawBlocks[chainEnd] : null;
      if (summaryBlock && isTodoWriteBlock(summaryBlock)) {
        overviewItem = summaryBlock.item;
        summaryIdx = chainEnd;
      } else {
        overviewItem = (rawBlocks[lastInterval.start] as SectionItemBlock).item;
      }

      // Process gap [cursor, chainStart): keep non-TodoWrite blocks, suppress TodoWrites
      if (cursor < chainStart) {
        const gapBlocks = rawBlocks
          .slice(cursor, chainStart)
          .filter((b) => !isTodoWriteBlock(b));
        if (gapBlocks.length > 0) {
          blocks.push(...mergeCollapsibleBlocks(gapBlocks, effectiveSessionId));
        }
      }

      // Emit a single overview card with the latest state
      blocks.push({ type: "item", item: overviewItem });

      // Emit planned_groups for each interval in the chain
      for (const interval of chain.intervals) {
        const startItem = (rawBlocks[interval.start] as SectionItemBlock).item;
        const nextItem =
          interval.nextTodoWriteIdx !== null
            ? (rawBlocks[interval.nextTodoWriteIdx] as SectionItemBlock).item
            : null;
        blocks.push({
          type: "planned_group",
          id: `pg-${effectiveSessionId}-${startItem.id}`,
          todos: buildPlannedTodos(startItem, nextItem),
          blocks: buildPlannedInnerBlocks(rawBlocks, interval.start + 1, interval.end),
        });
      }

      // Advance cursor past the chain and its summary TodoWrite (if suppressed)
      cursor = summaryIdx !== null ? summaryIdx + 1 : chainEnd;
    }

    if (cursor < rawBlocks.length) {
      blocks.push(...mergeCollapsibleBlocks(rawBlocks.slice(cursor), effectiveSessionId));
    }

    return blocks;
  });
}
