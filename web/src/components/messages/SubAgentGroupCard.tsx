import { Wrench } from "lucide-react";

import type { SessionStatusState } from "../../stores/event-reducer";
import {
  formatElapsed,
  formatSubAgentTypeLabel,
  getSessionActivityText,
  shortSessionId,
} from "./message-list-ui";

interface SubAgentGroupCardProps {
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  sourceSessionFork: boolean;
  toolCount: number;
  status: SessionStatusState | null;
  isFinished: boolean;
  nowSeconds: number;
  onClick: () => void;
}

export function SubAgentGroupCard({
  sourceSessionId,
  sourceSessionType,
  sourceSessionDesc,
  sourceSessionFork,
  toolCount,
  status,
  isFinished,
  nowSeconds,
  onClick,
}: SubAgentGroupCardProps): JSX.Element {
  const activityText = getSessionActivityText(status);
  const elapsedText =
    status?.taskStartedAt != null &&
    (status.taskActive || status.awaitingInput || status.compacting)
      ? formatElapsed(nowSeconds - status.taskStartedAt)
      : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className="group/subagent flex w-3/5 cursor-pointer items-center gap-3 rounded-xl border border-neutral-200/80 bg-surface/50 px-4 py-3 text-left shadow-sm shadow-neutral-200/40 transition-colors hover:bg-neutral-50"
    >
      {/* Status dot */}
      {activityText ? (
        <span className="relative flex h-1.5 w-1.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
        </span>
      ) : isFinished ? (
        <span className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
      ) : (
        <span className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-300" />
      )}

      {/* Type label */}
      <span className="shrink-0 text-base font-semibold text-neutral-800">
        {formatSubAgentTypeLabel(sourceSessionType)}
      </span>

      {/* Description */}
      <span className="min-w-0 truncate text-base text-neutral-600">
        {sourceSessionDesc ?? `Sub Agent ${shortSessionId(sourceSessionId)}`}
      </span>

      {/* Fork badge */}
      {sourceSessionFork ? (
        <span className="shrink-0 rounded-md border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
          fork
        </span>
      ) : null}

      {/* Activity + elapsed + tool count (right-aligned) */}
      <div className="ml-auto flex shrink-0 items-center gap-2 text-base text-neutral-500">
        {activityText ? <span className="font-mono text-base">{activityText}</span> : null}
        {elapsedText ? (
          <>
            {activityText ? <span className="text-neutral-300">&middot;</span> : null}
            <span className="font-mono">{elapsedText}</span>
          </>
        ) : null}
        {toolCount > 0 ? (
          <>
            {activityText || elapsedText ? (
              <span className="text-neutral-300">&middot;</span>
            ) : null}
            <span className="flex items-center gap-1">
              <Wrench className="h-3.5 w-3.5 shrink-0" />
              <span>{toolCount}</span>
            </span>
          </>
        ) : null}
      </div>
    </button>
  );
}
