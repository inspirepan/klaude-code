import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ToolBlockItem } from "@/types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { FilePathContent } from "./FilePath";
import { toDisplayPath } from "./file-path-utils";
import { HighlightText } from "./HighlightText";

const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write"]);

function toPascalCase(name: string): string {
  return name
    .split("_")
    .filter((seg) => seg.length > 0)
    .map((seg) => seg.charAt(0).toUpperCase() + seg.slice(1))
    .join("");
}

interface ToolBlockHeaderProps {
  item: ToolBlockItem;
  detail: string;
  description: string;
  detailColor: string;
  workDir?: string;
  headerDetailTextClass: string;
  detailChipClass: string;
}

export function ToolBlockHeader({
  item,
  detail,
  description,
  detailColor,
  workDir,
  headerDetailTextClass,
  detailChipClass,
}: ToolBlockHeaderProps): React.JSX.Element {
  const isFilePath = FILE_PATH_TOOLS.has(item.toolName);

  let detailContent: React.JSX.Element | null = null;
  let detailClass = "";

  if (detail) {
    if (isFilePath) {
      const display = toDisplayPath(detail, workDir);
      detailContent = <FilePathContent display={display} />;
      detailClass = `font-mono ${headerDetailTextClass}`;
    } else {
      detailContent = <HighlightText>{detail}</HighlightText>;
      detailClass = `font-mono ${headerDetailTextClass} ${detailChipClass} ${detailColor}`;
    }
  }

  return (
    <div className="grid min-w-0 grid-cols-[auto,minmax(0,1fr)] items-start gap-x-1.5 gap-y-1 font-sans text-sm leading-5">
      <span
        className={cn(
          "shrink-0 whitespace-nowrap font-semibold text-neutral-800",
          item.isStreaming && "text-shimmer",
        )}
      >
        {toPascalCase(item.toolName)}
      </span>
      {description ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="line-clamp-2 min-w-0 text-pretty font-sans text-sm italic text-slate-500">
              <HighlightText>{description}</HighlightText>
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-lg p-0">
            <ScrollArea className="w-full" viewportClassName="max-h-[60vh]" type="auto">
              <div className="whitespace-pre-wrap break-words px-3 py-2 text-sm text-neutral-800">
                {description}
              </div>
            </ScrollArea>
          </TooltipContent>
        </Tooltip>
      ) : detailContent ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={`min-w-0 truncate ${detailClass}`}>{detailContent}</span>
          </TooltipTrigger>
          <TooltipContent className="max-w-lg p-0 font-mono">
            <ScrollArea className="w-full" viewportClassName="max-h-[60vh]" type="auto">
              <div className="whitespace-pre-wrap break-all px-3 py-1.5">{detail}</div>
            </ScrollArea>
          </TooltipContent>
        </Tooltip>
      ) : null}
      {description && detailContent ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={`col-start-2 min-w-0 truncate ${detailClass}`}>{detailContent}</span>
          </TooltipTrigger>
          <TooltipContent className="max-w-lg p-0 font-mono">
            <ScrollArea className="w-full" viewportClassName="max-h-[60vh]" type="auto">
              <div className="whitespace-pre-wrap break-all px-3 py-1.5">{detail}</div>
            </ScrollArea>
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
