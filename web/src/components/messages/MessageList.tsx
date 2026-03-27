import { ArrowDown } from "lucide-react";
import {
  memo,
  type ReactNode,
  type CSSProperties,
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
  useLayoutEffect,
} from "react";

import { useT } from "@/i18n";
import { useMountEffect } from "@/hooks/useMountEffect";
import { useMessageStore } from "@/stores/message-store";
import { useAppStore } from "@/stores/app-store";
import { useSessionStore } from "@/stores/session-store";
import type { ReducerState } from "@/stores/event-reducer";
import type { MessageItem as MessageItemType } from "@/types/message";
import type { SessionRuntimeState, SessionSummary } from "@/types/session";
import { splitSessionTitle } from "@/components/session-title";
import { findSession } from "@/stores/session-helpers";
import { CollapseGroupBlock } from "./CollapseGroupBlock";
import { CollapseAllContext } from "./collapse-all-context";
import { DeveloperMessage } from "./DeveloperMessage";
import { MessageListHeader } from "./MessageListHeader";
import { MessageRow } from "./MessageRow";
import { PlannedGroupBlock } from "./PlannedGroupBlock";
import {
  buildSections,
  buildSectionBlocksForSection,
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
import { SessionStatusBar } from "@/components/input/SessionStatusBar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Item types whose components include the rail grid internally (grid-cols-[16px_1fr] gap-x-1.5).
// All other item types need RAIL_CONTENT_OFFSET to align with the grid's right column.
const GRID_ITEM_TYPES = new Set([
  "thinking",
  "tool_block",
  "developer_message",
  "task_metadata",
  "interrupt",
  "error",
  "assistant_text",
]);

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

const OFFSCREEN_BLOCK_STYLE: CSSProperties = {
  contentVisibility: "auto",
  containIntrinsicSize: "auto 160px",
};
const EMPTY_GROUP_IDS = new Set<string>();
const EMPTY_MATCH_ITEM_IDS: string[] = [];

/**
 * Block wrapper that plays a mount animation (opacity + translateY) via the
 * Web Animations API. The animation only fires when the scroll container
 * already has the `message-list-ready` class, which is added after a
 * double-rAF so history items rendered on the first frame are excluded.
 */
function AnimatedDiv({
  className,
  style,
  children,
}: {
  className: string;
  style?: CSSProperties;
  children: ReactNode;
}): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const container = el.closest("[data-message-scroll-container]");
    if (!container?.classList.contains("message-list-ready")) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.animate(
      [
        { opacity: 0, transform: "translateY(4px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      { duration: 200, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
    );
  }, []);
  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  );
}

function canReuseSectionItems(
  prevSection: MessageItemType[] | undefined,
  nextSection: MessageItemType[],
): boolean {
  if (!prevSection || prevSection.length !== nextSection.length) return false;
  for (let i = 0; i < nextSection.length; i++) {
    if (prevSection[i] !== nextSection[i]) return false;
  }
  return true;
}

interface SectionViewProps {
  sessionId: string;
  isHistorical: boolean;
  isLastSection: boolean;
  blocks: SectionBlock[];
  activeItemId: string | null;
  activeCollapseGroupId: string | null;
  copiedItemId: string | null;
  workspacePath: string;
  collapsedCollapseGroups: Record<string, boolean>;
  isEffectiveRunning: boolean;
  lastSectionCollapseGroupIds: Set<string>;
  onToggleCollapseGroup: (groupId: string, collapsed: boolean) => void;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
  onEnterSubAgent: (subAgentId: string) => void;
}

