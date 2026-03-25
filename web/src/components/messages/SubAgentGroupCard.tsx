import { memo, useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { useMessageStore } from "@/stores/message-store";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";
import { formatElapsed, formatSubAgentTypeLabel, shortSessionId } from "./message-list-ui";

interface SubAgentGroupCardProps {
  parentSessionId: string;
  sourceSessionId: string;
  sourceSessionType: string | null;
  sourceSessionDesc: string | null;
  toolCount: number;
  onEnterSubAgent: (subAgentId: string) => void;
}

export const SubAgentGroupCard = memo(function SubAgentGroupCard({
  parentSessionId,
  sourceSessionId,
  sourceSessionType,
  sourceSessionDesc,
  toolCount,
  onEnterSubAgent,
}: SubAgentGroupCardProps): React.JSX.Element {
  const t = useT();
  const status = useMessageStore(
    useCallback(
      (state) =>
        state.reducerStateBySessionId[parentSessionId]?.statusBySessionId[sourceSessionId] ?? null,
      [parentSessionId, sourceSessionId],
    ),
  );
  const isFinished = useMessageStore(
    useCallback(
      (state) =>
        state.reducerStateBySessionId[parentSessionId]?.subAgentFinishedBySessionId[
          sourceSessionId
        ] ?? false,
      [parentSessionId, sourceSessionId],
    ),
  );
  const isActive =
    status != null && (status.taskActive || status.awaitingInput || status.compacting);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const taskStartedAt = status?.taskStartedAt ?? null;

  useEffect(() => {
    if (!isActive || taskStartedAt == null) return;
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [isActive, taskStartedAt]);

  const nowSeconds = nowMs / 1000;
  const elapsedText =
    taskStartedAt != null && isActive
      ? formatElapsed(nowSeconds - taskStartedAt)
      : status?.taskElapsedSeconds != null
        ? formatElapsed(status.taskElapsedSeconds)
        : null;
  const handleClick = useCallback(() => {
    onEnterSubAgent(sourceSessionId);
  }, [onEnterSubAgent, sourceSessionId]);

  return (
    <div
      className={`grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} cursor-pointer text-base`}
      onClick={handleClick}
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
});
