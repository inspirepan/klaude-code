import { Copy, Check } from "lucide-react";
import { memo, useCallback } from "react";

import { useT } from "@/i18n";
import type { MessageItem as MessageItemType } from "@/types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";
import { MessageItem } from "./MessageItem";
import { isCopyableAssistantText } from "./message-list-ui";

interface MessageRowProps {
  item: MessageItemType;
  workDir: string;
  isActive: boolean;
  copied: boolean;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

function MessageRowInner({
  item,
  workDir,
  isActive,
  copied,
  onCopy,
  setItemRef,
}: MessageRowProps): React.JSX.Element {
  const t = useT();
  const canCopy = isCopyableAssistantText(item);
  const isUser = item.type === "user_message";
  const isAssistantText = item.type === "assistant_text";
  const handleItemRef = useCallback(
    (el: HTMLDivElement | null) => {
      setItemRef(item.id, el);
    },
    [item.id, setItemRef],
  );
  const handleCopy = useCallback(() => {
    void onCopy(item);
  }, [item, onCopy]);

  if (isAssistantText) {
    return (
      <div ref={handleItemRef} className="group/row min-w-0">
        <div
          className={`grid min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start rounded-lg border border-stone-200/50 bg-[#f8f8f6] shadow-[0_1px_3px_0_rgba(107,76,44,0.07),_0_1px_2px_-1px_rgba(107,76,44,0.05)] px-4 py-2 transition-shadow duration-150 ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
        >
          <span className="relative flex h-[1lh] items-center justify-center leading-[1.75]">
            <span
              className={`absolute inline-flex h-2 w-2 rounded-full bg-[#2e140c] transition-opacity duration-150 ${canCopy ? "group-hover/row:opacity-0" : ""} ${copied ? "opacity-0" : "opacity-100"}`}
              aria-hidden="true"
            />
            {canCopy ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className={`absolute cursor-pointer transition-opacity duration-150 ${copied ? "opacity-100" : "opacity-0 group-hover/row:opacity-100"}`}
                    aria-label={copied ? t("copy.copied") : t("copy.copy")}
                  >
                    {copied ? (
                      <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    ) : (
                      <Copy className="h-3.5 w-3.5 shrink-0 text-neutral-400 transition-colors hover:text-neutral-600" />
                    )}
                  </button>
                </TooltipTrigger>
                <TooltipContent>{copied ? t("copy.copied") : t("copy.copy")}</TooltipContent>
              </Tooltip>
            ) : null}
          </span>
          <div className="min-w-0">
            <MessageItem item={item} workDir={workDir} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={handleItemRef}
      className={`group/row min-w-0 ${isUser ? "-mx-4 -mt-2.5 px-4 pt-2.5 sm:-mx-6 sm:px-6" : ""}`}
    >
      <div
        className={`min-w-0 transition-shadow duration-150 ${isUser ? "" : "rounded-lg"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
      >
        <MessageItem item={item} workDir={workDir} />
      </div>
    </div>
  );
}

export const MessageRow = memo(
  MessageRowInner,
  (prev, next) =>
    prev.item === next.item &&
    prev.workDir === next.workDir &&
    prev.isActive === next.isActive &&
    prev.copied === next.copied &&
    prev.onCopy === next.onCopy &&
    prev.setItemRef === next.setItemRef,
);