const SectionView = memo(function SectionView({
  sessionId,
  isHistorical,
  isLastSection,
  blocks,
  activeItemId,
  activeCollapseGroupId,
  copiedItemId,
  workspacePath,
  collapsedCollapseGroups,
  isEffectiveRunning,
  lastSectionCollapseGroupIds,
  onToggleCollapseGroup,
  onCopy,
  setItemRef,
  onEnterSubAgent,
}: SectionViewProps): React.JSX.Element {
  const blockStyle = isHistorical ? OFFSCREEN_BLOCK_STYLE : undefined;

  const isCollapseGroupCollapsed = (groupId: string): boolean => {
    if (activeCollapseGroupId === groupId) return false;
    if (groupId in collapsedCollapseGroups) return collapsedCollapseGroups[groupId];
    if (isEffectiveRunning) {
      return !(isLastSection && lastSectionCollapseGroupIds.has(groupId));
    }
    return true;
  };

  return (
    <>
      {blocks.map((block, blockIdx) => {
        const spacing = blockSpacingClass(block, blockIdx === 0);

        if (block.type === "dev_group") {
          return (
            <AnimatedDiv key={block.id} className={spacing} style={blockStyle}>
              <DeveloperMessage items={block.items} />
            </AnimatedDiv>
          );
        }

        if (block.type === "collapse_group") {
          const collapsed = isCollapseGroupCollapsed(block.id);
          return (
            <AnimatedDiv key={block.id} className={spacing} style={blockStyle}>
              <CollapseGroupBlock
                entries={block.entries}
                collapsed={collapsed}
                onToggle={() => {
                  onToggleCollapseGroup(block.id, collapsed);
                }}
                activeItemId={activeItemId}
                copiedItemId={copiedItemId}
                workDir={workspacePath}
                onCopy={onCopy}
                setItemRef={setItemRef}
                renderSubAgent={(entry) => (
                  <SubAgentGroupCard
                    parentSessionId={sessionId}
                    key={entry.groupId}
                    sourceSessionId={entry.sourceSessionId}
                    sourceSessionType={entry.sourceSessionType}
                    sourceSessionDesc={entry.sourceSessionDesc}
                    toolCount={entry.toolCount}
                    onEnterSubAgent={onEnterSubAgent}
                  />
                )}
              />
            </AnimatedDiv>
          );
        }

        if (block.type === "planned_group") {
          const pgCollapsed = isCollapseGroupCollapsed(block.id);
          return (
            <AnimatedDiv key={block.id} className={spacing} style={blockStyle}>
              <PlannedGroupBlock
                todos={block.todos}
                collapsed={pgCollapsed}
                onToggle={() => {
                  onToggleCollapseGroup(block.id, pgCollapsed);
                }}
              >
                {block.blocks.map((inner) => {
                  if (inner.type === "dev_group") {
                    return <DeveloperMessage key={inner.id} items={inner.items} />;
                  }
                  if (inner.type === "sub_agent_group") {
                    return (
                      <SubAgentGroupCard
                        parentSessionId={sessionId}
                        key={inner.groupId}
                        sourceSessionId={inner.sourceSessionId}
                        sourceSessionType={inner.sourceSessionType}
                        sourceSessionDesc={inner.sourceSessionDesc}
                        toolCount={inner.toolCount}
                        onEnterSubAgent={onEnterSubAgent}
                      />
                    );
                  }
                  const innerItem = inner.item;
                  const innerHasRailGrid =
                    GRID_ITEM_TYPES.has(innerItem.type) &&
                    !(innerItem.type === "tool_block" && CARD_TOOL_NAMES.has(innerItem.toolName));
                  const innerOffset = !innerHasRailGrid ? RAIL_CONTENT_OFFSET : "";
                  return (
                    <div key={innerItem.id} className={innerOffset}>
                      <MessageRow
                        item={innerItem}
                        workDir={workspacePath}
                        isActive={innerItem.id === activeItemId}
                        copied={copiedItemId === innerItem.id}
                        onCopy={onCopy}
                        setItemRef={setItemRef}
                      />
                    </div>
                  );
                })}
              </PlannedGroupBlock>
            </AnimatedDiv>
          );
        }

        if (block.type === "sub_agent_group") {
          return (
            <AnimatedDiv key={block.groupId} className={spacing} style={blockStyle}>
              <SubAgentGroupCard
                parentSessionId={sessionId}
                sourceSessionId={block.sourceSessionId}
                sourceSessionType={block.sourceSessionType}
                sourceSessionDesc={block.sourceSessionDesc}
                toolCount={block.toolCount}
                onEnterSubAgent={onEnterSubAgent}
              />
            </AnimatedDiv>
          );
        }

        const item = block.item;
        const hasRailGrid =
          GRID_ITEM_TYPES.has(item.type) &&
          !(item.type === "tool_block" && CARD_TOOL_NAMES.has(item.toolName));
        const itemOffset = item.type !== "user_message" && !hasRailGrid ? RAIL_CONTENT_OFFSET : "";
        return (
          <AnimatedDiv key={item.id} className={`${spacing} ${itemOffset}`} style={blockStyle}>
            <MessageRow
              item={item}
              workDir={workspacePath}
              isActive={item.id === activeItemId}
              copied={copiedItemId === item.id}
              onCopy={onCopy}
              setItemRef={setItemRef}
            />
          </AnimatedDiv>
        );
      })}
    </>
  );
});

