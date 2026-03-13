import { Loader } from "lucide-react";
import { useEffect, useRef, useState, useCallback, useMemo, useLayoutEffect } from "react";

import { useMessageStore } from "../../stores/message-store";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import type { SessionStatusState } from "../../stores/event-reducer";
import type { MessageItem as MessageItemType } from "../../types/message";
import type { SessionSummary } from "../../types/session";
import { splitSessionTitle } from "@/components/session-title";
import { CollapseGroupBlock } from "./CollapseGroupBlock";
import { CollapseAllContext } from "./collapse-all-context";
import { MessageListHeader } from "./MessageListHeader";
import { MessageRow } from "./MessageRow";
import { isQuestionSummaryUIExtra, isTodoListUIExtra } from "./message-ui-extra";
import { SearchBar } from "./SearchBar";
import { SubAgentGroupCard } from "./SubAgentGroupCard";
import { isCopyableAssistantText } from "./message-list-ui";
import { SearchProvider, type SearchState } from "./search-context";

const EMPTY_ITEMS: MessageItemType[] = [];
const EMPTY_SUB_AGENT_DESC_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_TYPE_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_FINISHED_MAP: Record<string, boolean> = {};
const EMPTY_STATUS_MAP: Record<string, SessionStatusState> = {};

interface MessageListProps {
  sessionId: string;
}

function getSessionTitle(session: SessionSummary | null): string {
  const generatedTitle = session?.title?.trim();
  if (generatedTitle !== undefined && generatedTitle.length > 0) {
    return generatedTitle;
  }
  const firstMessage = session?.user_messages[0]?.trim();
  if (firstMessage !== undefined && firstMessage.length > 0) {
    return firstMessage;
  }
  return "New session";
}

interface SectionItemBlock {
  type: "item";
  item: MessageItemType;
}

interface SectionSubAgentBlock {
  type: "sub_agent_group";
  groupId: string;
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  items: MessageItemType[];
}

interface SectionCollapseGroupBlock {
  type: "collapse_group";
  id: string;
  items: MessageItemType[];
}

type SectionBlock = SectionItemBlock | SectionSubAgentBlock | SectionCollapseGroupBlock;

function isCollapsibleItem(item: MessageItemType): boolean {
  if (item.type === "tool_block") {
    return !isTodoListUIExtra(item.uiExtra) && !isQuestionSummaryUIExtra(item.uiExtra);
  }
  return item.type === "thinking" || item.type === "developer_message";
}

