import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { ChevronRight, Loader2, PanelLeftOpen, PanelRightOpen, RefreshCw } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
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

interface MessageListProps {
  sessionId: string;
}

function shortSessionId(id: string): string {
  return id.slice(0, 8);
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
  const selectSession = useSessionStore((state) => state.selectSession);
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActiveIndex, setSearchActiveIndex] = useState(-1);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [collapsedSubAgentGroups, setCollapsedSubAgentGroups] = useState<Record<string, boolean>>(
    {},
  );
  const copyTimerRef = useRef(0);

  const session = useMemo(
    () => groups.flatMap((group) => group.sessions).find((item) => item.id === sessionId) ?? null,
    [groups, sessionId],
  );
  const sessionTitle = useMemo(() => getSessionTitle(session), [session]);
  const workspacePath = session?.work_dir ?? "";

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

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await selectSession(sessionId);
    } finally {
      setRefreshing(false);
    }
  }, [selectSession, sessionId]);

  useEffect(() => () => window.clearTimeout(copyTimerRef.current), []);

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
  }, [sessionId, hasItems]);

  // Auto-scroll on new messages only when near bottom
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 150;
    if (nearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [visibleItems.length]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
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
      let i = 0;
      while (i < section.length) {
        const item = section[i];
        const sourceSessionId = item.sessionId ?? sessionId;
        if (sourceSessionId === sessionId) {
          blocks.push({ type: "item", item });
          i += 1;
          continue;
        }

        const groupItems: MessageItemType[] = [item];
        i += 1;
        while (i < section.length) {
          const next = section[i];
          const nextSourceSessionId = next.sessionId ?? sessionId;
          if (nextSourceSessionId !== sourceSessionId) break;
          groupItems.push(next);
          i += 1;
        }

        blocks.push({
          type: "sub_agent_group",
          groupId: `${groupItems[0].id}-${sourceSessionId}`,
          sourceSessionId,
          sourceSessionType: subAgentTypeBySessionId[sourceSessionId] ?? null,
          sourceSessionDesc: subAgentDescBySessionId[sourceSessionId] ?? null,
          items: groupItems,
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

  const activeGroupId =
    activeItemId === null ? null : (subAgentGroupIdByItemId.get(activeItemId) ?? null);

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

        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-neutral-200/80 bg-white/95 px-4 backdrop-blur sm:px-6">
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
            <div className="flex min-w-0 items-center gap-2 text-[14px] leading-5">
              <span className="truncate font-semibold text-neutral-800" title={sessionTitle}>
                {sessionTitle}
              </span>
              {workspacePath ? (
                <span
                  className="truncate font-mono text-[11px] leading-4 text-neutral-400"
                  title={workspacePath}
                >
                  {workspacePath}
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
            onClick={() => {
              void handleRefresh();
            }}
            title="Refresh session"
            aria-label="Refresh session"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
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
          <div className="mx-auto max-w-4xl space-y-5 px-4 py-8 sm:px-6">
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
                        const lastAssistantItem = [...block.items]
                          .reverse()
                          .find(
                            (item): item is AssistantTextItem =>
                              item.type === "assistant_text" &&
                              !item.isStreaming &&
                              item.content.trim().length > 0,
                          );
                        const resultPreview =
                          isFinished && lastAssistantItem
                            ? previewAssistantResult(lastAssistantItem.content)
                            : null;
                        return (
                          <div key={block.groupId} className="group/subagent flex min-w-0 gap-4">
                            <div className="min-w-0 flex-1 rounded-xl border border-neutral-200/80 bg-white">
                              <button
                                type="button"
                                onClick={() => {
                                  setCollapsedSubAgentGroups((prev) => ({
                                    ...prev,
                                    [block.groupId]: !collapsed,
                                  }));
                                }}
                                className="flex w-full cursor-pointer items-center gap-1.5 px-3.5 py-2.5 text-left"
                              >
                                <ChevronRight
                                  className={`h-3.5 w-3.5 text-neutral-300 transition-transform duration-150 ${collapsed ? "" : "rotate-90"}`}
                                />
                                <span className="whitespace-nowrap font-sans text-[14px] font-semibold text-neutral-700">
                                  {block.sourceSessionType
                                    ? `Agent(${block.sourceSessionType})`
                                    : "Agent"}
                                </span>
                                <span className="truncate text-sm text-neutral-600">
                                  {block.sourceSessionDesc ??
                                    `Sub Agent ${shortSessionId(block.sourceSessionId)}`}
                                </span>
                              </button>
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
                                                className="flex min-w-0 items-start gap-1.5 text-[12px]"
                                              >
                                                <span className="whitespace-nowrap font-sans text-neutral-500">
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
                                    return (
                                      <div
                                        key={item.id}
                                        ref={(el) => setItemRef(item.id, el)}
                                        className="group/row relative min-w-0"
                                      >
                                        <div
                                          className={`min-w-0 flex-1 rounded-xl bg-neutral-50/60 transition-shadow duration-150 ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
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
                <div ref={bottomRef} />
              </>
            ) : (
              <div className="flex min-h-[240px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-neutral-300" />
              </div>
            )}
          </div>
        </div>
      </div>
    </SearchProvider>
  );
}
