import type { ToolBlockItem } from "../../types/message";
import { HighlightText } from "./HighlightText";
import { ToolRichResult } from "./ToolRichResult";

const RESULT_LINE_LIMIT = 15;

interface ToolBlockResultProps {
  item: ToolBlockItem;
  compact: boolean;
  open: boolean;
  hasRich: boolean;
  hideResultRail: boolean;
  hasResult: boolean;
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
  hideResultRail,
  hasResult,
  isEmptyResult,
  isError,
  showMore,
  onToggleShowMore,
}: ToolBlockResultProps): JSX.Element | null {
  if (!open) return null;

  const subTextClass = compact ? "text-[13px]" : "text-sm";
  const miniTextClass = compact ? "text-2xs" : "text-xs";

  return (
    <div className="col-span-2 mt-0.5 grid min-w-0 grid-cols-[16px_1fr] gap-x-1.5">
      <div className="flex justify-center">
        {hideResultRail ? null : <div className="w-px bg-neutral-200" />}
      </div>
      <div className="min-w-0">
        {hasRich ? (
          <div
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            <ToolRichResult item={item} compact={compact} />
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
              const displayed = truncated
                ? lines.slice(0, RESULT_LINE_LIMIT).join("\n")
                : item.result!;
              return (
                <>
                  <pre
                    className={`mt-0.5 ${subTextClass} whitespace-pre-wrap break-words font-mono leading-relaxed ${isError ? "text-red-700" : "text-neutral-400"}`}
                  >
                    <HighlightText>{displayed}</HighlightText>
                  </pre>
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
  );
}