const EMPTY_ITEMS: MessageItemType[] = [];
const EMPTY_SUB_AGENT_DESC_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_TYPE_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_FORK_MAP: Record<string, boolean> = {};

/** Index a record safely, returning undefined for absent keys at runtime. */
function recordGet<T>(record: Record<string, T>, key: string): T | undefined {
  return record[key];
}

const BOTTOM_THRESHOLD_PX = 120;

interface SectionBlocksReuseCacheEntry {
  sections: MessageItemType[][];
  sectionBlocks: SectionBlock[][];
  subAgentDescBySessionId: Record<string, string>;
  subAgentTypeBySessionId: Record<string, string>;
  subAgentForkBySessionId: Record<string, boolean>;
}

// Keyed by `${sessionId}:${effectiveSessionId}`. Only the current key is
// relevant; stale entries are pruned on each write to prevent unbounded growth.
const SECTION_REUSE_CACHE = new Map<string, MessageItemType[][]>();
const SECTION_BLOCK_REUSE_CACHE = new Map<string, SectionBlocksReuseCacheEntry>();

function pruneCacheExcept<V>(cache: Map<string, V>, keepKey: string): void {
  if (cache.size <= 1) return;
  for (const key of cache.keys()) {
    if (key !== keepKey) cache.delete(key);
  }
}

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
    return firstMessage.length > 40 ? `${firstMessage.slice(0, 40)}...` : firstMessage;
  }
  return null;
}

function ConnectedSessionStatusBar({
  sessionId,
  viewingSubAgentSessionId,
  runtime,
}: {
  sessionId: string;
  viewingSubAgentSessionId: string | null;
  runtime: SessionRuntimeState | null;
}): React.JSX.Element | null {
  const targetSessionId = viewingSubAgentSessionId ?? sessionId;
  const status = useMessageStore(
    useCallback(
      (state) =>
        state.reducerStateBySessionId[sessionId]?.statusBySessionId[targetSessionId] ?? null,
      [sessionId, targetSessionId],
    ),
  );

  return <SessionStatusBar status={status} runtime={viewingSubAgentSessionId ? null : runtime} />;
}

