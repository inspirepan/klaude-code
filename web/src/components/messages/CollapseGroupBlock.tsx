import type { MessageItem as MessageItemType } from "../../types/message";
import { MessageRow } from "./MessageRow";

interface CollapseGroupBlockProps {
  items: MessageItemType[];
  collapsed: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

export function CollapseGroupBlock({
  items,
  collapsed,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
}: CollapseGroupBlockProps): JSX.Element {
  const label = `${items.length} step${items.length === 1 ? "" : "s"}`;

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-1.5 py-0.5 text-left text-sm text-neutral-400 transition-colors hover:text-neutral-600"
      >
        <span className="font-mono text-xs">{collapsed ? "[+]" : "[-]"}</span>
        <span>{label}</span>
      </button>
      {!collapsed ? (
        <div className="mt-3 space-y-5">
          {items.map((item) => (
            <MessageRow
              key={item.id}
              item={item}
              variant="main"
              workDir={workDir}
              isActive={item.id === activeItemId}
              copied={copiedItemId === item.id}
              onCopy={onCopy}
              itemRef={(el: HTMLDivElement | null) => setItemRef(item.id, el)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
