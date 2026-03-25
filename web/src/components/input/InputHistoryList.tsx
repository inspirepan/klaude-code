import { useEffect, useRef } from "react";
import { History } from "lucide-react";
import { CommandListPanel, CommandListScroll, CommandListItem } from "@/components/ui/command-list";
import { useT } from "@/i18n";

interface InputHistoryListProps {
  items: string[];
  highlightIndex: number;
  onHighlightIndexChange: (index: number) => void;
  onSelect: (entry: string) => void;
}

export function InputHistoryList({
  items,
  highlightIndex,
  onHighlightIndexChange,
  onSelect,
}: InputHistoryListProps): React.JSX.Element {
  const t = useT();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!listRef.current || highlightIndex < 0 || highlightIndex >= items.length) {
      return;
    }
    const el = listRef.current.querySelector(`[data-history-index="${highlightIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, items.length]);

  return (
    <CommandListPanel className="absolute bottom-full left-0 right-0 z-20 mb-1.5 shadow-float">
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-1.5 text-xs text-neutral-500">
        <span className="flex items-center gap-1.5">
          <History className="h-3 w-3 shrink-0" />
          <span>{t("composer.inputHistory")}</span>
        </span>
        <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface px-1 text-[11px] font-medium leading-[18px] text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
          Esc
        </kbd>
      </div>
      <CommandListScroll ref={listRef} maxHeight="max-h-64">
        {items.map((entry, index) => (
          <CommandListItem
            key={index}
            data-history-index={index}
            highlighted={index === highlightIndex}
            onPointerEnter={() => {
              onHighlightIndexChange(index);
            }}
            onClick={() => {
              onSelect(entry);
            }}
          >
            <span className="min-w-0 flex-1 truncate">{entry}</span>
          </CommandListItem>
        ))}
      </CommandListScroll>
    </CommandListPanel>
  );
}
