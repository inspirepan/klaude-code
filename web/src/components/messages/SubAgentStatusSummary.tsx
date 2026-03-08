import { CircleHelp } from "lucide-react";

import type { SubAgentMetaRow } from "./message-list-ui";

interface SubAgentStatusSummaryProps {
  activityText: string | null;
  summaryParts: string[];
  metaRows: SubAgentMetaRow[];
  metaOpen: boolean;
  onMetaOpenChange: (open: boolean) => void;
}

export function SubAgentStatusSummary({
  activityText,
  summaryParts,
  metaRows,
  metaOpen,
  onMetaOpenChange,
}: SubAgentStatusSummaryProps): JSX.Element | null {
  if (activityText === null && summaryParts.length === 0 && metaRows.length === 0) {
    return null;
  }

  return (
    <div className="px-3.5 pb-2 pt-0 text-xs">
      {activityText ? (
        <div className="truncate font-mono text-neutral-500">{activityText}</div>
      ) : null}
      {summaryParts.length > 0 || metaRows.length > 0 ? (
        <div className="mt-1 flex items-center gap-2">
          {summaryParts.length > 0 ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-neutral-400">
              {summaryParts.map((part) => (
                <span key={part}>{part}</span>
              ))}
            </div>
          ) : null}
          {metaRows.length > 0 ? (
            <div
              className="relative"
              onMouseEnter={() => {
                onMetaOpenChange(true);
              }}
              onMouseLeave={() => {
                onMetaOpenChange(false);
              }}
            >
              <button
                type="button"
                className="inline-flex h-5 w-5 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
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
                        <span className="text-neutral-400">{row.label}</span>
                        <span className="text-right font-mono text-neutral-600">{row.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
