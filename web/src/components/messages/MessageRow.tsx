import type { RefCallback } from "react";

import type { MessageItem as MessageItemType } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { MessageItem } from "./MessageItem";
import { isCopyableAssistantText } from "./message-list-ui";

interface MessageRowProps {
  item: MessageItemType;
  variant: "main" | "subagent";
  workDir: string;
  isActive: boolean;
  copied: boolean;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  itemRef: RefCallback<HTMLDivElement>;
}

export function MessageRow({
  item,
  variant,
  workDir,
  isActive,
  copied,
  onCopy,
  itemRef,
}: MessageRowProps): JSX.Element {
  const canCopy = isCopyableAssistantText(item);
  const isUser = item.type === "user_message";
  const usesInlineToolLayout = variant === "subagent" && item.type === "tool_block";
  const compact = variant === "subagent";

  return (
    <div
      ref={itemRef}
      className={
        variant === "main"
          ? `group/row min-w-0 ${isUser ? "-mx-4 -mt-2.5 px-4 pt-2.5 sm:-mx-6 sm:px-6" : ""}`
          : "group/row relative min-w-0"
      }
    >
      <div
        className={
          variant === "main"
            ? `min-w-0 transition-shadow duration-150 ${isUser ? "" : "rounded-xl"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`
            : `min-w-0 flex-1 rounded-xl transition-shadow duration-150 ${usesInlineToolLayout ? "" : "bg-surface/60"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`
        }
      >
        <MessageItem item={item} compact={compact} workDir={workDir} />
        {canCopy ? (
          <div className="mt-1 flex justify-end">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => onCopy(item)}
                  className="cursor-pointer font-mono text-xs leading-none text-neutral-500 opacity-0 transition-opacity duration-150 hover:text-neutral-700 group-hover/row:opacity-100"
                  aria-label={copied ? "Copied" : "Copy"}
                >
                  {copied ? "[Copied]" : "[Copy]"}
                </button>
              </TooltipTrigger>
              <TooltipContent>{copied ? "Copied" : "Copy"}</TooltipContent>
            </Tooltip>
          </div>
        ) : null}
      </div>
    </div>
  );
}