function extractSearchableText(item: MessageItemType): string {
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
    case "task_worked":
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

function findMatchingItemIds(items: MessageItemType[], query: string): string[] {
  if (!query.trim()) return [];
  const lower = query.toLowerCase();
  return items
    .filter((item) => extractSearchableText(item).toLowerCase().includes(lower))
    .map((item) => item.id);
}

export function MessageList({ sessionId }: MessageListProps): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const runtime = useSessionStore((state) => state.runtimeBySessionId[sessionId] ?? null);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const items = useMessageStore((state) => state.messagesBySessionId[sessionId] ?? EMPTY_ITEMS);
  const subAgentDescBySessionId = useMessageStore(
    (state) =>
      state.reducerStateBySessionId[sessionId]?.subAgentDescBySessionId ?? EMPTY_SUB_AGENT_DESC_MAP,
  );
  const subAgentTypeBySessionId = useMessageStore(
    (state) =>
      state.reducerStateBySessionId[sessionId]?.subAgentTypeBySessionId ?? EMPTY_SUB_AGENT_TYPE_MAP,
  );
  const subAgentFinishedBySessionId = useMessageStore(
    (state) =>
      state.reducerStateBySessionId[sessionId]?.subAgentFinishedBySessionId ??
      EMPTY_SUB_AGENT_FINISHED_MAP,
  );
  const statusBySessionId = useMessageStore(
    (state) => state.reducerStateBySessionId[sessionId]?.statusBySessionId ?? EMPTY_STATUS_MAP,
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const shouldStickToBottomRef = useRef(true);
  const previousLastVisibleItemIdRef = useRef<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActiveIndex, setSearchActiveIndex] = useState(-1);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);
  const [collapsedSubAgentGroups, setCollapsedSubAgentGroups] = useState<Record<string, boolean>>(
    {},
  );
  const [subAgentMetaOpen, setSubAgentMetaOpen] = useState<Record<string, boolean>>({});
  const [collapsedCollapseGroups, setCollapsedCollapseGroups] = useState<Record<string, boolean>>(
    {},
  );
  const [collapseGen, setCollapseGen] = useState(0);
  const [expandGen, setExpandGen] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const copyTimerRef = useRef(0);

  const session = useMemo(
    () => groups.flatMap((group) => group.sessions).find((item) => item.id === sessionId) ?? null,
    [groups, sessionId],
  );
  const sessionTitle = useMemo(() => getSessionTitle(session), [session]);
  const { primary: primaryTitle, secondary: secondaryTitle } = useMemo(
    () => splitSessionTitle(sessionTitle),
    [sessionTitle],
  );
  const workspacePath = session?.work_dir ?? "";
  const sessionReadOnly = session?.read_only === true;

  const visibleItems = useMemo(
    () =>
      items.filter((item) => {
        if (item.type === "tool_block" && item.toolName === "Agent") return false;
        const sourceSessionId = item.sessionId ?? sessionId;
        if (
          sourceSessionId !== sessionId &&
          (item.type === "developer_message" || item.type === "thinking")
        ) {
          return false;
        }
        return true;
      }),
    [items, sessionId],
  );
  const hasStreamingAssistantText = useMemo(
    () =>
      visibleItems.some(
        (item) =>
          item.type === "assistant_text" &&
          (item.sessionId ?? sessionId) === sessionId &&
          item.isStreaming,
      ),
    [sessionId, visibleItems],
  );

  const searchMatchItemIds = useMemo(
    () => findMatchingItemIds(visibleItems, searchQuery),
    [visibleItems, searchQuery],
  );

  const activeItemId = useMemo(() => {
    if (searchMatchItemIds.length === 0) return null;
    return searchMatchItemIds[searchActiveIndex] ?? searchMatchItemIds[0] ?? null;
  }, [searchActiveIndex, searchMatchItemIds]);

  const resolvedSearchActiveIndex =
    activeItemId === null ? -1 : searchMatchItemIds.indexOf(activeItemId);
  const searchState = useMemo<SearchState>(
    () => ({
      query: searchQuery,
      matchItemIds: searchMatchItemIds,
      activeIndex: resolvedSearchActiveIndex,
    }),
    [searchQuery, searchMatchItemIds, resolvedSearchActiveIndex],
  );

  // Cmd+F intercept
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Scroll to active search match
  useEffect(() => {
    if (!activeItemId) return;
    const el = itemRefsMap.current.get(activeItemId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeItemId, collapsedSubAgentGroups]);

  const handleSearchQueryChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleSearchNext = useCallback(() => {
    if (searchMatchItemIds.length === 0) return;
    const currentIndex = activeItemId === null ? -1 : searchMatchItemIds.indexOf(activeItemId);
    setSearchActiveIndex((currentIndex + 1) % searchMatchItemIds.length);
  }, [activeItemId, searchMatchItemIds]);

  const handleSearchPrev = useCallback(() => {
    if (searchMatchItemIds.length === 0) return;
    const currentIndex = activeItemId === null ? 0 : searchMatchItemIds.indexOf(activeItemId);
    setSearchActiveIndex(
      (currentIndex - 1 + searchMatchItemIds.length) % searchMatchItemIds.length,
    );
  }, [activeItemId, searchMatchItemIds]);

  const handleSearchClose = useCallback(() => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchActiveIndex(-1);
  }, []);

  useEffect(() => () => window.clearTimeout(copyTimerRef.current), []);

  const hasActiveStatus = useMemo(
    () =>
      Object.values(statusBySessionId).some(
        (status) => status.taskActive || status.awaitingInput || status.compacting,
      ) ||
      runtime?.sessionState === "running" ||
      runtime?.sessionState === "waiting_user_input",
    [runtime?.sessionState, statusBySessionId],
  );
  const mainSessionStatus = statusBySessionId[sessionId] ?? null;
  const isMainSessionRunning =
    runtime?.sessionState === "running" ||
    (((mainSessionStatus?.taskActive ?? false) ||
      (mainSessionStatus?.thinkingActive ?? false) ||
      (mainSessionStatus?.compacting ?? false) ||
      (mainSessionStatus?.isComposing ?? false)) &&
      mainSessionStatus?.awaitingInput !== true);

  useEffect(() => {
    if (!hasActiveStatus) return;
    setNowMs(Date.now());
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [hasActiveStatus]);

  const handleCopy = useCallback(async (item: MessageItemType) => {
    if (!isCopyableAssistantText(item)) return;
    try {
      await navigator.clipboard.writeText(item.content);
      setCopiedItemId(item.id);
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopiedItemId(null), 2000);
    } catch {
      // ignore
    }
  }, []);

  // Restore scroll position when items first load for a session
  const hasItems = visibleItems.length > 0;
  useLayoutEffect(() => {
    if (!hasItems) return;
    const saved = sessionStorage.getItem(`scroll-${sessionId}`);
    const container = scrollRef.current;
    if (!container) return;
    if (saved !== null) {
      container.scrollTop = parseInt(saved, 10);
    } else {
      container.scrollTop = container.scrollHeight;
    }
    shouldStickToBottomRef.current =
      container.scrollHeight - container.scrollTop - container.clientHeight < 150;
  }, [sessionId, hasItems]);

  useLayoutEffect(() => {
    const lastItem = visibleItems[visibleItems.length - 1];
    const previousLastItemId = previousLastVisibleItemIdRef.current;
    previousLastVisibleItemIdRef.current = lastItem?.id ?? null;
    if (!lastItem || previousLastItemId === null || previousLastItemId === lastItem.id) {
      return;
    }

    const sourceSessionId = lastItem.sessionId ?? sessionId;
    if (sourceSessionId !== sessionId || lastItem.type !== "user_message") {
      return;
    }

    shouldStickToBottomRef.current = true;
    const container = scrollRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [sessionId, visibleItems]);

  // Auto-scroll on streamed updates only when user is already near bottom.
  useLayoutEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    if (shouldStickToBottomRef.current) {
      container.scrollTop = container.scrollHeight;
    }
  }, [visibleItems]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    shouldStickToBottomRef.current =
      container.scrollHeight - container.scrollTop - container.clientHeight < 150;
    sessionStorage.setItem(`scroll-${sessionId}`, String(container.scrollTop));
  }, [sessionId]);

  const setItemRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) {
      itemRefsMap.current.set(id, el);
    } else {
      itemRefsMap.current.delete(id);
    }
  }, []);

  // Group items into sections starting at each main-session user message so that
  // CSS sticky is scoped to each section's containing block.
  const sections = useMemo(() => {
    const result: MessageItemType[][] = [];
    let current: MessageItemType[] = [];
    for (const item of visibleItems) {
      const sourceSessionId = item.sessionId ?? sessionId;
      const isMainSessionUserMessage =
        item.type === "user_message" && sourceSessionId === sessionId;
      if (isMainSessionUserMessage && current.length > 0) {
        result.push(current);
        current = [];
      }
      current.push(item);
    }
    if (current.length > 0) result.push(current);
    return result;
  }, [visibleItems, sessionId]);

  const sectionBlocks = useMemo(() => {
    return sections.map((section) => {
      // First pass: group sub-agent items
      const rawBlocks: SectionBlock[] = [];
      const subAgentBlockIndexBySessionId = new Map<string, number>();
      let i = 0;
      while (i < section.length) {
        const item = section[i];
        const sourceSessionId = item.sessionId ?? sessionId;
        if (sourceSessionId === sessionId) {
          rawBlocks.push({ type: "item", item });
          i += 1;
          continue;
        }

        const existingBlockIndex = subAgentBlockIndexBySessionId.get(sourceSessionId);
        if (existingBlockIndex !== undefined) {
          const existingBlock = rawBlocks[existingBlockIndex];
          if (existingBlock?.type === "sub_agent_group") {
            existingBlock.items.push(item);
          }
          i += 1;
          continue;
        }

        const groupItems: MessageItemType[] = [item];
        const blockIndex = rawBlocks.length;
        rawBlocks.push({
          type: "sub_agent_group",
          groupId: `${sessionId}-${section[0]?.id ?? sourceSessionId}-${sourceSessionId}`,
          sourceSessionId,
          sourceSessionType: subAgentTypeBySessionId[sourceSessionId] ?? null,
          sourceSessionDesc: subAgentDescBySessionId[sourceSessionId] ?? null,
          items: groupItems,
        });
        subAgentBlockIndexBySessionId.set(sourceSessionId, blockIndex);
        i += 1;
      }

      // Second pass: merge consecutive thinking/tool_block items into collapse groups
      const blocks: SectionBlock[] = [];
      let pending: MessageItemType[] = [];
      for (const block of rawBlocks) {
        if (block.type === "item" && isCollapsibleItem(block.item)) {
          pending.push(block.item);
        } else {
          if (pending.length > 0) {
            blocks.push({
              type: "collapse_group",
              id: `cg-${sessionId}-${pending[0].id}`,
              items: pending,
            });
            pending = [];
          }
          blocks.push(block);
        }
      }
      if (pending.length > 0) {
        blocks.push({
          type: "collapse_group",
          id: `cg-${sessionId}-${pending[0].id}`,
          items: pending,
        });
      }
      return blocks;
    });
  }, [sections, sessionId, subAgentDescBySessionId, subAgentTypeBySessionId]);

  const subAgentGroupIdByItemId = useMemo(() => {
    const map = new Map<string, string>();
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type !== "sub_agent_group") continue;
        for (const item of block.items) {
          map.set(item.id, block.groupId);
        }
      }
    }
    return map;
  }, [sectionBlocks]);

  const collapseGroupIdByItemId = useMemo(() => {
    const map = new Map<string, string>();
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type !== "collapse_group") continue;
        for (const item of block.items) {
          map.set(item.id, block.id);
        }
      }
    }
    return map;
  }, [sectionBlocks]);

  const lastCollapseGroupId = useMemo(() => {
    let lastId: string | null = null;
    let hasMessageAfterLastGroup = false;
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type === "collapse_group") {
          lastId = block.id;
          hasMessageAfterLastGroup = false;
        } else if (
          block.type === "item" &&
          (block.item.type === "user_message" ||
            (block.item.type === "assistant_text" && block.item.content.trim().length > 0)) &&
          lastId !== null
        ) {
          hasMessageAfterLastGroup = true;
        }
      }
    }
    return hasMessageAfterLastGroup ? null : lastId;
  }, [sectionBlocks]);

  const activeGroupId =
    activeItemId === null ? null : (subAgentGroupIdByItemId.get(activeItemId) ?? null);

  const allCollapseGroupIds = useMemo(() => {
    const ids: string[] = [];
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type === "collapse_group") ids.push(block.id);
      }
    }
    return ids;
  }, [sectionBlocks]);

  const handleCollapseAll = useCallback(() => {
    const state: Record<string, boolean> = {};
    for (const id of allCollapseGroupIds) state[id] = true;
    setCollapsedCollapseGroups(state);
    setCollapseGen((v) => v + 1);
  }, [allCollapseGroupIds]);

  const handleExpandAll = useCallback(() => {
    const state: Record<string, boolean> = {};
    for (const id of allCollapseGroupIds) state[id] = false;
    setCollapsedCollapseGroups(state);
    setExpandGen((v) => v + 1);
  }, [allCollapseGroupIds]);

  // Cmd+Shift+, collapse all, Cmd+Shift+. expand all
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return;
      if (e.code === "Comma") {
        e.preventDefault();
        handleCollapseAll();
      } else if (e.code === "Period") {
        e.preventDefault();
        handleExpandAll();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [handleCollapseAll, handleExpandAll]);

  const isCollapseGroupCollapsed = useCallback(
    (groupId: string): boolean => {
      // Force expand if the group contains the active search match
      if (activeItemId !== null && collapseGroupIdByItemId.get(activeItemId) === groupId) {
        return false;
      }
      if (groupId in collapsedCollapseGroups) {
        return collapsedCollapseGroups[groupId];
      }
      // Default: last group expanded, others collapsed
      return groupId !== lastCollapseGroupId;
    },
    [activeItemId, collapseGroupIdByItemId, collapsedCollapseGroups, lastCollapseGroupId],
  );
  const nowSeconds = nowMs / 1000;

  const collapseAllValue = useMemo(() => ({ collapseGen, expandGen }), [collapseGen, expandGen]);

  return (
    <CollapseAllContext.Provider value={collapseAllValue}>
      <SearchProvider value={searchState}>
        <div className="relative flex min-h-0 flex-1 flex-col">
          {searchOpen ? (
            <SearchBar
              totalMatches={searchMatchItemIds.length}
              activeIndex={resolvedSearchActiveIndex}
              onQueryChange={handleSearchQueryChange}
              onNext={handleSearchNext}
              onPrev={handleSearchPrev}
              onClose={handleSearchClose}
            />
          ) : null}

          <div
            ref={scrollRef}
            onScroll={handleScroll}
            data-message-scroll-container="true"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-y-contain"
          >
            <MessageListHeader
              primaryTitle={primaryTitle}
              secondaryTitle={secondaryTitle}
              workspacePath={workspacePath}
              sessionReadOnly={sessionReadOnly}
              sidebarOpen={sidebarOpen}
              setSidebarOpen={setSidebarOpen}
              onSearchOpen={() => setSearchOpen(true)}
              onCollapseAll={handleCollapseAll}
              onExpandAll={handleExpandAll}
            />
            <div className="mx-auto max-w-4xl space-y-5 px-4 pb-14 pt-8 sm:px-6">
              {hasItems ? (
                <>
                  {sections.map((section, sectionIndex) => (
                    <div key={section[0].id} className="space-y-5">
                      {sectionBlocks[sectionIndex]?.map((block) => {
                        if (block.type === "collapse_group") {
                          const collapsed = isCollapseGroupCollapsed(block.id);
                          return (
                            <CollapseGroupBlock
                              key={block.id}
                              items={block.items}
                              collapsed={collapsed}
                              showRunningSpinner={
                                block.id === lastCollapseGroupId && isMainSessionRunning
                              }
                              onToggle={() => {
                                setCollapsedCollapseGroups((prev) => ({
                                  ...prev,
                                  [block.id]: !collapsed,
                                }));
                              }}
                              activeItemId={activeItemId}
                              copiedItemId={copiedItemId}
                              workDir={workspacePath}
                              onCopy={handleCopy}
                              setItemRef={setItemRef}
                            />
                          );
                        }

                        if (block.type === "sub_agent_group") {
                          const collapsed =
                            activeGroupId === block.groupId
                              ? false
                              : (collapsedSubAgentGroups[block.groupId] ?? true);
                          const isFinished =
                            subAgentFinishedBySessionId[block.sourceSessionId] === true;
                          return (
                            <SubAgentGroupCard
                              key={block.groupId}
                              sourceSessionId={block.sourceSessionId}
                              sourceSessionType={block.sourceSessionType}
                              sourceSessionDesc={block.sourceSessionDesc}
                              items={block.items}
                              collapsed={collapsed}
                              status={statusBySessionId[block.sourceSessionId] ?? null}
                              isFinished={isFinished}
                              nowSeconds={nowSeconds}
                              activeItemId={activeItemId}
                              copiedItemId={copiedItemId}
                              metaOpen={subAgentMetaOpen[block.groupId] === true}
                              workDir={workspacePath}
                              onToggleCollapsed={() => {
                                setCollapsedSubAgentGroups((prev) => ({
                                  ...prev,
                                  [block.groupId]: !collapsed,
                                }));
                              }}
                              onMetaOpenChange={(open) => {
                                setSubAgentMetaOpen((prev) => ({
                                  ...prev,
                                  [block.groupId]: open,
                                }));
                              }}
                              onCopy={handleCopy}
                              setItemRef={setItemRef}
                            />
                          );
                        }

                        const item = block.item;
                        return (
                          <MessageRow
                            key={item.id}
                            item={item}
                            variant="main"
                            workDir={workspacePath}
                            isActive={item.id === activeItemId}
                            copied={copiedItemId === item.id}
                            onCopy={handleCopy}
                            itemRef={(el) => {
                              setItemRef(item.id, el);
                            }}
                          />
                        );
                      })}
                    </div>
                  ))}
                  <div aria-hidden="true" className={hasStreamingAssistantText ? "h-12" : "h-0"} />
                </>
              ) : runtime?.wsState === "connecting" ? (
                <div className="flex min-h-[240px] items-center justify-center">
                  <Loader className="h-5 w-5 animate-spin text-neutral-500" />
                </div>
              ) : (
                <div className="flex min-h-[240px] items-center justify-center">
                  <div className="rounded-3xl border border-dashed border-neutral-200 bg-neutral-50/70 px-6 py-10 text-center">
                    <div className="text-base font-semibold text-neutral-700">No messages yet</div>
                    <div className="mt-1 text-sm text-neutral-500">
                      Send a message below to start this session.
                    </div>
                  </div>
                </div>
              )}
            </div>
            {/* Add padding space equal to MessageComposer height + mask height so content isn't hidden under the absolute positioned bar */}
            <div className="h-44 shrink-0 sm:h-40" />
          </div>
        </div>
      </SearchProvider>
    </CollapseAllContext.Provider>
  );
}
