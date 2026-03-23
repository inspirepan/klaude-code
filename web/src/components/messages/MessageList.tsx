import { ArrowDown, Loader } from "lucide-react";
import { useEffect, useRef, useState, useCallback, useMemo, useLayoutEffect } from "react";

import { useT } from "@/i18n";
import { useMountEffect } from "@/hooks/useMountEffect";
import { useMessageStore } from "../../stores/message-store";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import type { SessionStatusState } from "../../stores/event-reducer";
import type { MessageItem as MessageItemType } from "../../types/message";
import type { SessionSummary } from "../../types/session";
import { splitSessionTitle } from "@/components/session-title";
import { CollapseGroupBlock } from "./CollapseGroupBlock";
import { CollapseAllContext } from "./collapse-all-context";
import { DeveloperMessage } from "./DeveloperMessage";
import { MessageListHeader } from "./MessageListHeader";
import { MessageRow } from "./MessageRow";
import { PlannedGroupBlock } from "./PlannedGroupBlock";
import {
  buildSections,
  buildSectionBlocks,
  findMatchingItemIds,
  type SectionBlock,
} from "./message-sections";
import { SearchBar } from "./SearchBar";
import { SubAgentGroupCard } from "./SubAgentGroupCard";
import {
  isCopyableAssistantText,
  formatSubAgentTypeLabel,
  shortSessionId,
} from "./message-list-ui";
import { SearchProvider, type SearchState } from "./search-context";
import { SessionStatusBar } from "../input/SessionStatusBar";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

// Item types whose components include the rail grid internally (grid-cols-[16px_1fr] gap-x-1.5).
// All other item types need RAIL_CONTENT_OFFSET to align with the grid's right column.
const GRID_ITEM_TYPES = new Set(["thinking", "tool_block", "developer_message", "task_metadata"]);

// Tool blocks that render as cards (no rail grid) and need the content offset.
const CARD_TOOL_NAMES = new Set(["TodoWrite", "AskUserQuestion"]);

// Left offset matching the rail grid: 16px column + 6px gap = 22px.
const RAIL_CONTENT_OFFSET = "pl-[22px]";

function blockSpacingClass(block: SectionBlock, isFirst: boolean): string {
  if (isFirst) return "";
  if (block.type === "planned_group" || block.type === "collapse_group") return "mt-3";
  if (block.type === "item" && block.item.type === "tool_block") return "mt-3";
  return "mt-3";
}

const EMPTY_ITEMS: MessageItemType[] = [];
const EMPTY_SUB_AGENT_DESC_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_TYPE_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_FORK_MAP: Record<string, boolean> = {};
const EMPTY_SUB_AGENT_FINISHED_MAP: Record<string, boolean> = {};
const EMPTY_STATUS_MAP: Record<string, SessionStatusState> = {};
const BOTTOM_THRESHOLD_PX = 120;

const AGENT_URL_RE = /^\/session\/[a-f0-9]+\/agent\/([a-f0-9]+)$/;

function getSubAgentIdFromUrl(): string | null {
  const match = window.location.pathname.match(AGENT_URL_RE);
  return match ? match[1] : null;
}

function isNearBottom(container: HTMLDivElement): boolean {
  return (
    container.scrollHeight - container.scrollTop - container.clientHeight < BOTTOM_THRESHOLD_PX
  );
}

interface MessageListProps {
  sessionId: string;
}

function getSessionTitle(session: SessionSummary | null): string | null {
  const generatedTitle = session?.title?.trim();
  if (generatedTitle !== undefined && generatedTitle.length > 0) {
    return generatedTitle;
  }
  const firstMessage = session?.user_messages[0]?.trim();
  if (firstMessage !== undefined && firstMessage.length > 0) {
    return firstMessage;
  }
  return null;
}

