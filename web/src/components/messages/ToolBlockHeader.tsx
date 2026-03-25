import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ToolBlockItem } from "@/types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { FilePathContent } from "./FilePath";
import { toDisplayPath } from "./file-path-utils";
import { HighlightText } from "./HighlightText";

const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write"]);

interface ToolBlockHeaderProps {
  item: ToolBlockItem;
  detail: string;
  detailColor: string;
  workDir?: string;
  headerDetailTextClass: string;
  detailChipClass: string;
}

export function ToolBlockHeader({
  item,
  detail,
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
      detailClass = `rounded bg-surface px-1.5 py-0.5 ${headerDetailTextClass}`;
    } else {
      detailContent = <HighlightText>{detail}</HighlightText>;
      detailClass = `${headerDetailTextClass} ${detailChipClass} ${detailColor}`;
    }
  }

  return (
    <div className="flex min-h-6 min-w-0 items-center gap-1.5 font-mono text-sm leading-5">
      <span
        className={cn(
          "shrink-0 whitespace-nowrap font-medium text-neutral-700",
          item.isStreaming && "text-shimmer",
        )}
      >
        {item.toolName}
      </span>
      {detailContent ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={`min-w-0 truncate ${detailClass}`} title={detail}>
              {detailContent}
            </span>
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
