import { CircleCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import type { SessionStatusState } from "../../stores/event-reducer";
import { formatElapsed, formatSubAgentTypeLabel, shortSessionId } from "./message-list-ui";

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
  const t = useT();
  const isActive =
    status != null && (status.taskActive || status.awaitingInput || status.compacting);
  const elapsedText =
    status?.taskStartedAt != null && isActive
      ? formatElapsed(nowSeconds - status.taskStartedAt)
      : status?.taskElapsedSeconds != null
        ? formatElapsed(status.taskElapsedSeconds)
        : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className="group/subagent flex w-3/5 cursor-pointer items-center gap-2.5 rounded-lg border border-border/80 bg-surface/50 px-3.5 py-2.5 text-left shadow-sm shadow-neutral-200/40 transition-colors hover:bg-neutral-50"
    >
      {/* Status icon */}
      {isFinished ? (
        <CircleCheck className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
      ) : !isActive ? (
        <span className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-300" />
      ) : null}

      {/* Type label */}
      <span
        className={cn(
          "shrink-0 text-sm font-medium text-neutral-700",
          isActive && "text-shimmer",
        )}
      >
        {formatSubAgentTypeLabel(sourceSessionType)}
      </span>

      {/* Description */}
      <span className="min-w-0 truncate text-sm text-neutral-600">
        {sourceSessionDesc ?? t("subAgent.defaultDesc")(shortSessionId(sourceSessionId))}
      </span>

      {/* Fork badge */}
      {sourceSessionFork ? (
        <span className="shrink-0 rounded-md border border-border bg-neutral-50 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
          {t("subAgent.fork")}
        </span>
      ) : null}

      {/* Elapsed + tool count (right-aligned) */}
      <div className="ml-auto flex shrink-0 items-center gap-2 text-sm text-neutral-500">
        {elapsedText ? <span className="font-sans">{elapsedText}</span> : null}
        {toolCount > 0 ? (
          <>
            {elapsedText ? <span className="text-neutral-300">&middot;</span> : null}
            <span>{t("subAgent.toolCall")(toolCount)}</span>
          </>
        ) : null}
      </div>
    </button>
  );
}
