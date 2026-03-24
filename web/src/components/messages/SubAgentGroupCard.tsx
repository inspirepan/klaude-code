import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import type { SessionStatusState } from "../../stores/event-reducer";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";
import { formatElapsed, formatSubAgentTypeLabel, shortSessionId } from "./message-list-ui";

interface SubAgentGroupCardProps {
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
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
  toolCount,
  status,
  isFinished,
  nowSeconds,
  onClick,
}: SubAgentGroupCardProps): React.JSX.Element {
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
    <div
      className={`grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} cursor-pointer text-base`}
      onClick={onClick}
    >
      {/* Dot marker */}
      <span className="flex h-[1lh] items-center justify-center">
        <span
          className={cn("h-1 w-1 rounded-full", isFinished ? "bg-emerald-500" : "bg-neutral-300")}
        />
      </span>

      {/* Content */}
      <div className="flex min-h-6 min-w-0 items-center gap-1.5 text-sm leading-5">
        <span className={cn("shrink-0 font-medium text-neutral-700", isActive && "text-shimmer")}>
          {formatSubAgentTypeLabel(sourceSessionType)}
        </span>
        <span className="min-w-0 truncate text-neutral-600">
          {sourceSessionDesc ?? t("subAgent.defaultDesc")(shortSessionId(sourceSessionId))}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5 text-neutral-500">
          {toolCount > 0 ? <span>{t("subAgent.toolCall")(toolCount)}</span> : null}
          {toolCount > 0 && elapsedText ? <span className="text-neutral-300">&middot;</span> : null}
          {elapsedText ? <span>{elapsedText}</span> : null}
        </div>
      </div>
    </div>
  );
}
