import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";

export interface SlashCompletionItem {
  /** "command" for built-in commands, "skill" for loaded skills. */
  kind: "command" | "skill";
  /** Display name (e.g. "compact", "tmux-test"). */
  name: string;
  /** Short description shown as secondary text. */
  description: string;
  /** For skills: "project" | "user" | "system". Unused for commands. */
  location?: string;
  /** Full text to insert when selected (e.g. "/compact ", "/skill:tmux-test "). */
  insertText: string;
}

interface SlashCompletionListProps {
  items: SlashCompletionItem[];
  highlightIndex: number;
  onHighlightIndexChange: (index: number) => void;
  onSelect: (item: SlashCompletionItem) => void;
  dropUp?: boolean;
}

export function SlashCompletionList({
  items,
  highlightIndex,
  onHighlightIndexChange,
  onSelect,
  dropUp = true,
}: SlashCompletionListProps): JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const item = items[highlightIndex];
    if (!item || !listRef.current) {
      return;
    }
    const el = listRef.current.querySelector(
      `[data-slash-completion="${CSS.escape(item.insertText)}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, items]);

  return (
    <div className={`absolute left-0 right-0 z-20 overflow-hidden rounded-lg border border-neutral-200/80 bg-white shadow-[0_4px_16px_rgba(0,0,0,0.08)] ${dropUp ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}>
      <ScrollArea ref={listRef} className="w-full pb-1.5 pt-2" viewportClassName="max-h-72" type="hover">
        {items.map((item, index) => {
          const highlighted = index === highlightIndex;
          return (
            <button
              key={item.insertText}
              data-slash-completion={item.insertText}
              type="button"
              className={[
                "ml-2 mr-2.5 flex w-[calc(100%-1.125rem)] items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors",
                highlighted ? "bg-muted text-neutral-900" : "text-neutral-600 hover:bg-surface",
              ].join(" ")}
              onMouseDown={(event) => {
                event.preventDefault();
              }}
              onPointerEnter={() => {
                onHighlightIndexChange(index);
              }}
              onClick={() => {
                onSelect(item);
              }}
            >
              <span className="min-w-0 flex-1 truncate text-base leading-6">
                <span className="text-neutral-800">
                  {item.kind === "command" ? `/${item.name}` : `skill:${item.name}`}
                </span>
                <span className="ml-2 text-neutral-400">{item.description}</span>
              </span>
            </button>
          );
        })}
      </ScrollArea>
    </div>
  );
}
