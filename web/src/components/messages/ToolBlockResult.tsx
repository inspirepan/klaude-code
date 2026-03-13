import type { ToolBlockItem } from "../../types/message";
import { HighlightText } from "./HighlightText";
import { ToolRichResult } from "./ToolRichResult";

const RESULT_LINE_LIMIT = 15;

interface ToolBlockResultProps {
  item: ToolBlockItem;
  compact: boolean;
  open: boolean;
  hasRich: boolean;
  hasResult: boolean;
  hasStreamingContent: boolean;
  streamingContent: string;
  isEmptyResult: boolean;
  isError: boolean;
  showMore: boolean;
  onToggleShowMore: () => void;
}

export function ToolBlockResult({
  item,
  compact,
  open,
  hasRich,
  hasResult,
  hasStreamingContent,
  streamingContent,
  isEmptyResult,
  isError,
  showMore,
  onToggleShowMore,
}: ToolBlockResultProps): JSX.Element | null {
  const subTextClass = "text-sm";
  const miniTextClass = compact ? "text-2xs" : "text-xs";
  const resultLineClass = "block max-w-full overflow-hidden text-ellipsis whitespace-pre";

  return (
    <div
      className="col-span-2 grid transition-[grid-template-rows,opacity] duration-200 ease-in-out"
      style={{ gridTemplateRows: open ? "1fr" : "0fr", opacity: open ? 1 : 0 }}
    >
      <div className="min-w-0 overflow-hidden">
        <div className="mt-0.5 min-w-0 pl-6">
          {hasRich ? (
            <div
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              <ToolRichResult item={item} compact={compact} />
            </div>
          ) : hasStreamingContent ? (
            <div
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              <div className={`mt-0.5 ${subTextClass} font-mono leading-relaxed text-neutral-400`}>
                {streamingContent.split("\n").map((line, index) => (
                  <div key={index} className={resultLineClass}>
                    {line || " "}
                  </div>
                ))}
              </div>
            </div>
          ) : hasResult ? (
            <div
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              {(() => {
                const lines = item.result!.split("\n");
                const truncated = !showMore && lines.length > RESULT_LINE_LIMIT;
                const displayedLines = truncated ? lines.slice(0, RESULT_LINE_LIMIT) : lines;
                return (
                  <>
                    <div
                      className={`mt-0.5 ${subTextClass} font-mono leading-relaxed ${isError ? "text-red-700" : "text-neutral-400"}`}
                    >
                      {displayedLines.map((line, index) => (
                        <div key={index} className={resultLineClass}>
                          <HighlightText>{line || " "}</HighlightText>
                        </div>
                      ))}
                    </div>
                    {lines.length > RESULT_LINE_LIMIT ? (
                      <button
                        type="button"
                        onClick={onToggleShowMore}
                        className={`mt-0.5 ${miniTextClass} cursor-pointer font-sans text-neutral-400 transition-colors hover:text-neutral-600`}
                      >
                        {showMore
                          ? "Show less"
                          : `Show more (${lines.length - RESULT_LINE_LIMIT} lines)`}
                      </button>
                    ) : null}
                  </>
                );
              })()}
            </div>
          ) : isEmptyResult ? (
            <div className={`mt-0.5 ${subTextClass} font-mono text-neutral-400`}>(no content)</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
