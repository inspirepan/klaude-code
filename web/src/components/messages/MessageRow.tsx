import type { RefCallback } from "react";

import { useT } from "@/i18n";
import type { MessageItem as MessageItemType } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { MessageItem } from "./MessageItem";
import { isCopyableAssistantText } from "./message-list-ui";

interface MessageRowProps {
  item: MessageItemType;
  workDir: string;
  isActive: boolean;
  copied: boolean;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  itemRef: RefCallback<HTMLDivElement>;
}

export function MessageRow({
  item,
  workDir,
  isActive,
  copied,
  onCopy,
  itemRef,
}: MessageRowProps): React.JSX.Element {
  const t = useT();
  const canCopy = isCopyableAssistantText(item);
  const isUser = item.type === "user_message";

  return (
    <div
      ref={itemRef}
      className={`group/row min-w-0 ${isUser ? "-mx-4 -mt-2.5 px-4 pt-2.5 sm:-mx-6 sm:px-6" : ""}`}
    >
      <div
        className={`min-w-0 transition-shadow duration-150 ${isUser ? "" : "rounded-lg"} ${isActive ? "ring-2 ring-amber-300/70 ring-offset-1" : ""}`}
      >
        <MessageItem item={item} workDir={workDir} />
        {canCopy ? (
          <div className="mt-2.5 flex justify-end">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => void onCopy(item)}
                  className="cursor-pointer font-mono text-sm leading-none text-neutral-500 opacity-0 transition-opacity duration-150 hover:text-neutral-700 group-hover/row:opacity-100"
                  aria-label={copied ? t("copy.copied") : t("copy.copy")}
                >
                  {copied ? t("copy.copiedButton") : t("copy.copyButton")}
                </button>
              </TooltipTrigger>
              <TooltipContent>{copied ? t("copy.copied") : t("copy.copy")}</TooltipContent>
            </Tooltip>
          </div>
        ) : null}
      </div>
    </div>
  );
}
