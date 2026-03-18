import { Loader } from "lucide-react";
import type { ToolBlockItem } from "../../types/message";
import { CollapseRailMarker } from "./CollapseRail";
import { FilePath } from "./FilePath";
import { HighlightText } from "./HighlightText";

const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write"]);

interface ToolBlockHeaderProps {
  item: ToolBlockItem;
  expandable: boolean;
  open: boolean;
  detailExpanded: boolean;
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
  detailExpanded,
  detail,
  detailColor,
  workDir,
  headerDetailTextClass,
  detailChipClass,
}: ToolBlockHeaderProps): JSX.Element {
  const isBash = item.toolName === "Bash";

  return (
    <>
      <CollapseRailMarker open={open} expandable={expandable} indicatorClassName="mt-1" />

      {/* Col 2: tool name + detail */}
      <div className="flex min-w-0 items-baseline gap-1.5">
        <span className="whitespace-nowrap font-mono font-semibold text-neutral-600">
          {item.toolName}
        </span>
        {detail ? (
          FILE_PATH_TOOLS.has(item.toolName) ? (
            <FilePath
              path={detail}
              expanded={detailExpanded}
              workDir={workDir}
              className={headerDetailTextClass}
            />
          ) : isBash ? (
            <code
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${detailExpanded ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </code>
          ) : (
            <span
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${detailExpanded ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </span>
          )
        ) : null}
        {item.isStreaming ? (
          <Loader className="mt-1 h-3 w-3 shrink-0 animate-spin text-neutral-500" />
        ) : null}
      </div>
    </>
  );
}
