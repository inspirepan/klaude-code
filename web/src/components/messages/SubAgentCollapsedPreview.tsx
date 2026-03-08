import type { PreviewText } from "./message-list-ui";
import { extractToolPreviewDetail } from "./message-list-ui";
import type { ToolBlockItem } from "../../types/message";

interface SubAgentCollapsedPreviewProps {
  isFinished: boolean;
  toolItems: ToolBlockItem[];
  previewTools: ToolBlockItem[];
  moreToolsCount: number;
  resultPreview: PreviewText | null;
  streamingPreview: PreviewText | null;
}

export function SubAgentCollapsedPreview({
  isFinished,
  toolItems,
  previewTools,
  moreToolsCount,
  resultPreview,
  streamingPreview,
}: SubAgentCollapsedPreviewProps): JSX.Element {
  return (
    <div className="px-3.5 pb-3.5 pt-0.5">
      {resultPreview ? (
        <>
          <div className="mb-1.5 text-xs text-neutral-400">{toolItems.length} tools</div>
          <div className="mt-2.5">
            <div className="relative overflow-hidden rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2">
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-neutral-500">
                {resultPreview.text}
              </pre>
              {resultPreview.hasMore ? (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-neutral-50/95 to-transparent" />
              ) : null}
            </div>
          </div>
        </>
      ) : streamingPreview ? (
        <>
          <div className="mb-1.5 flex items-center gap-2 text-xs text-neutral-400">
            <span>Running</span>
            <span>·</span>
            <span>{toolItems.length} tools</span>
          </div>
          <div className="space-y-2.5">
            {previewTools.length > 0 ? (
              <div className="space-y-1.5">
                {previewTools.map((toolItem) => {
                  const detail = extractToolPreviewDetail(toolItem.toolName, toolItem.arguments);
                  return (
                    <div key={toolItem.id} className="flex min-w-0 items-center gap-1.5 text-2xs">
                      <div className="flex items-center gap-1">
                        <span className="whitespace-nowrap font-sans text-neutral-500">
                          {toolItem.toolName}
                        </span>
                        {toolItem.isStreaming ? (
                          <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
                        ) : null}
                      </div>
                      {detail ? (
                        <code className="min-w-0 max-w-full truncate rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-neutral-500">
                          {detail}
                        </code>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
            <div className="relative overflow-hidden rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2">
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-neutral-500">
                {streamingPreview.text}
              </pre>
              {streamingPreview.hasMore ? (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-neutral-50/95 to-transparent" />
              ) : null}
            </div>
          </div>
        </>
      ) : (
        <>
          {!isFinished && moreToolsCount > 0 ? (
            <div className="mb-1.5 text-xs text-neutral-400">{moreToolsCount} more tools</div>
          ) : null}
          {previewTools.length > 0 ? (
            <div className="space-y-1.5">
              {previewTools.map((toolItem) => {
                const detail = extractToolPreviewDetail(toolItem.toolName, toolItem.arguments);
                return (
                  <div key={toolItem.id} className="flex min-w-0 items-center gap-1.5 text-2xs">
                    <span className="whitespace-nowrap font-sans text-neutral-500">
                      {toolItem.toolName}
                    </span>
                    {detail ? (
                      <code className="min-w-0 max-w-full truncate rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-neutral-500">
                        {detail}
                      </code>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-xs text-neutral-400">No tool calls</div>
          )}
        </>
      )}
    </div>
  );
}
