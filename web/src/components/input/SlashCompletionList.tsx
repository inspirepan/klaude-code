import { useEffect, useRef } from "react";
import { CommandListPanel, CommandListScroll, CommandListItem } from "@/components/ui/command-list";

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
    <CommandListPanel
      className={`absolute left-0 right-0 z-20 shadow-float ${dropUp ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}
    >
      <CommandListScroll ref={listRef}>
        {items.map((item, index) => (
          <CommandListItem
            key={item.insertText}
            data-slash-completion={item.insertText}
            highlighted={index === highlightIndex}
            onPointerEnter={() => onHighlightIndexChange(index)}
            onClick={() => onSelect(item)}
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium text-neutral-800">
                {item.kind === "command" ? `/${item.name}` : `skill:${item.name}`}
              </span>
              <span className="ml-2 text-neutral-500">{item.description}</span>
            </span>
          </CommandListItem>
        ))}
      </CommandListScroll>
    </CommandListPanel>
  );
}
