import type { RefCallback } from "react";

import type { MessageItem as MessageItemType } from "../../types/message";
import { MessageItem } from "./MessageItem";
import { isCopyableAssistantText } from "./message-list-ui";

interface MessageRowProps {
  item: MessageItemType;
  variant: "main" | "subagent";
  workDir: string;
  isActive: boolean;
  displayTime: string | null;
  copied: boolean;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  itemRef: RefCallback<HTMLDivElement>;
}

export function MessageRow({
  item,
  variant,
  workDir,
  isActive,
  displayTime,
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
          ? `group/row flex min-w-0 gap-4 ${isUser ? "sticky top-12 z-10 -mx-4 -mt-2.5 px-4 pt-2.5 sm:-mx-6 sm:px-6" : ""}`
          : "group/row relative min-w-0"
      }
    >
      <div
        className={
          variant === "main"
            ? `min-w-0 flex-1 transition-shadow duration-150 ${isUser ? "overflow-hidden rounded-[22px] shadow-sm" : "rounded-xl"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`
            : `min-w-0 flex-1 rounded-xl transition-shadow duration-150 ${usesInlineToolLayout ? "" : "bg-neutral-50/60"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`
        }
      >
        <MessageItem item={item} compact={compact} workDir={workDir} />
        {canCopy ? (
          <div className="mt-1 flex justify-end sm:hidden">
            <button
              type="button"
              onClick={() => onCopy(item)}
              className="cursor-pointer text-xs leading-none text-neutral-300 transition-colors duration-150 hover:text-neutral-500"
              title={copied ? "Copied" : "Copy"}
            >
              {copied ? "[Copied]" : "[Copy]"}
            </button>
          </div>
        ) : null}
      </div>
      <div
        className={
          variant === "main"
            ? "hidden shrink-0 flex-col items-end gap-1 whitespace-nowrap pt-0.5 text-right sm:flex"
            : "absolute left-[calc(100%+24px)] top-0 hidden w-[112px] flex-col items-end gap-1 whitespace-nowrap pt-0.5 text-right sm:flex"
        }
      >
        {displayTime ? (
          <span className="relative -top-0.5 select-none pb-1 text-xs tabular-nums leading-none text-neutral-300 opacity-0 transition-opacity duration-150 group-hover/row:opacity-100">
            {displayTime}
          </span>
        ) : null}
        {canCopy ? (
          <button
            type="button"
            onClick={() => onCopy(item)}
            className="cursor-pointer text-xs leading-none text-neutral-300 opacity-0 transition-opacity duration-150 hover:text-neutral-500 group-hover/row:opacity-100"
            title={copied ? "Copied" : "Copy"}
          >
            {copied ? "[Copied]" : "[Copy]"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
