import { Loader } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ToolBlockItem } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { CollapseRailMarker } from "./CollapseRail";
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

  const detailChip = detail ? (
    FILE_PATH_TOOLS.has(item.toolName) ? (
      <FilePath path={detail} workDir={workDir} className={headerDetailTextClass} />
    ) : isBash ? (
      <code
        className={`inline-block max-w-full truncate ${headerDetailTextClass} ${detailChipClass} ${detailColor}`}
      >
        <HighlightText>{detail}</HighlightText>
      </code>
    ) : (
      <span
        className={`inline-block max-w-full truncate ${headerDetailTextClass} ${detailChipClass} ${detailColor}`}
      >
        <HighlightText>{detail}</HighlightText>
      </span>
    )
  ) : null;

  return (
    <>
      <CollapseRailMarker open={open} expandable={expandable} indicatorClassName="mt-1" />

      {/* Col 2: tool name + detail */}
      <div className="flex min-h-6 min-w-0 items-center gap-1.5">
        <span className="whitespace-nowrap font-mono font-semibold text-neutral-600">
          {item.toolName}
        </span>
        {detailChip ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="min-w-0">{detailChip}</span>
            </TooltipTrigger>
            <TooltipContent className="max-w-lg p-0 font-mono">
              <ScrollArea className="w-full" viewportClassName="max-h-[60vh]" type="auto">
                <div className="whitespace-pre-wrap break-all px-3 py-1.5">{detail}</div>
              </ScrollArea>
            </TooltipContent>
          </Tooltip>
        ) : null}
        {item.isStreaming ? (
          <Loader className="h-3 w-3 shrink-0 animate-spin text-neutral-500" />
        ) : null}
      </div>
    </>
  );
}
