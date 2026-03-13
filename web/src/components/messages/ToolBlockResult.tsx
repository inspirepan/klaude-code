import { useLayoutEffect, useRef } from "react";

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
  const containerRef = useRef<HTMLDivElement>(null);
  const previousHeightRef = useRef<number | null>(null);
  const wasStreamingRef = useRef(item.isStreaming);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const currentHeight = element.getBoundingClientRect().height;
    const previousHeight = previousHeightRef.current;
    const justCompleted = wasStreamingRef.current && !item.isStreaming;

    if (justCompleted && open && previousHeight !== null && currentHeight > previousHeight) {
      const scrollContainer = element.closest<HTMLElement>(
        "[data-message-scroll-container='true']",
      );
      if (scrollContainer) {
        const blockRect = element.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const isVisible =
          blockRect.bottom > containerRect.top && blockRect.top < containerRect.bottom;
        if (isVisible) {
          scrollContainer.scrollTop += currentHeight - previousHeight;
        }
      }
    }

    previousHeightRef.current = currentHeight;
    wasStreamingRef.current = item.isStreaming;
  }, [item.isStreaming, item.result, item.resultStatus, item.uiExtra, open]);

  return (
    <div
      ref={containerRef}
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
              <div className={`mt-0.5 ${subTextClass} font-mono leading-relaxed text-neutral-500`}>
                {(() => {
                  const lines = streamingContent.split("\n");
                  if (lines.length > RESULT_LINE_LIMIT * 2) {
                    const headLines = lines.slice(0, RESULT_LINE_LIMIT);
                    const tailLines = lines.slice(-RESULT_LINE_LIMIT);
                    const hiddenCount = lines.length - RESULT_LINE_LIMIT * 2;
                    return (
                      <>
                        {headLines.map((line, index) => (
                          <div key={index} className={resultLineClass}>
                            {line || " "}
                          </div>
                        ))}
                        <div
                          className={`my-0.5 ${miniTextClass} cursor-default font-sans text-neutral-400`}
                        >
                          {`··· ${hiddenCount} lines hidden ···`}
                        </div>
                        {tailLines.map((line, index) => (
                          <div key={`tail-${index}`} className={resultLineClass}>
                            {line || " "}
                          </div>
                        ))}
                      </>
                    );
                  }
                  return lines.map((line, index) => (
                    <div key={index} className={resultLineClass}>
                      {line || " "}
                    </div>
                  ));
                })()}
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
                      className={`mt-0.5 ${subTextClass} font-mono leading-relaxed ${isError ? "text-red-700" : "text-neutral-500"}`}
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
                        className={`mt-0.5 ${miniTextClass} cursor-pointer font-sans text-neutral-500 transition-colors hover:text-neutral-700`}
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
            <div className={`mt-0.5 ${subTextClass} font-mono text-neutral-500`}>(no content)</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
