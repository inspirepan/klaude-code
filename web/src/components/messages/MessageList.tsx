import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Loader2, ChevronUp } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import type {
  MessageItem as MessageItemType,
  UserMessageItem,
  ItemTimestamp,
  AssistantTextItem,
} from "../../types/message";
import { MessageItem } from "./MessageItem";
import { SearchBar } from "./SearchBar";
import { SearchProvider, type SearchState } from "./search-context";

const EMPTY_ITEMS: MessageItemType[] = [];

interface MessageListProps {
  sessionId: string;
}

interface StickyUserMessage {
  item: UserMessageItem;
  originId: string;
}

function isToday(date: Date): boolean {
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

function formatTime(ts: ItemTimestamp): string | null {
  if (ts === null) return null;
  const date = new Date(ts * 1000);
  const time = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const day = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${day} ${time}`;
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
  const items = useMessageStore((state) => state.messagesBySessionId[sessionId] ?? EMPTY_ITEMS);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const [stickyMsg, setStickyMsg] = useState<StickyUserMessage | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActiveIndex, setSearchActiveIndex] = useState(-1);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);
  const copyTimerRef = useRef(0);

  const searchMatchItemIds = useMemo(
    () => findMatchingItemIds(items, searchQuery),
    [items, searchQuery],
  );

  // Reset active index when matches change
  useEffect(() => {
    setSearchActiveIndex(searchMatchItemIds.length > 0 ? 0 : -1);
  }, [searchMatchItemIds]);

  const searchState = useMemo<SearchState>(
    () => ({ query: searchQuery, matchItemIds: searchMatchItemIds, activeIndex: searchActiveIndex }),
    [searchQuery, searchMatchItemIds, searchActiveIndex],
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
    if (searchActiveIndex < 0 || searchMatchItemIds.length === 0) return;
    const itemId = searchMatchItemIds[searchActiveIndex];
    if (!itemId) return;
    const el = itemRefsMap.current.get(itemId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [searchActiveIndex, searchMatchItemIds]);

  const handleSearchQueryChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleSearchNext = useCallback(() => {
    if (searchMatchItemIds.length === 0) return;
    setSearchActiveIndex((prev) => (prev + 1) % searchMatchItemIds.length);
  }, [searchMatchItemIds.length]);

  const handleSearchPrev = useCallback(() => {
    if (searchMatchItemIds.length === 0) return;
    setSearchActiveIndex((prev) => (prev - 1 + searchMatchItemIds.length) % searchMatchItemIds.length);
  }, [searchMatchItemIds.length]);

  const handleSearchClose = useCallback(() => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchActiveIndex(-1);
  }, []);

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

  const userMessages = useMemo(
    () => items.filter((i): i is UserMessageItem => i.type === "user_message"),
    [items],
  );

  // Restore scroll position when items first load for a session
  const hasItems = items.length > 0;
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
  }, [items.length]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    sessionStorage.setItem(`scroll-${sessionId}`, String(container.scrollTop));

    const containerTop = container.getBoundingClientRect().top;
    let lastAbove: UserMessageItem | null = null;

    for (const msg of userMessages) {
      const el = itemRefsMap.current.get(msg.id);
      if (!el) continue;
      const rect = el.getBoundingClientRect();
      if (rect.bottom < containerTop) {
        lastAbove = msg;
      }
    }

    if (lastAbove) {
      setStickyMsg((prev) =>
        prev?.originId === lastAbove.id ? prev : { item: lastAbove, originId: lastAbove.id },
      );
    } else {
      setStickyMsg((prev) => (prev === null ? prev : null));
    }
  }, [sessionId, userMessages]);

  const scrollToOrigin = useCallback(() => {
    if (!stickyMsg) return;
    const el = itemRefsMap.current.get(stickyMsg.originId);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [stickyMsg]);

  const setItemRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) {
      itemRefsMap.current.set(id, el);
    } else {
      itemRefsMap.current.delete(id);
    }
  }, []);

  if (items.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-neutral-300 animate-spin" />
      </div>
    );
  }

  const activeItemId = searchActiveIndex >= 0 ? searchMatchItemIds[searchActiveIndex] : null;

  return (
    <SearchProvider value={searchState}>
      <div className="flex-1 min-h-0 relative">
        {searchOpen ? (
          <SearchBar
            totalMatches={searchMatchItemIds.length}
            activeIndex={searchActiveIndex}
            onQueryChange={handleSearchQueryChange}
            onNext={handleSearchNext}
            onPrev={handleSearchPrev}
            onClose={handleSearchClose}
          />
        ) : null}

        {stickyMsg ? (
          <button
            type="button"
            onClick={scrollToOrigin}
            className="absolute top-0 left-0 right-0 z-10 border-b border-neutral-100 bg-white/90 backdrop-blur-sm cursor-pointer hover:bg-neutral-50/90 transition-colors"
          >
            <div className="max-w-3xl mx-auto px-4 sm:px-6 py-2 flex items-center gap-2">
              <ChevronUp className="w-3.5 h-3.5 text-neutral-400 shrink-0" />
              <span className="text-sm text-neutral-500 truncate">{stickyMsg.item.content}</span>
            </div>
          </button>
        ) : null}

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto overflow-x-hidden scrollbar-thin"
        >
          <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 space-y-5">
            {items.map((item) => {
              const time = formatTime(item.timestamp);
              const isActive = item.id === activeItemId;
              const canCopy = isCopyableAssistantText(item);
              const copied = copiedItemId === item.id;
              return (
                <div
                  key={item.id}
                  ref={(el) => setItemRef(item.id, el)}
                  className="group/row flex gap-4 min-w-0"
                >
                  <div className={`flex-1 min-w-0 transition-shadow duration-150 rounded-lg ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}>
                    <MessageItem item={item} />
                    {canCopy ? (
                      <div className="sm:hidden mt-1 flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleCopy(item)}
                          className="text-xs leading-none text-neutral-300 hover:text-neutral-500 transition-colors duration-150 cursor-pointer"
                          title={copied ? "Copied" : "Copy"}
                        >
                          {copied ? "[Copied]" : "[Copy]"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                  <div className="hidden sm:flex shrink-0 text-right whitespace-nowrap flex-col items-end gap-1 pt-0.5">
                    {time ? (
                      <span className="text-xs leading-none tabular-nums text-neutral-300 opacity-0 group-hover/row:opacity-100 transition-opacity duration-150 select-none relative -top-0.5 pb-1">
                        {time}
                      </span>
                    ) : null}
                    {canCopy ? (
                      <button
                        type="button"
                        onClick={() => handleCopy(item)}
                        className="text-xs leading-none text-neutral-300 hover:text-neutral-500 opacity-0 group-hover/row:opacity-100 transition-opacity duration-150 cursor-pointer"
                        title={copied ? "Copied" : "Copy"}
                      >
                        {copied ? "[Copied]" : "[Copy]"}
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>
    </SearchProvider>
  );
}
