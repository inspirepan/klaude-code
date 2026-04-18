import { type ReactNode, useMemo } from "react";

import { useT } from "@/i18n";
import type { MessageItem as MessageItemType, DeveloperMessageItem } from "@/types/message";
import type { CollapseGroupEntry, SectionSubAgentBlock } from "./message-sections";
import { ChevronRight } from "lucide-react";
import { COLLAPSE_RAIL_GRID_CLASS_NAME, CollapseRailPanel } from "./CollapseRail";
import { MessageRow } from "./MessageRow";
import { DeveloperMessage } from "./DeveloperMessage";

interface CollapseGroupBlockProps {
  entries: CollapseGroupEntry[];
  collapsed: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
  renderSubAgent?: (entry: SectionSubAgentBlock) => ReactNode;
}

export function CollapseGroupBlock({
  entries,
  collapsed,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
  renderSubAgent,
}: CollapseGroupBlockProps): React.JSX.Element {
  const t = useT();
  const items = useMemo(
    () => entries.filter((e): e is MessageItemType => e.type !== "sub_agent_group"),
    [entries],
  );
  const totalCount = useMemo(() => {
    const toolCount = items.filter((item) => item.type === "tool_block").length;
    const agentCount = entries.filter(
      (e): e is SectionSubAgentBlock => e.type === "sub_agent_group",
    ).length;
    return toolCount + agentCount;
  }, [items, entries]);

  // Group consecutive entries for rendering: dev messages merge, sub-agents render via callback
  type RenderBlock =
    | { kind: "dev"; items: DeveloperMessageItem[] }
    | { kind: "other"; item: MessageItemType }
    | { kind: "sub_agent"; entry: SectionSubAgentBlock };

  const renderBlocks = useMemo((): RenderBlock[] => {
    const result: RenderBlock[] = [];
    for (const entry of entries) {
      if (entry.type === "sub_agent_group") {
        result.push({ kind: "sub_agent", entry });
        continue;
      }
      if (entry.type === "developer_message") {
        const last = result.at(-1);
        if (last?.kind === "dev") {
          last.items.push(entry);
        } else {
          result.push({ kind: "dev", items: [entry] });
        }
      } else {
        result.push({ kind: "other", item: entry });
      }
    }
    return result;
  }, [entries]);

  return (
    <div className="rounded-lg border border-stone-200/50 bg-[#e6eee2]/40 px-4 py-1 shadow-[0_1px_3px_0_rgba(70,100,60,0.07),_0_1px_2px_-1px_rgba(70,100,60,0.05)]">
      <button
        type="button"
        onClick={onToggle}
        className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-center py-1.5 text-left text-sm leading-5`}
      >
        <span className="flex h-[1lh] items-center justify-center">
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 text-neutral-400 transition-transform duration-150 ease-out-strong ${!collapsed ? "rotate-90" : ""}`}
          />
        </span>
        <span className="flex min-w-0 items-center text-neutral-500">
          {totalCount === 0 ? t("collapse.thoughts") : t("collapse.toolsUsed")(totalCount)}
        </span>
      </button>
      <CollapseRailPanel open={!collapsed}>
        <div className="mt-1.5 min-w-0 pl-[22px]">
          <div className="min-w-0 space-y-3 pb-1">
            {renderBlocks.map((block, idx) => {
              if (block.kind === "dev") {
                return <DeveloperMessage key={`dev-${idx}`} items={block.items} />;
              }
              if (block.kind === "sub_agent") {
                return renderSubAgent ? renderSubAgent(block.entry) : null;
              }
              return (
                <MessageRow
                  key={block.item.id}
                  item={block.item}
                  workDir={workDir}
                  isActive={block.item.id === activeItemId}
                  copied={copiedItemId === block.item.id}
                  onCopy={onCopy}
                  setItemRef={setItemRef}
                />
              );
            })}
          </div>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
