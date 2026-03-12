import type { ToolBlockItem } from "../../types/message";
import { FilePath } from "./FilePath";
import { HighlightText } from "./HighlightText";

const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write"]);

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
      {/* Col 1: toggle indicator */}
      <div className="flex flex-col items-center">
        <span className={`mt-0.5 font-mono text-xs text-neutral-300 ${!expandable ? "opacity-0" : ""}`}>
          {open ? "[-]" : "[+]"}
        </span>
      </div>

      {/* Col 2: tool name + detail */}
      <div className="flex min-w-0 items-start gap-1.5">
        <span className="whitespace-nowrap font-mono font-normal text-neutral-500">
          {item.toolName}
        </span>
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
          <span className="mt-1 h-3 w-3 shrink-0 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
        ) : null}
      </div>
    </>
  );
}
