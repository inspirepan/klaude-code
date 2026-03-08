import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  ChevronRight,
  CircleHelp,
  Lock,
  PanelLeftOpen,
  PanelRightOpen,
  RefreshCw,
} from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import type { SessionStatusState } from "../../stores/event-reducer";
import type {
  MessageItem as MessageItemType,
  ItemTimestamp,
  AssistantTextItem,
} from "../../types/message";
import type { SessionSummary } from "../../types/session";
import { MessageItem } from "./MessageItem";
import { SearchBar } from "./SearchBar";
import { SearchProvider, type SearchState } from "./search-context";

const EMPTY_ITEMS: MessageItemType[] = [];
const EMPTY_SUB_AGENT_DESC_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_TYPE_MAP: Record<string, string> = {};
const EMPTY_SUB_AGENT_FINISHED_MAP: Record<string, boolean> = {};
const EMPTY_STATUS_MAP: Record<string, SessionStatusState> = {};
const COMPACT_NUMBER_FORMATTER = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

interface MessageListProps {
  sessionId: string;
}

function shortSessionId(id: string): string {
  return id.slice(0, 8);
}

function formatSubAgentTypeLabel(type: string | null): string {
  if (type === null || type.trim().length === 0) {
    return "Agent";
  }
  return type.charAt(0).toUpperCase() + type.slice(1);
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

function splitSessionTitle(title: string): { primary: string; secondary: string | null } {
  const separator = " — ";
  const separatorIndex = title.indexOf(separator);
  if (separatorIndex === -1) {
    return { primary: title, secondary: null };
  }
  return {
    primary: title.slice(0, separatorIndex),
    secondary: title.slice(separatorIndex + separator.length),
  };
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

type SectionBlock = SectionItemBlock | SectionSubAgentBlock;

function formatTime(ts: ItemTimestamp): string | null {
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

function extractToolPreviewDetail(toolName: string, args: string): string {
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>;
    switch (toolName) {
      case "Bash":
        return typeof parsed.command === "string" ? parsed.command : "";
      case "Read":
      case "Edit":
      case "Write":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "WebFetch":
        return typeof parsed.url === "string" ? parsed.url : "";
      case "WebSearch":
        return typeof parsed.query === "string" ? parsed.query : "";
      case "Agent":
        return typeof parsed.description === "string" ? parsed.description : "";
      default:
        return "";
    }
  } catch {
    return args.trim().split("\n")[0] ?? "";
  }
}

function previewAssistantResult(content: string): { text: string; hasMore: boolean } {
  const lines = content.split("\n");
  if (lines.length <= 10) return { text: content, hasMore: false };
  return { text: lines.slice(0, 10).join("\n"), hasMore: true };
}

function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  if (Math.abs(value) < 1000) return Math.round(value).toString();
  return COMPACT_NUMBER_FORMATTER.format(value);
}

function formatElapsed(totalSeconds: number): string {
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

function getSessionActivityText(status: SessionStatusState | null): string | null {
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

function getSessionSummaryParts(status: SessionStatusState | null, nowSeconds: number): string[] {
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

function getSessionMetaRows(
  status: SessionStatusState | null,
  nowSeconds: number,
): Array<{ label: string; value: string }> {
  if (status === null) return [];

  const rows: Array<{ label: string; value: string }> = [];
  if (status.tokenInput !== null) {
    rows.push({ label: "Input", value: formatCompactNumber(status.tokenInput) });
  }
  if ((status.tokenCached ?? 0) > 0) {
    rows.push({
      label: "Cached",
      value:
        status.cacheHitRate !== null
          ? `${formatCompactNumber(status.tokenCached ?? 0)} (${Math.round(status.cacheHitRate * 100)}%)`
          : formatCompactNumber(status.tokenCached ?? 0),
    });
  }
  if ((status.tokenCacheWrite ?? 0) > 0) {
    rows.push({ label: "Cache write", value: formatCompactNumber(status.tokenCacheWrite ?? 0) });
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

function isCopyableAssistantText(item: MessageItemType): item is AssistantTextItem {
  return item.type === "assistant_text" && !item.isStreaming && item.content.split("\n").length > 5;
}

export function MessageList({ sessionId }: MessageListProps): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const refreshSession = useSessionStore((state) => state.refreshSession);
  const runtime = useSessionStore((state) => state.runtimeBySessionId[sessionId] ?? null);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const rightSidebarOpen = useAppStore((state) => state.rightSidebarOpen);
  const setRightSidebarOpen = useAppStore((state) => state.setRightSidebarOpen);
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
  const bottomRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const shouldStickToBottomRef = useRef(true);
  const previousLastVisibleItemIdRef = useRef<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActiveIndex, setSearchActiveIndex] = useState(-1);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [collapsedSubAgentGroups, setCollapsedSubAgentGroups] = useState<Record<string, boolean>>(
    {},
  );
  const [subAgentMetaOpen, setSubAgentMetaOpen] = useState<Record<string, boolean>>({});
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
  const refreshDisabled =
    refreshing ||
    runtime?.sessionState === "running" ||
    runtime?.sessionState === "waiting_user_input";

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

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshSession(sessionId);
    } finally {
      setRefreshing(false);
    }
  }, [refreshSession, sessionId]);

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
  useEffect(() => {
    if (!hasItems) return;
    const saved = sessionStorage.getItem(`scroll-${sessionId}`);
    if (saved !== null) {
      scrollRef.current?.scrollTo({ top: parseInt(saved, 10) });
    } else {
      bottomRef.current?.scrollIntoView();
    }
    const container = scrollRef.current;
    if (container) {
      shouldStickToBottomRef.current =
        container.scrollHeight - container.scrollTop - container.clientHeight < 150;
    }
  }, [sessionId, hasItems]);

  useEffect(() => {
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
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [sessionId, visibleItems]);

  // Auto-scroll on streamed updates only when user is already near bottom.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    if (shouldStickToBottomRef.current) {
      container.scrollTo({ top: container.scrollHeight });
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
      const blocks: SectionBlock[] = [];
      const subAgentBlockIndexBySessionId = new Map<string, number>();
      let i = 0;
      while (i < section.length) {
        const item = section[i];
        const sourceSessionId = item.sessionId ?? sessionId;
        if (sourceSessionId === sessionId) {
          blocks.push({ type: "item", item });
          i += 1;
          continue;
        }

        const existingBlockIndex = subAgentBlockIndexBySessionId.get(sourceSessionId);
        if (existingBlockIndex !== undefined) {
          const existingBlock = blocks[existingBlockIndex];
          if (existingBlock?.type === "sub_agent_group") {
            existingBlock.items.push(item);
          }
          i += 1;
          continue;
        }

        const groupItems: MessageItemType[] = [item];
        const blockIndex = blocks.length;
        blocks.push({
          type: "sub_agent_group",
          groupId: `${section[0]?.id ?? sourceSessionId}-${sourceSessionId}`,
          sourceSessionId,
          sourceSessionType: subAgentTypeBySessionId[sourceSessionId] ?? null,
          sourceSessionDesc: subAgentDescBySessionId[sourceSessionId] ?? null,
          items: groupItems,
        });
        subAgentBlockIndexBySessionId.set(sourceSessionId, blockIndex);
        i += 1;
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

  const activeGroupId =
    activeItemId === null ? null : (subAgentGroupIdByItemId.get(activeItemId) ?? null);
  const nowSeconds = nowMs / 1000;

  return (
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

        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-neutral-200/80 bg-white/95 px-4 py-2 backdrop-blur sm:px-6">
          {!sidebarOpen ? (
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              onClick={() => {
                setSidebarOpen(true);
              }}
              title="Expand sidebar"
              aria-label="Expand sidebar"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-baseline gap-2 text-[14px] leading-5">
              <span className="truncate font-semibold text-neutral-800" title={primaryTitle}>
                {primaryTitle}
              </span>
              {secondaryTitle ? (
                <span className="truncate text-neutral-500" title={secondaryTitle}>
                  {secondaryTitle}
                </span>
              ) : null}
              {sessionReadOnly ? (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                  <Lock className="h-3 w-3" />
                  <span>Read-only</span>
                </span>
              ) : null}
              {workspacePath ? (
                <span
                  className="truncate font-sans text-[14px] leading-5 text-neutral-400"
                  title={workspacePath}
                >
                  {workspacePath}
                </span>
              ) : null}
            </div>
          </div>
          {sessionReadOnly ? (
            <div className="shrink-0 rounded-md border border-amber-200 bg-amber-50 px-3 py-1 text-[11px] text-amber-800">
              This session is owned by another live runtime. Web can observe it, but cannot send
              control actions.
            </div>
          ) : null}
          <button
            type="button"
            disabled={refreshDisabled}
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
            onClick={() => {
              void handleRefresh();
            }}
            title={refreshDisabled ? "Wait until current task completes" : "Refresh session"}
            aria-label="Refresh session"
          >
            <RefreshCw
              className={`h-4 w-4 ${refreshing ? "animate-spin" : ""} ${refreshDisabled ? "opacity-40" : ""}`}
            />
          </button>
          {!rightSidebarOpen ? (
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              onClick={() => {
                setRightSidebarOpen(true);
              }}
              title="Expand right sidebar"
              aria-label="Expand right sidebar"
            >
              <PanelRightOpen className="h-4 w-4" />
            </button>
          ) : null}
        </div>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
        >
          <div className="mx-auto max-w-4xl space-y-5 px-4 pb-14 pt-8 sm:px-6">
            {hasItems ? (
              <>
                {sections.map((section, sectionIndex) => (
                  <div key={section[0].id} className="space-y-5">
                    {sectionBlocks[sectionIndex]?.map((block) => {
                      if (block.type === "sub_agent_group") {
                        const collapsed =
                          activeGroupId === block.groupId
                            ? false
                            : (collapsedSubAgentGroups[block.groupId] ?? true);
                        const toolItems = block.items.filter(
                          (item): item is Extract<MessageItemType, { type: "tool_block" }> =>
                            item.type === "tool_block",
                        );
                        const previewTools = toolItems.slice(-3);
                        const moreToolsCount = Math.max(0, toolItems.length - previewTools.length);
                        const isFinished =
                          subAgentFinishedBySessionId[block.sourceSessionId] === true;
                        const subAgentStatus = statusBySessionId[block.sourceSessionId] ?? null;
                        const subAgentActivityText = getSessionActivityText(subAgentStatus);
                        const subAgentSummaryParts = getSessionSummaryParts(
                          subAgentStatus,
                          nowSeconds,
                        );
                        const subAgentMetaRows = getSessionMetaRows(subAgentStatus, nowSeconds);
                        const hasSubAgentStatus =
                          subAgentActivityText !== null ||
                          subAgentSummaryParts.length > 0 ||
                          subAgentMetaRows.length > 0;
                        const lastAssistantItem = [...block.items]
                          .reverse()
                          .find(
                            (item): item is AssistantTextItem =>
                              item.type === "assistant_text" && item.content.trim().length > 0,
                          );
                        const lastCompletedAssistantItem = [...block.items]
                          .reverse()
                          .find(
                            (item): item is AssistantTextItem =>
                              item.type === "assistant_text" &&
                              !item.isStreaming &&
                              item.content.trim().length > 0,
                          );
                        const resultPreview =
                          isFinished && lastCompletedAssistantItem
                            ? previewAssistantResult(lastCompletedAssistantItem.content)
                            : null;
                        const streamingPreview =
                          !isFinished && lastAssistantItem
                            ? previewAssistantResult(lastAssistantItem.content)
                            : null;
                        return (
                          <div key={block.groupId} className="group/subagent flex min-w-0 gap-4">
                            <div className="min-w-0 flex-1 rounded-2xl border border-neutral-200/80 bg-white shadow-sm shadow-neutral-200/40">
                              <button
                                type="button"
                                onClick={() => {
                                  setCollapsedSubAgentGroups((prev) => ({
                                    ...prev,
                                    [block.groupId]: !collapsed,
                                  }));
                                }}
                                className="flex w-full cursor-pointer items-center gap-2 px-4 py-3 text-left"
                              >
                                <ChevronRight
                                  className={`h-3.5 w-3.5 shrink-0 text-neutral-300 transition-transform duration-150 ${collapsed ? "" : "rotate-90"}`}
                                />
                                <div className="flex min-w-0 items-baseline gap-2">
                                  <span className="whitespace-nowrap text-[14px] font-semibold text-neutral-800">
                                    {formatSubAgentTypeLabel(block.sourceSessionType)}
                                  </span>
                                  <span className="truncate text-[14px] text-neutral-600">
                                    {block.sourceSessionDesc ??
                                      `Sub Agent ${shortSessionId(block.sourceSessionId)}`}
                                  </span>
                                </div>
                              </button>
                              {hasSubAgentStatus ? (
                                <div className="px-3.5 pb-2 pt-0 text-[12px]">
                                  {subAgentActivityText ? (
                                    <div className="truncate font-mono text-neutral-500">
                                      {subAgentActivityText}
                                    </div>
                                  ) : null}
                                  {subAgentSummaryParts.length > 0 ||
                                  subAgentMetaRows.length > 0 ? (
                                    <div className="mt-1 flex items-center gap-2">
                                      {subAgentSummaryParts.length > 0 ? (
                                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-neutral-400">
                                          {subAgentSummaryParts.map((part) => (
                                            <span key={part}>{part}</span>
                                          ))}
                                        </div>
                                      ) : null}
                                      {subAgentMetaRows.length > 0 ? (
                                        <div
                                          className="relative"
                                          onMouseEnter={() => {
                                            setSubAgentMetaOpen((prev) => ({
                                              ...prev,
                                              [block.groupId]: true,
                                            }));
                                          }}
                                          onMouseLeave={() => {
                                            setSubAgentMetaOpen((prev) => ({
                                              ...prev,
                                              [block.groupId]: false,
                                            }));
                                          }}
                                        >
                                          <button
                                            type="button"
                                            className="inline-flex h-5 w-5 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                                            aria-label="Show sub-agent metadata"
                                            onClick={() => {
                                              setSubAgentMetaOpen((prev) => ({
                                                ...prev,
                                                [block.groupId]: !prev[block.groupId],
                                              }));
                                            }}
                                          >
                                            <CircleHelp className="h-3 w-3" />
                                          </button>
                                          {subAgentMetaOpen[block.groupId] ? (
                                            <div className="absolute right-0 top-full z-20 mt-2 min-w-[180px] rounded-xl border border-neutral-200/80 bg-white p-3 shadow-lg shadow-neutral-200/60">
                                              <div className="space-y-1.5 text-[12px] leading-5">
                                                {subAgentMetaRows.map((row) => (
                                                  <div
                                                    key={row.label}
                                                    className="flex items-start justify-between gap-4"
                                                  >
                                                    <span className="text-neutral-400">
                                                      {row.label}
                                                    </span>
                                                    <span className="text-right font-mono text-neutral-600">
                                                      {row.value}
                                                    </span>
                                                  </div>
                                                ))}
                                              </div>
                                            </div>
                                          ) : null}
                                        </div>
                                      ) : null}
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                              {collapsed ? (
                                <div className="px-3.5 pb-3.5 pt-0.5">
                                  {resultPreview ? (
                                    <>
                                      <div className="mb-1.5 text-xs text-neutral-400">
                                        {toolItems.length} tools
                                      </div>
                                      <div className="mt-2.5">
                                        <div className="relative overflow-hidden rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2">
                                          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-neutral-500">
                                            {resultPreview.text}
                                          </pre>
                                          {resultPreview.hasMore ? (
                                            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-neutral-50/95 to-transparent" />
                                          ) : null}
                                        </div>
                                      </div>
                                    </>
                                  ) : streamingPreview ? (
                                    <>
                                      <div className="mb-1.5 flex items-center gap-2 text-xs text-neutral-400">
                                        <span>Running</span>
                                        <span>·</span>
                                        <span>{toolItems.length} tools</span>
                                      </div>
                                      <div className="space-y-2.5">
                                        {previewTools.length > 0 ? (
                                          <div className="space-y-1.5">
                                            {previewTools.map((toolItem) => {
                                              const detail = extractToolPreviewDetail(
                                                toolItem.toolName,
                                                toolItem.arguments,
                                              );
                                              return (
                                                <div
                                                  key={toolItem.id}
                                                  className="flex min-w-0 items-baseline gap-1.5 text-[11px]"
                                                >
                                                  <div className="flex items-baseline gap-1">
                                                    <span className="relative top-px whitespace-nowrap font-sans text-neutral-500">
                                                      {toolItem.toolName}
                                                    </span>
                                                    {toolItem.isStreaming ? (
                                                      <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
                                                    ) : null}
                                                  </div>
                                                  {detail ? (
                                                    <code className="min-w-0 max-w-full truncate rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-neutral-500">
                                                      {detail}
                                                    </code>
                                                  ) : null}
                                                </div>
                                              );
                                            })}
                                          </div>
                                        ) : null}
                                        <div className="relative overflow-hidden rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2">
                                          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-neutral-500">
                                            {streamingPreview.text}
                                          </pre>
                                          {streamingPreview.hasMore ? (
                                            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-neutral-50/95 to-transparent" />
                                          ) : null}
                                        </div>
                                      </div>
                                    </>
                                  ) : (
                                    <>
                                      {moreToolsCount > 0 ? (
                                        <div className="mb-1.5 text-xs text-neutral-400">
                                          {moreToolsCount} more tools
                                        </div>
                                      ) : null}
                                      {previewTools.length > 0 ? (
                                        <div className="space-y-1.5">
                                          {previewTools.map((toolItem) => {
                                            const detail = extractToolPreviewDetail(
                                              toolItem.toolName,
                                              toolItem.arguments,
                                            );
                                            return (
                                              <div
                                                key={toolItem.id}
                                                className="flex min-w-0 items-baseline gap-1.5 text-[11px]"
                                              >
                                                <span className="relative top-px whitespace-nowrap font-sans text-neutral-500">
                                                  {toolItem.toolName}
                                                </span>
                                                {detail ? (
                                                  <code className="min-w-0 max-w-full truncate rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-neutral-500">
                                                    {detail}
                                                  </code>
                                                ) : null}
                                              </div>
                                            );
                                          })}
                                        </div>
                                      ) : (
                                        <div className="text-xs text-neutral-400">
                                          No tool calls
                                        </div>
                                      )}
                                    </>
                                  )}
                                </div>
                              ) : (
                                <div className="space-y-5 px-3.5 pb-3.5 pt-0.5">
                                  {block.items.map((item, index) => {
                                    const time = formatTime(item.timestamp);
                                    const prevTime =
                                      index > 0
                                        ? formatTime(block.items[index - 1]!.timestamp)
                                        : null;
                                    const displayTime = time && time !== prevTime ? time : null;
                                    const isActive = item.id === activeItemId;
                                    const canCopy = isCopyableAssistantText(item);
                                    const copied = copiedItemId === item.id;
                                    const usesInlineToolLayout = item.type === "tool_block";
                                    return (
                                      <div
                                        key={item.id}
                                        ref={(el) => setItemRef(item.id, el)}
                                        className="group/row relative min-w-0"
                                      >
                                        <div
                                          className={`min-w-0 flex-1 rounded-xl transition-shadow duration-150 ${usesInlineToolLayout ? "" : "bg-neutral-50/60"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
                                        >
                                          <MessageItem
                                            item={item}
                                            compact
                                            workDir={workspacePath}
                                          />
                                          {canCopy ? (
                                            <div className="mt-1 flex justify-end sm:hidden">
                                              <button
                                                type="button"
                                                onClick={() => handleCopy(item)}
                                                className="cursor-pointer text-xs leading-none text-neutral-300 transition-colors duration-150 hover:text-neutral-500"
                                                title={copied ? "Copied" : "Copy"}
                                              >
                                                {copied ? "[Copied]" : "[Copy]"}
                                              </button>
                                            </div>
                                          ) : null}
                                        </div>
                                        <div className="absolute left-[calc(100%+24px)] top-0 hidden w-[112px] flex-col items-end gap-1 whitespace-nowrap pt-0.5 text-right sm:flex">
                                          {displayTime ? (
                                            <span className="relative -top-0.5 select-none pb-1 text-xs tabular-nums leading-none text-neutral-300 opacity-0 transition-opacity duration-150 group-hover/row:opacity-100">
                                              {displayTime}
                                            </span>
                                          ) : null}
                                          {canCopy ? (
                                            <button
                                              type="button"
                                              onClick={() => handleCopy(item)}
                                              className="cursor-pointer text-xs leading-none text-neutral-300 opacity-0 transition-opacity duration-150 hover:text-neutral-500 group-hover/row:opacity-100"
                                              title={copied ? "Copied" : "Copy"}
                                            >
                                              {copied ? "[Copied]" : "[Copy]"}
                                            </button>
                                          ) : null}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                            <div className="hidden w-[112px] shrink-0 sm:block" />
                          </div>
                        );
                      }

                      const item = block.item;
                      const time = formatTime(item.timestamp);
                      const isActive = item.id === activeItemId;
                      const canCopy = isCopyableAssistantText(item);
                      const copied = copiedItemId === item.id;
                      const isUser = item.type === "user_message";
                      return (
                        <div
                          key={item.id}
                          ref={(el) => setItemRef(item.id, el)}
                          className={`group/row flex min-w-0 gap-4 ${isUser ? "sticky top-0 z-10 -mx-4 -mt-2.5 px-4 pt-2.5 sm:-mx-6 sm:px-6" : ""}`}
                        >
                          <div
                            className={`min-w-0 flex-1 transition-shadow duration-150 ${isUser ? "overflow-hidden rounded-[22px] shadow-sm" : "rounded-xl"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
                          >
                            <MessageItem item={item} workDir={workspacePath} />
                            {canCopy ? (
                              <div className="mt-1 flex justify-end sm:hidden">
                                <button
                                  type="button"
                                  onClick={() => handleCopy(item)}
                                  className="cursor-pointer text-xs leading-none text-neutral-300 transition-colors duration-150 hover:text-neutral-500"
                                  title={copied ? "Copied" : "Copy"}
                                >
                                  {copied ? "[Copied]" : "[Copy]"}
                                </button>
                              </div>
                            ) : null}
                          </div>
                          <div className="hidden shrink-0 flex-col items-end gap-1 whitespace-nowrap pt-0.5 text-right sm:flex">
                            {time ? (
                              <span className="relative -top-0.5 select-none pb-1 text-xs tabular-nums leading-none text-neutral-300 opacity-0 transition-opacity duration-150 group-hover/row:opacity-100">
                                {time}
                              </span>
                            ) : null}
                            {canCopy ? (
                              <button
                                type="button"
                                onClick={() => handleCopy(item)}
                                className="cursor-pointer text-xs leading-none text-neutral-300 opacity-0 transition-opacity duration-150 hover:text-neutral-500 group-hover/row:opacity-100"
                                title={copied ? "Copied" : "Copy"}
                              >
                                {copied ? "[Copied]" : "[Copy]"}
                              </button>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))}
                <div
                  ref={bottomRef}
                  aria-hidden="true"
                  className={`transition-[height] duration-150 ${hasStreamingAssistantText ? "h-12" : "h-0"}`}
                />
              </>
            ) : runtime?.wsState === "connecting" ? (
              <div className="flex min-h-[240px] items-center justify-center">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-neutral-200 border-t-neutral-500" />
              </div>
            ) : (
              <div className="flex min-h-[240px] items-center justify-center">
                <div className="rounded-3xl border border-dashed border-neutral-200 bg-neutral-50/70 px-6 py-10 text-center">
                  <div className="text-[15px] font-semibold text-neutral-700">No messages yet</div>
                  <div className="mt-1 text-[13px] text-neutral-500">
                    Send a message below to start this session.
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </SearchProvider>
  );
}