export function MessageList({ sessionId }: MessageListProps): JSX.Element {
  const t = useT();
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
  const subAgentForkBySessionId = useMessageStore(
    (state) =>
      state.reducerStateBySessionId[sessionId]?.subAgentForkBySessionId ?? EMPTY_SUB_AGENT_FORK_MAP,
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
  const contentRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const previousLastVisibleItemIdRef = useRef<string | null>(null);
  const mainScrollTopRef = useRef<number | null>(null);
  const [viewingSubAgentSessionId, setViewingSubAgentSessionId] = useState<string | null>(
    getSubAgentIdFromUrl,
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActiveIndex, setSearchActiveIndex] = useState(-1);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [collapsedCollapseGroups, setCollapsedCollapseGroups] = useState<Record<string, boolean>>(
    {},
  );
  const [collapseGen, setCollapseGen] = useState(0);
  const [expandGen, setExpandGen] = useState(0);

  const copyTimerRef = useRef(0);

  // Reset sub-agent view when the parent session changes (e.g. switching sessions)
  const [prevSessionId, setPrevSessionId] = useState(sessionId);
  if (prevSessionId !== sessionId) {
    setPrevSessionId(sessionId);
    setViewingSubAgentSessionId(getSubAgentIdFromUrl());
  }

  const effectiveSessionId = viewingSubAgentSessionId ?? sessionId;

  const session = useMemo(
    () => groups.flatMap((group) => group.sessions).find((item) => item.id === sessionId) ?? null,
    [groups, sessionId],
  );
  const sessionTitle = useMemo(
    () => getSessionTitle(session) ?? t("sidebar.newSession"),
    [session, t],
  );
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
        if (viewingSubAgentSessionId) {
          // Sub-agent view: show only items from the viewed sub-agent session
          return sourceSessionId === viewingSubAgentSessionId;
        }
        // Main view: existing filter
        if (
          sourceSessionId !== sessionId &&
          (item.type === "developer_message" || item.type === "thinking")
        ) {
          return false;
        }
        return true;
      }),
    [items, sessionId, viewingSubAgentSessionId],
  );
  const hasStreamingAssistantText = useMemo(
    () =>
      visibleItems.some(
        (item) =>
          item.type === "assistant_text" &&
          (item.sessionId ?? sessionId) === effectiveSessionId &&
          item.isStreaming,
      ),
    [effectiveSessionId, sessionId, visibleItems],
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
  useMountEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  });

  // Scroll to active search match
  useEffect(() => {
    if (!activeItemId) return;
    const el = itemRefsMap.current.get(activeItemId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeItemId]);

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

  useMountEffect(() => () => window.clearTimeout(copyTimerRef.current));

  const mainSessionStatus = statusBySessionId[sessionId] ?? null;
  const effectiveStatus = statusBySessionId[effectiveSessionId] ?? null;
  const isMainSessionRunning =
    runtime?.sessionState === "running" ||
    (((mainSessionStatus?.taskActive ?? false) ||
      (mainSessionStatus?.thinkingActive ?? false) ||
      (mainSessionStatus?.compacting ?? false) ||
      (mainSessionStatus?.isComposing ?? false)) &&
      mainSessionStatus?.awaitingInput !== true);

  const isEffectiveRunning = viewingSubAgentSessionId
    ? ((effectiveStatus?.taskActive ?? false) ||
        (effectiveStatus?.thinkingActive ?? false) ||
        (effectiveStatus?.compacting ?? false) ||
        (effectiveStatus?.isComposing ?? false)) &&
      effectiveStatus?.awaitingInput !== true
    : isMainSessionRunning;

  const [prevRunning, setPrevRunning] = useState(isEffectiveRunning);
  if (prevRunning !== isEffectiveRunning) {
    setPrevRunning(isEffectiveRunning);
    if (prevRunning && !isEffectiveRunning) {
      setCollapsedCollapseGroups({});
    }
  }

  // Reset collapse state when switching between main and sub-agent views
  const [prevEffectiveSessionId, setPrevEffectiveSessionId] = useState(effectiveSessionId);
  if (prevEffectiveSessionId !== effectiveSessionId) {
    setPrevEffectiveSessionId(effectiveSessionId);
    setCollapsedCollapseGroups({});
  }

  const hasActiveStatus = useMemo(
    () =>
      Object.values(statusBySessionId).some(
        (status) => status.taskActive || status.awaitingInput || status.compacting,
      ) ||
      runtime?.sessionState === "running" ||
      runtime?.sessionState === "waiting_user_input",
    [runtime?.sessionState, statusBySessionId],
  );

  const [nowMs, setNowMs] = useState(() => Date.now());
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

  const nowSeconds = nowMs / 1000;

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

  const updateScrollButtonVisibility = useCallback(() => {
    const container = scrollRef.current;
    if (!container) {
      setShowScrollToBottom(false);
      return;
    }
    setShowScrollToBottom(!isNearBottom(container));
  }, []);

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      const container = scrollRef.current;
      if (!container) return;
      container.scrollTo({ top: container.scrollHeight, behavior });
      setShowScrollToBottom(false);
      sessionStorage.setItem(
        `scroll-${sessionId}`,
        String(Math.max(0, container.scrollHeight - container.clientHeight)),
      );
    },
    [sessionId],
  );

  // Restore scroll position when items first load for a session
  const hasItems = visibleItems.length > 0;
  useLayoutEffect(() => {
    if (!hasItems) {
      setShowScrollToBottom(false);
      return;
    }
    const saved = sessionStorage.getItem(`scroll-${sessionId}`);
    const container = scrollRef.current;
    if (!container) return;
    if (saved !== null) {
      container.scrollTop = parseInt(saved, 10);
    } else {
      container.scrollTop = container.scrollHeight;
    }
    updateScrollButtonVisibility();
  }, [hasItems, sessionId, updateScrollButtonVisibility]);

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

    scrollToBottom("auto");
  }, [scrollToBottom, sessionId, visibleItems]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      updateScrollButtonVisibility();
    });
    observer.observe(content);
    return () => {
      observer.disconnect();
    };
  }, [sessionId, updateScrollButtonVisibility]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    setShowScrollToBottom(!isNearBottom(container));
    sessionStorage.setItem(`scroll-${sessionId}`, String(container.scrollTop));
  }, [sessionId]);

  const setItemRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) {
      itemRefsMap.current.set(id, el);
    } else {
      itemRefsMap.current.delete(id);
    }
  }, []);

  // Sub-agent navigation
  const handleEnterSubAgent = useCallback(
    (subAgentId: string) => {
      mainScrollTopRef.current = scrollRef.current?.scrollTop ?? null;
      setViewingSubAgentSessionId(subAgentId);
      history.pushState(null, "", `/session/${sessionId}/agent/${subAgentId}`);
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo({ top: 0 });
      });
    },
    [sessionId],
  );

  const handleExitSubAgent = useCallback(() => {
    setViewingSubAgentSessionId(null);
    history.pushState(null, "", `/session/${sessionId}`);
    const savedTop = mainScrollTopRef.current;
    requestAnimationFrame(() => {
      if (savedTop !== null && scrollRef.current) {
        scrollRef.current.scrollTop = savedTop;
      }
    });
  }, [sessionId]);

  // Sync sub-agent view with browser back/forward
  useEffect(() => {
    const handlePopState = () => {
      setViewingSubAgentSessionId(getSubAgentIdFromUrl());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const sections = useMemo(
    () => buildSections(visibleItems, sessionId, effectiveSessionId),
    [visibleItems, sessionId, effectiveSessionId],
  );

  const sectionBlocks = useMemo(
    () =>
      buildSectionBlocks(
        sections,
        sessionId,
        effectiveSessionId,
        subAgentDescBySessionId,
        subAgentTypeBySessionId,
        subAgentForkBySessionId,
      ),
    [
      sections,
      sessionId,
      effectiveSessionId,
      subAgentDescBySessionId,
      subAgentForkBySessionId,
      subAgentTypeBySessionId,
    ],
  );

  const collapseGroupIdByItemId = useMemo(() => {
    const map = new Map<string, string>();
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type === "collapse_group") {
          for (const item of block.items) map.set(item.id, block.id);
        } else if (block.type === "planned_group") {
          for (const inner of block.blocks) {
            if (inner.type === "item") map.set(inner.item.id, block.id);
          }
        }
      }
    }
    return map;
  }, [sectionBlocks]);

  const lastSectionCollapseGroupIds = useMemo(() => {
    const lastSection = sectionBlocks[sectionBlocks.length - 1];
    if (!lastSection) return new Set<string>();
    const ids = new Set<string>();
    for (const block of lastSection) {
      if (block.type === "collapse_group" || block.type === "planned_group") ids.add(block.id);
    }
    return ids;
  }, [sectionBlocks]);

  const allCollapseGroupIds = useMemo(() => {
    const ids: string[] = [];
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type === "collapse_group" || block.type === "planned_group") ids.push(block.id);
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
      // While running, expand all groups in the current turn (last section)
      if (isEffectiveRunning) {
        return !lastSectionCollapseGroupIds.has(groupId);
      }
      return true;
    },
    [
      activeItemId,
      collapseGroupIdByItemId,
      collapsedCollapseGroups,
      isEffectiveRunning,
      lastSectionCollapseGroupIds,
    ],
  );

  const collapseAllValue = useMemo(() => ({ collapseGen, expandGen }), [collapseGen, expandGen]);

  // Sub-agent view header label
  const subAgentLabel = useMemo(() => {
    if (!viewingSubAgentSessionId) return null;
    const typeLabel = formatSubAgentTypeLabel(
      subAgentTypeBySessionId[viewingSubAgentSessionId] ?? null,
    );
    const desc =
      subAgentDescBySessionId[viewingSubAgentSessionId] ?? shortSessionId(viewingSubAgentSessionId);
    return `${typeLabel} — ${desc}`;
  }, [viewingSubAgentSessionId, subAgentTypeBySessionId, subAgentDescBySessionId]);

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
            onBack={viewingSubAgentSessionId ? handleExitSubAgent : undefined}
            subAgentLabel={subAgentLabel}
          />
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            data-message-scroll-container="true"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-y-none"
          >
            <div ref={contentRef}>
              <div className="mx-auto max-w-4xl space-y-5 px-4 pb-2 pt-8 sm:px-6">
                {hasItems ? (
                  <>
                    {sections.map((section, sectionIndex) => (
                      <div key={section[0].id}>
                        {sectionBlocks[sectionIndex]?.map((block, blockIdx) => {
                          const spacing = blockSpacingClass(block, blockIdx === 0);

                          if (block.type === "dev_group") {
                            return (
                              <div key={block.id} className={spacing}>
                                <DeveloperMessage items={block.items} />
                              </div>
                            );
                          }

                          if (block.type === "collapse_group") {
                            const collapsed = isCollapseGroupCollapsed(block.id);
                            return (
                              <div key={block.id} className={spacing}>
                                <CollapseGroupBlock
                                  items={block.items}
                                  collapsed={collapsed}
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
                              </div>
                            );
                          }

                          if (block.type === "planned_group") {
                            const pgCollapsed = isCollapseGroupCollapsed(block.id);
                            return (
                              <div key={block.id} className={spacing}>
                                <PlannedGroupBlock
                                  todos={block.todos}
                                  collapsed={pgCollapsed}
                                  onToggle={() => {
                                    setCollapsedCollapseGroups((prev) => ({
                                      ...prev,
                                      [block.id]: !pgCollapsed,
                                    }));
                                  }}
                                >
                                  {block.blocks.map((inner) => {
                                    if (inner.type === "dev_group") {
                                      return (
                                        <DeveloperMessage key={inner.id} items={inner.items} />
                                      );
                                    }
                                    if (inner.type === "sub_agent_group") {
                                      const isFinished =
                                        subAgentFinishedBySessionId[inner.sourceSessionId] ===
                                        true;
                                      return (
                                        <SubAgentGroupCard
                                          key={inner.groupId}
                                          sourceSessionId={inner.sourceSessionId}
                                          sourceSessionType={inner.sourceSessionType}
                                          sourceSessionDesc={inner.sourceSessionDesc}
                                          sourceSessionFork={inner.sourceSessionFork}
                                          toolCount={inner.toolCount}
                                          status={
                                            statusBySessionId[inner.sourceSessionId] ?? null
                                          }
                                          isFinished={isFinished}
                                          nowSeconds={nowSeconds}
                                          onClick={() =>
                                            handleEnterSubAgent(inner.sourceSessionId)
                                          }
                                        />
                                      );
                                    }
                                    return (
                                      <MessageRow
                                        key={inner.item.id}
                                        item={inner.item}
                                        workDir={workspacePath}
                                        isActive={inner.item.id === activeItemId}
                                        copied={copiedItemId === inner.item.id}
                                        onCopy={handleCopy}
                                        itemRef={(el) => setItemRef(inner.item.id, el)}
                                      />
                                    );
                                  })}
                                </PlannedGroupBlock>
                              </div>
                            );
                          }

                          if (block.type === "sub_agent_group") {
                            const isFinished =
                              subAgentFinishedBySessionId[block.sourceSessionId] === true;
                            return (
                              <div key={block.groupId} className={`${spacing} ${RAIL_CONTENT_OFFSET}`}>
                                <SubAgentGroupCard
                                  sourceSessionId={block.sourceSessionId}
                                  sourceSessionType={block.sourceSessionType}
                                  sourceSessionDesc={block.sourceSessionDesc}
                                  sourceSessionFork={block.sourceSessionFork}
                                  toolCount={block.toolCount}
                                  status={statusBySessionId[block.sourceSessionId] ?? null}
                                  isFinished={isFinished}
                                  nowSeconds={nowSeconds}
                                  onClick={() => handleEnterSubAgent(block.sourceSessionId)}
                                />
                              </div>
                            );
                          }

                          const item = block.item;
                          const hasRailGrid =
                            GRID_ITEM_TYPES.has(item.type) &&
                            !(item.type === "tool_block" && CARD_TOOL_NAMES.has(item.toolName));
                          const itemOffset =
                            item.type !== "user_message" && !hasRailGrid
                              ? RAIL_CONTENT_OFFSET
                              : "";
                          return (
                            <div key={item.id} className={`${spacing} ${itemOffset}`}>
                              <MessageRow
                                item={item}
                                workDir={workspacePath}
                                isActive={item.id === activeItemId}
                                copied={copiedItemId === item.id}
                                onCopy={handleCopy}
                                itemRef={(el) => {
                                  setItemRef(item.id, el);
                                }}
                              />
                            </div>
                          );
                        })}
                      </div>
                    ))}
                    <div
                      aria-hidden="true"
                      className={`transition-[height] duration-300 ease-out ${hasStreamingAssistantText ? "h-12" : "h-0"}`}
                    />
                  </>
                ) : runtime?.wsState === "connecting" ? (
                  <div className="flex min-h-[240px] items-center justify-center">
                    <Loader className="h-5 w-5 animate-spin text-neutral-500" />
                  </div>
                ) : null}
              </div>
              <div className="mx-auto max-w-4xl px-4 pb-4 sm:px-6">
                <SessionStatusBar
                  status={viewingSubAgentSessionId ? effectiveStatus : mainSessionStatus}
                  runtime={viewingSubAgentSessionId ? null : runtime}
                />
              </div>
            </div>
          </div>
          {showScrollToBottom ? (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-20 -translate-x-1/2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => scrollToBottom()}
                    className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card/95 text-neutral-700 shadow-sm ring-1 ring-black/[0.06] backdrop-blur transition-colors hover:bg-card hover:text-neutral-900"
                    aria-label={t("messageList.scrollToBottom")}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>{t("messageList.scrollToBottom")}</TooltipContent>
              </Tooltip>
            </div>
          ) : null}
        </div>
      </SearchProvider>
    </CollapseAllContext.Provider>
  );
}
