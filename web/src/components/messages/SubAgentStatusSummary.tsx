import { CircleHelp } from "lucide-react";

import type { SubAgentMetaRow } from "./message-list-ui";

interface SubAgentStatusSummaryProps {
  activityText: string | null;
  summaryParts: string[];
  metaRows: SubAgentMetaRow[];
  metaOpen: boolean;
  toolCount: number;
  isFinished: boolean;
  onMetaOpenChange: (open: boolean) => void;
}

export function SubAgentStatusSummary({
  activityText,
  summaryParts,
  metaRows,
  metaOpen,
  toolCount,
  isFinished,
  onMetaOpenChange,
}: SubAgentStatusSummaryProps): JSX.Element | null {
  const parts: string[] = [];
  if (toolCount > 0) parts.push(`${toolCount} tools`);
  parts.push(...summaryParts);

  if (activityText === null && parts.length === 0 && metaRows.length === 0) {
    return null;
  }

  return (
    <div className="flex items-center gap-2 px-4 pb-2.5 text-xs">
      {activityText ? (
        <span className="relative flex h-1.5 w-1.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
        </span>
      ) : isFinished ? (
        <span className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
      ) : null}

      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-neutral-500">
        {activityText ? <span className="font-mono">{activityText}</span> : null}
        {parts.map((part, i) => (
          <span key={part} className="flex items-center gap-2">
            {i > 0 || activityText !== null ? (
              <span className="text-neutral-300">&middot;</span>
            ) : null}
            {part}
          </span>
        ))}
      </div>

      {metaRows.length > 0 ? (
        <div
          className="relative ml-auto shrink-0"
          onMouseEnter={() => {
            onMetaOpenChange(true);
          }}
          onMouseLeave={() => {
            onMetaOpenChange(false);
          }}
        >
          <button
            type="button"
            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-neutral-400 transition-colors hover:bg-neutral-200 hover:text-neutral-600"
            aria-label="Show sub-agent metadata"
            onClick={() => {
              onMetaOpenChange(!metaOpen);
            }}
          >
            <CircleHelp className="h-3 w-3" />
          </button>
          {metaOpen ? (
            <div className="absolute right-0 top-full z-20 mt-2 min-w-[180px] rounded-xl border border-neutral-200/80 bg-white p-3 shadow-lg shadow-neutral-200/60">
              <div className="space-y-1.5 text-xs leading-5">
                {metaRows.map((row) => (
                  <div key={row.label} className="flex items-start justify-between gap-4">
                    <span className="text-neutral-500">{row.label}</span>
                    <span className="text-right font-sans text-neutral-600">{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
