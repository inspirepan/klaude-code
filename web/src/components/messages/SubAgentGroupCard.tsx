import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ChevronRight } from "lucide-react";

import type { SessionStatusState } from "../../stores/event-reducer";
import type { DeveloperMessageItem, MessageItem as MessageItemType } from "../../types/message";
import { CollapseGroupBlock } from "./CollapseGroupBlock";
import { DeveloperMessage } from "./DeveloperMessage";
import { MessageRow } from "./MessageRow";
import { SubAgentStatusSummary } from "./SubAgentStatusSummary";
import {
  formatSubAgentTypeLabel,
  getSessionActivityText,
  getSessionMetaRows,
  getSessionSummaryParts,
  isToolBlock,
  shortSessionId,
} from "./message-list-ui";
import { isQuestionSummaryUIExtra, isTodoListUIExtra } from "./message-ui-extra";

const COLLAPSED_HEIGHT = 180;
const DURATION_MS = 200;

function isCollapsibleItem(item: MessageItemType): boolean {
  if (item.type === "tool_block") {
    return !isTodoListUIExtra(item.uiExtra) && !isQuestionSummaryUIExtra(item.uiExtra);
  }
  return item.type === "thinking" || item.type === "developer_message";
}

type ExpandedBlock =
  | { type: "item"; item: MessageItemType }
  | { type: "collapse_group"; id: string; items: MessageItemType[] }
  | { type: "dev_group"; id: string; items: DeveloperMessageItem[] };

