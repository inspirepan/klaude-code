import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Loader2, ChevronUp } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import type { MessageItem as MessageItemType, UserMessageItem, ItemTimestamp } from "../../types/message";
import { MessageItem } from "./MessageItem";

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
  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (isToday(date)) return time;
  const day = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${day} ${time}`;
}

export function MessageList({ sessionId }: MessageListProps): JSX.Element {
  const items = useMessageStore((state) => state.messagesBySessionId[sessionId] ?? EMPTY_ITEMS);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const itemRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const [stickyMsg, setStickyMsg] = useState<StickyUserMessage | null>(null);

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
        <Loader2 className="w-5 h-5 text-zinc-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 relative">
      {stickyMsg ? (
        <button
          type="button"
          onClick={scrollToOrigin}
          className="absolute top-0 left-0 right-0 z-10 border-b border-zinc-100 bg-white/90 backdrop-blur-sm cursor-pointer hover:bg-zinc-50/90 transition-colors"
        >
          <div className="max-w-3xl mx-auto px-4 sm:px-6 py-2 flex items-center gap-2">
            <ChevronUp className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
            <span className="text-sm text-zinc-500 truncate">{stickyMsg.item.content}</span>
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
            return (
              <div
                key={item.id}
                ref={(el) => {
                  if (item.type === "user_message") setItemRef(item.id, el);
                }}
                className="group/row flex gap-4 min-w-0"
              >
                <div className="flex-1 min-w-0">
                  <MessageItem item={item} />
                </div>
                <div className="hidden sm:block w-16 shrink-0 pt-1 text-right">
                  {time ? (
                    <span className="text-[11px] tabular-nums text-zinc-300 opacity-0 group-hover/row:opacity-100 transition-opacity duration-150 select-none">
                      {time}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
