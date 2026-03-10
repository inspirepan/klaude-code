import { ChevronRight } from "lucide-react";

import type { ToolBlockItem } from "../../types/message";
import { FilePath } from "./FilePath";
import { HighlightText } from "./HighlightText";

const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write", "Glob", "Grep"]);

interface ToolBlockHeaderProps {
  item: ToolBlockItem;
  expandable: boolean;
  open: boolean;
  detail: string;
  detailColor: string;
  workDir?: string;
  headerDetailTextClass: string;
  detailChipClass: string;
}

export function ToolBlockHeader({
  item,
  expandable,
  open,
  detail,
  detailColor,
  workDir,
  headerDetailTextClass,
  detailChipClass,
}: ToolBlockHeaderProps): JSX.Element {
  const isBash = item.toolName === "Bash";

  return (
    <>
      <div className="flex items-center gap-1.5 self-stretch">
        <div className={`flex flex-col items-center${open ? "self-stretch" : ""}`}>
          <ChevronRight
            className={`h-4 w-4 shrink-0 text-neutral-300 transition-transform duration-150 ${open ? "rotate-90" : ""} ${!expandable ? "opacity-0" : ""}`}
          />
          {open ? <div className="mt-1 w-px flex-1 bg-neutral-200" /> : null}
        </div>
        <span className="whitespace-nowrap font-sans font-normal text-neutral-500">
          {item.toolName}
        </span>
      </div>

      <div className="flex min-h-[22px] min-w-0 items-center gap-1.5">
        {detail ? (
          FILE_PATH_TOOLS.has(item.toolName) ? (
            <FilePath
              path={detail}
              expanded={open}
              workDir={workDir}
              className={headerDetailTextClass}
            />
          ) : isBash ? (
            <code
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </code>
          ) : (
            <span
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </span>
          )
        ) : null}
        {item.isStreaming ? (
          <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
        ) : null}
      </div>
    </>
  );
}