function groupItemsIntoBlocks(items: MessageItemType[]): ExpandedBlock[] {
  const blocks: ExpandedBlock[] = [];
  let pending: MessageItemType[] = [];

  const flushPending = () => {
    if (pending.length === 0) return;
    const hasToolBlock = pending.some((item) => item.type === "tool_block");
    if (hasToolBlock) {
      blocks.push({
        type: "collapse_group",
        id: `cg-${pending[0]!.id}`,
        items: pending,
      });
    } else {
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

  for (const item of items) {
    if (isCollapsibleItem(item)) {
      pending.push(item);
    } else {
      flushPending();
      blocks.push({ type: "item", item });
    }
  }
  flushPending();

  return blocks;
}

interface SubAgentGroupCardProps {
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  sourceSessionFork: boolean;
  items: MessageItemType[];
  collapsed: boolean;
  status: SessionStatusState | null;
  isFinished: boolean;
  nowSeconds: number;
  activeItemId: string | null;
  copiedItemId: string | null;
  metaOpen: boolean;
  workDir: string;
  onToggleCollapsed: () => void;
  onMetaOpenChange: (open: boolean) => void;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

export function SubAgentGroupCard({
  sourceSessionId,
  sourceSessionType,
  sourceSessionDesc,
  sourceSessionFork,
  items,
  collapsed,
  status,
  isFinished,
  nowSeconds,
  activeItemId,
  copiedItemId,
  metaOpen,
  workDir,
  onToggleCollapsed,
  onMetaOpenChange,
  onCopy,
  setItemRef,
}: SubAgentGroupCardProps): JSX.Element {
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [hasCollapsedOverflow, setHasCollapsedOverflow] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const contentInnerRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(false);
  const collapsedRef = useRef(collapsed);
  useEffect(() => {
    collapsedRef.current = collapsed;
  }, [collapsed]);

  const toolItems = items.filter(isToolBlock);
  const activityText = getSessionActivityText(status);
  const summaryParts = getSessionSummaryParts(status, nowSeconds);
  const metaRows = getSessionMetaRows(status, nowSeconds);

  const expandedBlocks = useMemo(() => groupItemsIntoBlocks(items), [items]);

  const lastCollapseGroupId = useMemo(() => {
    for (let i = expandedBlocks.length - 1; i >= 0; i--) {
      const block = expandedBlocks[i];
      if (block?.type === "collapse_group") return block.id;
    }
    return null;
  }, [expandedBlocks]);

  const [prevFinished, setPrevFinished] = useState(isFinished);
  if (prevFinished !== isFinished) {
    setPrevFinished(isFinished);
    if (!prevFinished && isFinished) {
      setCollapsedGroups({});
    }
  }

  const isCollapseGroupCollapsed = useCallback(
    (groupId: string): boolean => {
      if (activeItemId !== null) {
        for (const block of expandedBlocks) {
          if (
            block.type === "collapse_group" &&
            block.id === groupId &&
            block.items.some((item) => item.id === activeItemId)
          ) {
            return false;
          }
        }
      }
      if (groupId in collapsedGroups) {
        return collapsedGroups[groupId]!;
      }
      // While running, keep the last (newest) group expanded; otherwise all collapsed
      if (!isFinished) {
        return groupId !== lastCollapseGroupId;
      }
      return true;
    },
    [activeItemId, collapsedGroups, expandedBlocks, isFinished, lastCollapseGroupId],
  );

  useEffect(() => {
    const el = contentRef.current;
    const innerEl = contentInnerRef.current;
    if (!el || !innerEl) return;

    const updateOverflow = (): void => {
      setHasCollapsedOverflow(el.scrollHeight > COLLAPSED_HEIGHT + 1);
      // Keep height in sync while collapsed: as items stream in, the content
      // area should grow up to COLLAPSED_HEIGHT, then stay capped there.
      if (collapsedRef.current && el.style.height !== "auto") {
        const target = `${Math.min(el.scrollHeight, COLLAPSED_HEIGHT)}px`;
        if (el.style.height !== target) {
          el.style.height = target;
        }
      }
    };

    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(innerEl);
    return () => observer.disconnect();
  }, [expandedBlocks]);

  // Animate height transition between collapsed and expanded
  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    if (!mountedRef.current) {
      mountedRef.current = true;
      if (collapsed) {
        el.style.height = `${Math.min(el.scrollHeight, COLLAPSED_HEIGHT)}px`;
      }
      return;
    }

    if (!collapsed) {
      // Expanding: animate from current height to full content height, then release to auto
      el.style.height = `${el.scrollHeight}px`;
      const timer = setTimeout(() => {
        el.style.height = "auto";
      }, DURATION_MS + 10);
      return () => clearTimeout(timer);
    } else {
      // Collapsing: snapshot current height, force reflow, then animate to collapsed height
      const targetHeight = Math.min(el.scrollHeight, COLLAPSED_HEIGHT);
      el.style.transition = "none";
      el.style.height = `${el.getBoundingClientRect().height}px`;
      void el.offsetHeight;
      el.style.transition = "";
      el.style.height = `${targetHeight}px`;
    }
  }, [collapsed]);

  const renderBlock = (block: ExpandedBlock) => {
    if (block.type === "collapse_group") {
      const cgCollapsed = collapsed ? true : isCollapseGroupCollapsed(block.id);
      return (
        <CollapseGroupBlock
          key={block.id}
          items={block.items}
          collapsed={cgCollapsed}
          onToggle={
            collapsed
              ? onToggleCollapsed
              : () => {
                  setCollapsedGroups((prev) => ({
                    ...prev,
                    [block.id]: !cgCollapsed,
                  }));
                }
          }
          activeItemId={activeItemId}
          copiedItemId={copiedItemId}
          workDir={workDir}
          onCopy={onCopy}
          setItemRef={setItemRef}
        />
      );
    }
    if (block.type === "dev_group") {
      return <DeveloperMessage key={block.id} items={block.items} />;
    }
    return (
      <MessageRow
        key={block.item.id}
        item={block.item}
        variant="subagent"
        workDir={workDir}
        isActive={block.item.id === activeItemId}
        copied={copiedItemId === block.item.id}
        onCopy={onCopy}
        itemRef={(el) => {
          setItemRef(block.item.id, el);
        }}
      />
    );
  };

  return (
    <div className="group/subagent flex min-w-0 gap-4">
      <div className="min-w-0 flex-1 rounded-xl border border-neutral-200/80 bg-surface/50 shadow-sm shadow-neutral-200/40">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="flex w-full cursor-pointer items-center gap-2 px-4 py-3 text-left"
        >
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 text-neutral-300 transition-transform duration-150 ${collapsed ? "" : "rotate-90"}`}
          />
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="whitespace-nowrap text-base font-semibold text-neutral-800">
              {formatSubAgentTypeLabel(sourceSessionType)}
            </span>
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-base text-neutral-600">
                {sourceSessionDesc ?? `Sub Agent ${shortSessionId(sourceSessionId)}`}
              </span>
              {sourceSessionFork ? (
                <span className="shrink-0 rounded-md border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                  fork
                </span>
              ) : null}
            </div>
          </div>
        </button>
        <SubAgentStatusSummary
          activityText={activityText}
          summaryParts={summaryParts}
          metaRows={metaRows}
          metaOpen={metaOpen}
          toolCount={toolItems.length}
          isFinished={isFinished}
          onMetaOpenChange={onMetaOpenChange}
        />
        <div className="px-3.5 pb-3.5 pt-0.5" style={{ zoom: 0.9 }}>
          <div
            ref={contentRef}
            className="relative flex flex-col-reverse overflow-hidden transition-[height] duration-200 ease-out"
          >
            <div
              ref={contentInnerRef}
              className="space-y-5"
              style={{ backfaceVisibility: "hidden" }}
            >
              {expandedBlocks.map(renderBlock)}
            </div>
            {collapsed && hasCollapsedOverflow ? (
              <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-10 bg-gradient-to-b from-[hsl(var(--surface))] to-transparent" />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
