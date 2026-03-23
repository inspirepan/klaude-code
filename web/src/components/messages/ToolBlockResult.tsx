import { useT } from "@/i18n";
import type { ToolBlockItem } from "../../types/message";
import { CollapseRailPanel } from "./CollapseRail";
import { HighlightText } from "./HighlightText";
import { ToolRichResult } from "./ToolRichResult";

const RESULT_LINE_LIMIT = 5;
const STREAMING_LINE_LIMIT = 5;

interface ToolBlockResultProps {
  item: ToolBlockItem;
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
  const t = useT();
  const subTextClass = "text-base";
  const miniTextClass = "text-sm";
  const resultLineClass = "block max-w-full overflow-hidden text-ellipsis whitespace-pre";

  return (
    <CollapseRailPanel open={open}>
      <div className="mt-0.5 min-w-0">
          {hasRich ? (
            <div
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              <ToolRichResult item={item} />
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
                  const lineClass = `${resultLineClass} stream-fade-in`;
                  if (lines.length > STREAMING_LINE_LIMIT * 2) {
                    const headLines = lines.slice(0, STREAMING_LINE_LIMIT);
                    const tailLines = lines.slice(-STREAMING_LINE_LIMIT);
                    const hiddenCount = lines.length - STREAMING_LINE_LIMIT * 2;
                    return (
                      <>
                        {headLines.map((line, index) => (
                          <div key={index} className={lineClass}>
                            {line || " "}
                          </div>
                        ))}
                        <div
                          className={`my-0.5 ${miniTextClass} cursor-default font-sans text-neutral-500`}
                        >
                          {t("toolResult.linesHidden")(hiddenCount)}
                        </div>
                        {tailLines.map((line, index) => (
                          <div key={`tail-${index}`} className={lineClass}>
                            {line || " "}
                          </div>
                        ))}
                      </>
                    );
                  }
                  return lines.map((line, index) => (
                    <div key={index} className={lineClass}>
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
                          ? t("toolResult.showLess")
                          : t("toolResult.showMore")(lines.length - RESULT_LINE_LIMIT)}
                      </button>
                    ) : null}
                  </>
                );
              })()}
            </div>
          ) : isEmptyResult ? (
            <div className={`mt-0.5 ${subTextClass} font-mono text-neutral-500`}>
              {t("toolResult.noContent")}
            </div>
          ) : null}
      </div>
    </CollapseRailPanel>
  );
}
