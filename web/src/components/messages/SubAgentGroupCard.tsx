import { ChevronRight } from "lucide-react";

import type { SessionStatusState } from "../../stores/event-reducer";
import type { AssistantTextItem, MessageItem as MessageItemType } from "../../types/message";
import { MessageRow } from "./MessageRow";
import { SubAgentCollapsedPreview } from "./SubAgentCollapsedPreview";
import { SubAgentStatusSummary } from "./SubAgentStatusSummary";
import {
  formatSubAgentTypeLabel,
  formatTime,
  getSessionActivityText,
  getSessionMetaRows,
  getSessionSummaryParts,
  isToolBlock,
  previewAssistantResult,
  shortSessionId,
} from "./message-list-ui";

interface SubAgentGroupCardProps {
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  items: MessageItemType[];
  collapsed: boolean;
  status: SessionStatusState | null;
  isFinished: boolean;
  nowSeconds: number;
  activeItemId: string | null;
  copiedItemId: string | null;
  metaOpen: boolean;
  workDir: string;
  onToggleCollapsed: () => void;
  onMetaOpenChange: (open: boolean) => void;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

export function SubAgentGroupCard({
  sourceSessionId,
  sourceSessionType,
  sourceSessionDesc,
  items,
  collapsed,
  status,
  isFinished,
  nowSeconds,
  activeItemId,
  copiedItemId,
  metaOpen,
  workDir,
  onToggleCollapsed,
  onMetaOpenChange,
  onCopy,
  setItemRef,
}: SubAgentGroupCardProps): JSX.Element {
  const toolItems = items.filter(isToolBlock);
  const previewTools = toolItems.slice(-3);
  const moreToolsCount = Math.max(0, toolItems.length - previewTools.length);
  const activityText = getSessionActivityText(status);
  const summaryParts = getSessionSummaryParts(status, nowSeconds);
  const metaRows = getSessionMetaRows(status, nowSeconds);
  const lastAssistantItem = [...items]
    .reverse()
    .find(
      (item): item is AssistantTextItem =>
        item.type === "assistant_text" && item.content.trim().length > 0,
    );
  const lastCompletedAssistantItem = [...items]
    .reverse()
    .find(
      (item): item is AssistantTextItem =>
        item.type === "assistant_text" && !item.isStreaming && item.content.trim().length > 0,
    );
  const resultPreview =
    isFinished && lastCompletedAssistantItem
      ? previewAssistantResult(lastCompletedAssistantItem.content)
      : null;
  const streamingPreview =
    !isFinished && lastAssistantItem ? previewAssistantResult(lastAssistantItem.content) : null;

  return (
    <div className="group/subagent flex min-w-0 gap-4">
      <div className="min-w-0 flex-1 rounded-2xl border border-neutral-200/80 bg-white shadow-sm shadow-neutral-200/40">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="flex w-full cursor-pointer items-center gap-2 px-4 py-3 text-left"
        >
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 text-neutral-300 transition-transform duration-150 ${collapsed ? "" : "rotate-90"}`}
          />
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="whitespace-nowrap text-sm font-semibold text-neutral-800">
              {formatSubAgentTypeLabel(sourceSessionType)}
            </span>
            <span className="truncate text-sm text-neutral-600">
              {sourceSessionDesc ?? `Sub Agent ${shortSessionId(sourceSessionId)}`}
            </span>
          </div>
        </button>
        <SubAgentStatusSummary
          activityText={activityText}
          summaryParts={summaryParts}
          metaRows={metaRows}
          metaOpen={metaOpen}
          onMetaOpenChange={onMetaOpenChange}
        />
        {collapsed ? (
          <SubAgentCollapsedPreview
            isFinished={isFinished}
            toolItems={toolItems}
            previewTools={previewTools}
            moreToolsCount={moreToolsCount}
            resultPreview={resultPreview}
            streamingPreview={streamingPreview}
          />
        ) : (
          <div className="space-y-5 px-3.5 pb-3.5 pt-0.5">
            {items.map((item, index) => {
              const time = formatTime(item.timestamp);
              const prevTime = index > 0 ? formatTime(items[index - 1]!.timestamp) : null;
              const displayTime = time && time !== prevTime ? time : null;
              return (
                <MessageRow
                  key={item.id}
                  item={item}
                  variant="subagent"
                  workDir={workDir}
                  isActive={item.id === activeItemId}
                  displayTime={displayTime}
                  copied={copiedItemId === item.id}
                  onCopy={onCopy}
                  itemRef={(el) => {
                    setItemRef(item.id, el);
                  }}
                />
              );
            })}
          </div>
        )}
      </div>
      <div className="hidden w-[112px] shrink-0 sm:block" />
    </div>
  );
}