function MessageListInner({ sessionId }: MessageListProps): React.JSX.Element {
  const t = useT();
  const session = useSessionStore((state) => findSession(state.groups, sessionId));
  const runtime = useSessionStore((state) => {
    const rt: SessionRuntimeState | undefined = state.runtimeBySessionId[sessionId];
    return rt ?? null;
  });
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const items = useMessageStore(
    (state) => recordGet(state.messagesBySessionId, sessionId) ?? EMPTY_ITEMS,
  );
  const subAgentDescBySessionId = useMessageStore((state) => {
    const rs: ReducerState | undefined = state.reducerStateBySessionId[sessionId];
    return rs?.subAgentDescBySessionId ?? EMPTY_SUB_AGENT_DESC_MAP;
  });
  const subAgentTypeBySessionId = useMessageStore((state) => {
    const rs: ReducerState | undefined = state.reducerStateBySessionId[sessionId];
    return rs?.subAgentTypeBySessionId ?? EMPTY_SUB_AGENT_TYPE_MAP;
  });
  const subAgentForkBySessionId = useMessageStore((state) => {
    const rs: ReducerState | undefined = state.reducerStateBySessionId[sessionId];
    return rs?.subAgentForkBySessionId ?? EMPTY_SUB_AGENT_FORK_MAP;
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const previousLastVisibleItemIdRef = useRef<string | null>(null);
  const mainScrollTopRef = useRef<number | null>(null);
  // Tracks programmatic scroll target so handleScroll can ignore the resulting event.
  const autoScrollRef = useRef<{ top: number; time: number } | null>(null);
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
        if (item.type === "unknown_event") return false;
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
  const searchMatchItemIds = useMemo(
    () =>
      searchQuery.trim() ? findMatchingItemIds(visibleItems, searchQuery) : EMPTY_MATCH_ITEM_IDS,
    [visibleItems, searchQuery],
  );

  const activeItemId = useMemo(() => {
    if (searchMatchItemIds.length === 0) return null;
    return searchActiveIndex >= 0 && searchActiveIndex < searchMatchItemIds.length
      ? searchMatchItemIds[searchActiveIndex]
      : searchMatchItemIds[0];
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
    return () => {
      document.removeEventListener("keydown", handler);
    };
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

  useMountEffect(() => () => {
    window.clearTimeout(copyTimerRef.current);
  });

  const mainSessionRunningByStatus = useMessageStore(
    useCallback(
      (state) => {
        const status = state.reducerStateBySessionId[sessionId]?.statusBySessionId[sessionId];
        return (
          ((status?.taskActive ?? false) ||
            (status?.thinkingActive ?? false) ||
            (status?.compacting ?? false) ||
            (status?.isComposing ?? false)) &&
          !status?.awaitingInput
        );
      },
      [sessionId],
    ),
  );
  const viewedSubAgentRunningByStatus = useMessageStore(
    useCallback(
      (state) => {
        if (!viewingSubAgentSessionId) return false;
        const status =
          state.reducerStateBySessionId[sessionId]?.statusBySessionId[viewingSubAgentSessionId];
        return (
          ((status?.taskActive ?? false) ||
            (status?.thinkingActive ?? false) ||
            (status?.compacting ?? false) ||
            (status?.isComposing ?? false)) &&
          !status?.awaitingInput
        );
      },
      [sessionId, viewingSubAgentSessionId],
    ),
  );
  const isMainSessionRunning = runtime?.sessionState === "running" || mainSessionRunningByStatus;

  const isEffectiveRunning = viewingSubAgentSessionId
    ? viewedSubAgentRunningByStatus
    : isMainSessionRunning;

  // Reset collapse state on running->stopped transition: no event handler to
  // hook into since isEffectiveRunning is derived from store selectors.
  const prevRunningRef = useRef(isEffectiveRunning);
  useEffect(() => {
    if (prevRunningRef.current && !isEffectiveRunning) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived state reset
      setCollapsedCollapseGroups({});
    }
    prevRunningRef.current = isEffectiveRunning;
  }, [isEffectiveRunning]);

  // Reset collapse state when switching between main and sub-agent views
  const prevEffectiveSessionIdRef = useRef(effectiveSessionId);
  useEffect(() => {
    if (prevEffectiveSessionIdRef.current !== effectiveSessionId) {
      prevEffectiveSessionIdRef.current = effectiveSessionId;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived state reset
      setCollapsedCollapseGroups({});
    }
  }, [effectiveSessionId]);

  const handleCopy = useCallback(async (item: MessageItemType) => {
    if (!isCopyableAssistantText(item)) return;
    try {
      await navigator.clipboard.writeText(item.content);
      setCopiedItemId(item.id);
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => {
        setCopiedItemId(null);
      }, 2000);
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

  const performScrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      const container = scrollRef.current;
      if (!container) return;
      container.style.overflowAnchor = "none";
      container.scrollTo({ top: container.scrollHeight, behavior });
      const expectedTop = Math.max(0, container.scrollHeight - container.clientHeight);
      autoScrollRef.current = { top: expectedTop, time: Date.now() };
      wasAtBottomRef.current = true;
      sessionStorage.setItem(`scroll-${sessionId}`, String(expectedTop));
    },
    [sessionId],
  );

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      performScrollToBottom(behavior);
      setShowScrollToBottom(false);
    },
    [performScrollToBottom],
  );

  // Restore scroll position when items first load for a session
  const hasItems = visibleItems.length > 0;
  useLayoutEffect(() => {
    if (!hasItems) {
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
    // Mark as programmatic so the resulting scroll event is ignored
    autoScrollRef.current = { top: container.scrollTop, time: Date.now() };
    wasAtBottomRef.current = isNearBottom(container);
    container.style.overflowAnchor = wasAtBottomRef.current ? "none" : "auto";
  }, [hasItems, sessionId]);

  useLayoutEffect(() => {
    const lastItem = visibleItems.at(-1);
    const previousLastItemId = previousLastVisibleItemIdRef.current;
    previousLastVisibleItemIdRef.current = lastItem?.id ?? null;
    if (!lastItem || previousLastItemId === null || previousLastItemId === lastItem.id) {
      return;
    }

    const sourceSessionId = lastItem.sessionId ?? sessionId;
    if (sourceSessionId !== sessionId || lastItem.type !== "user_message") {
      return;
    }

    performScrollToBottom("auto");
  }, [performScrollToBottom, sessionId, visibleItems]);

  useEffect(() => {
    const content = contentRef.current;
    const container = scrollRef.current;
    if (!content || !container) return;
    // Start with overflow-anchor matching the current scroll intent
    container.style.overflowAnchor = wasAtBottomRef.current ? "none" : "auto";
    let prevScrollHeight = container.scrollHeight;
    const observer = new ResizeObserver(() => {
      const newScrollHeight = container.scrollHeight;
      const grew = newScrollHeight > prevScrollHeight;
      prevScrollHeight = newScrollHeight;
      // Only auto-scroll when content grows (streaming text, new items).
      // When content shrinks (collapse, spacer removal) the browser naturally
      // clamps scrollTop to the new max, keeping the bottom anchored without
      // the jarring snap that used to cause visible jitter.
      if (wasAtBottomRef.current && grew) {
        // Disable browser scroll anchoring so it doesn't fight our scrollTop
        container.style.overflowAnchor = "none";
        container.scrollTop = newScrollHeight;
        autoScrollRef.current = {
          top: Math.max(0, newScrollHeight - container.clientHeight),
          time: Date.now(),
        };
      }
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
    // Ignore scroll events caused by our own programmatic scrollTop changes,
    // but always update button visibility.
    const auto = autoScrollRef.current;
    const isAutoScroll =
      auto && Date.now() - auto.time < 500 && Math.abs(container.scrollTop - auto.top) < 2;
    if (isAutoScroll) {
      autoScrollRef.current = null;
      setShowScrollToBottom(!isNearBottom(container));
      return;
    }
    const atBottom = isNearBottom(container);
    wasAtBottomRef.current = atBottom;
    // Auto-scroll mode: disable browser anchoring (we control scrollTop).
    // User-scroll mode: enable anchoring so content above stays stable.
    container.style.overflowAnchor = atBottom ? "none" : "auto";
    setShowScrollToBottom(!atBottom);
    sessionStorage.setItem(`scroll-${sessionId}`, String(container.scrollTop));
  }, [sessionId]);

  const setItemRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) {
      itemRefsMap.current.set(id, el);
    } else {
      itemRefsMap.current.delete(id);
    }
  }, []);

  // Enable entry animations only after the initial paint is committed.
  // Double-rAF ensures history items rendered on the first frame are excluded.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.classList.remove("message-list-ready");
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.classList.add("message-list-ready");
      });
    });
  }, [effectiveSessionId]);

  // Sub-agent navigation
  const handleEnterSubAgent = useCallback(
    (subAgentId: string) => {
      mainScrollTopRef.current = scrollRef.current?.scrollTop ?? null;
      setViewingSubAgentSessionId(subAgentId);
      history.pushState(null, "", `/session/${sessionId}/agent/${subAgentId}`);
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.style.overflowAnchor = "none";
          scrollRef.current.scrollTo({ top: 0 });
        }
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
    return () => {
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  const sectionCacheKey = `${sessionId}:${effectiveSessionId}`;

  const sections = useMemo(() => {
    const nextSections = buildSections(visibleItems, sessionId, effectiveSessionId);
    const prevSections = SECTION_REUSE_CACHE.get(sectionCacheKey);
    const reusedSections = prevSections
      ? nextSections.map((section, index) =>
          canReuseSectionItems(prevSections[index], section) ? prevSections[index] : section,
        )
      : nextSections;
    SECTION_REUSE_CACHE.set(sectionCacheKey, reusedSections);
    pruneCacheExcept(SECTION_REUSE_CACHE, sectionCacheKey);
    return reusedSections;
  }, [effectiveSessionId, sectionCacheKey, sessionId, visibleItems]);

  const sectionBlocks = useMemo(() => {
    const prev = SECTION_BLOCK_REUSE_CACHE.get(sectionCacheKey);
    const canReuseCachedBlocks =
      prev !== undefined &&
      prev.subAgentDescBySessionId === subAgentDescBySessionId &&
      prev.subAgentTypeBySessionId === subAgentTypeBySessionId &&
      prev.subAgentForkBySessionId === subAgentForkBySessionId;

    const nextSectionBlocks = sections.map((section, index) => {
      if (canReuseCachedBlocks && prev.sections[index] === section) {
        return prev.sectionBlocks[index];
      }
      return buildSectionBlocksForSection(
        section,
        sessionId,
        effectiveSessionId,
        subAgentDescBySessionId,
        subAgentTypeBySessionId,
        subAgentForkBySessionId,
      );
    });

    SECTION_BLOCK_REUSE_CACHE.set(sectionCacheKey, {
      sections,
      sectionBlocks: nextSectionBlocks,
      subAgentDescBySessionId,
      subAgentTypeBySessionId,
      subAgentForkBySessionId,
    });
    pruneCacheExcept(SECTION_BLOCK_REUSE_CACHE, sectionCacheKey);

    return nextSectionBlocks;
  }, [
    sectionCacheKey,
    sections,
    sessionId,
    effectiveSessionId,
    subAgentDescBySessionId,
    subAgentForkBySessionId,
    subAgentTypeBySessionId,
  ]);

  const collapseGroupIdByItemId = useMemo(() => {
    const map = new Map<string, string>();
    for (const blocks of sectionBlocks) {
      for (const block of blocks) {
        if (block.type === "collapse_group") {
          for (const entry of block.entries) {
            if (entry.type !== "sub_agent_group") map.set(entry.id, block.id);
          }
        } else if (block.type === "planned_group") {
          for (const inner of block.blocks) {
            if (inner.type === "item") map.set(inner.item.id, block.id);
          }
        }
      }
    }
    return map;
  }, [sectionBlocks]);

  const activeCollapseGroupId = useMemo(
    () => (activeItemId === null ? null : (collapseGroupIdByItemId.get(activeItemId) ?? null)),
    [activeItemId, collapseGroupIdByItemId],
  );

  const lastSectionCollapseGroupIds = useMemo(() => {
    const lastSection = sectionBlocks.at(-1);
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

  const handleToggleCollapseGroup = useCallback((groupId: string, collapsed: boolean) => {
    setCollapsedCollapseGroups((prev) => ({
      ...prev,
      [groupId]: !collapsed,
    }));
  }, []);

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
    return () => {
      document.removeEventListener("keydown", handler);
    };
  }, [handleCollapseAll, handleExpandAll]);

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
            onSearchOpen={() => {
              setSearchOpen(true);
            }}
            onCollapseAll={handleCollapseAll}
            onExpandAll={handleExpandAll}
            onBack={viewingSubAgentSessionId ? handleExitSubAgent : undefined}
            subAgentLabel={subAgentLabel}
            isRunning={isEffectiveRunning}
          />
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            data-message-scroll-container="true"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-y-none [scrollbar-gutter:stable]"
          >
            <div ref={contentRef}>
              <div className="mx-auto max-w-4xl space-y-5 px-4 pb-2 pt-8 sm:px-6">
                {hasItems ? (
                  <>
                    {sections.map((section, sectionIndex) => (
                      <div
                        key={section[0].id}
                        className="group/section"
                        style={
                          sectionIndex < sections.length - 1
                            ? { contentVisibility: "auto", containIntrinsicSize: "auto 200px" }
                            : undefined
                        }
                      >
                        <SectionView
                          sessionId={sessionId}
                          isHistorical={sectionIndex < sections.length - 1}
                          isLastSection={sectionIndex === sections.length - 1}
                          blocks={sectionBlocks[sectionIndex] ?? []}
                          activeItemId={activeItemId}
                          activeCollapseGroupId={activeCollapseGroupId}
                          copiedItemId={copiedItemId}
                          workspacePath={workspacePath}
                          collapsedCollapseGroups={collapsedCollapseGroups}
                          isEffectiveRunning={isEffectiveRunning}
                          lastSectionCollapseGroupIds={
                            sectionIndex === sections.length - 1
                              ? lastSectionCollapseGroupIds
                              : EMPTY_GROUP_IDS
                          }
                          onToggleCollapseGroup={handleToggleCollapseGroup}
                          onCopy={handleCopy}
                          setItemRef={setItemRef}
                          onEnterSubAgent={handleEnterSubAgent}
                        />
                      </div>
                    ))}
                    <div aria-hidden="true" className="h-12" />
                  </>
                ) : runtime?.wsState === "connecting" ? (
                  <div className="flex min-h-[240px] items-center justify-center">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-neutral-400" />
                  </div>
                ) : null}
              </div>
              <div className="mx-auto max-w-4xl px-4 pb-4 sm:px-6">
                <ConnectedSessionStatusBar
                  sessionId={sessionId}
                  viewingSubAgentSessionId={viewingSubAgentSessionId}
                  runtime={runtime}
                />
              </div>
            </div>
          </div>
          {showScrollToBottom && hasItems ? (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-20 -translate-x-1/2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => {
                      scrollToBottom();
                    }}
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

export const MessageList = memo(
  MessageListInner,
  (prev, next) => prev.sessionId === next.sessionId,
);
