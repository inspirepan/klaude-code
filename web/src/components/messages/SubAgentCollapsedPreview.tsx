import { useEffect, useRef } from "react";

import { Loader } from "lucide-react";

import type { PreviewText } from "./message-list-ui";
import { extractToolPreviewDetail } from "./message-list-ui";
import type { ToolBlockItem } from "../../types/message";

interface SubAgentCollapsedPreviewProps {
  isFinished: boolean;
  toolItems: ToolBlockItem[];
  resultPreview: PreviewText | null;
  streamingPreview: PreviewText | null;
}

export function SubAgentCollapsedPreview({
  isFinished,
  toolItems,
  resultPreview,
  streamingPreview,
}: SubAgentCollapsedPreviewProps): JSX.Element {
  const toolListRef = useRef<HTMLDivElement | null>(null);
  const lastTool = toolItems.at(-1);

  useEffect(() => {
    const element = toolListRef.current;
    if (!element) {
      return;
    }

    element.scrollTop = element.scrollHeight;
  }, [toolItems.length, lastTool?.id, lastTool?.isStreaming]);

  return (
    <div className="px-3.5 pb-3.5 pt-0.5">
      <div className="mb-2.5">
        <div className="mb-1.5 flex items-center gap-2 text-xs text-neutral-500">
          <span>{toolItems.length} tools</span>
          {!isFinished ? (
            <>
              <span>·</span>
              <span>Rolling out</span>
            </>
          ) : null}
        </div>
        <div
          ref={toolListRef}
          className="h-28 overflow-y-auto rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2"
        >
          {toolItems.length > 0 ? (
            <div className="space-y-1.5 pr-1">
              {toolItems.map((toolItem) => {
                const detail = extractToolPreviewDetail(toolItem.toolName, toolItem.arguments);
                return (
                  <div key={toolItem.id} className="flex min-w-0 items-center gap-1.5 text-2xs">
                    <div className="flex items-center gap-1">
                      <span className="whitespace-nowrap font-sans text-neutral-500">
                        {toolItem.toolName}
                      </span>
                      {toolItem.isStreaming ? (
                        <Loader className="h-3 w-3 shrink-0 animate-spin text-neutral-500" />
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
          ) : (
            <div className="text-xs text-neutral-500">No tool calls</div>
          )}
        </div>
      </div>
      {resultPreview ? (
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
      ) : streamingPreview ? (
        <div className="relative overflow-hidden rounded-lg border border-neutral-200/80 bg-neutral-50/70 px-2.5 py-2">
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-neutral-500">
            {streamingPreview.text}
          </pre>
          {streamingPreview.hasMore ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-neutral-50/95 to-transparent" />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
