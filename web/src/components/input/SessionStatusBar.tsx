import { Loader } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "@/i18n";

import type { SessionStatusState } from "../../stores/event-reducer";
import type { SessionRuntimeState } from "../../types/session";
import { getSessionActivityText, formatElapsed } from "../messages/message-list-ui";

interface SessionStatusBarProps {
  status: SessionStatusState | null;
  runtime: SessionRuntimeState | null;
}

function getRuntimeStatusLabel(
  runtime: SessionRuntimeState | null,
  t: ReturnType<typeof useT>,
): string | null {
  if (runtime === null) return null;
  if (runtime.sessionState === "running") return t("status.running");
  if (runtime.sessionState === "waiting_user_input") return t("status.waitingInput");
  return null;
}

export function SessionStatusBar({
  status,
  runtime,
}: SessionStatusBarProps): React.JSX.Element | null {
  const t = useT();
  const [nowMs, setNowMs] = useState(() => Date.now());

  const hasLiveStatus =
    status?.taskActive === true ||
    status?.awaitingInput === true ||
    status?.compacting === true ||
    status?.thinkingActive === true ||
    status?.isComposing === true ||
    runtime?.sessionState === "running" ||
    runtime?.sessionState === "waiting_user_input";

  useEffect(() => {
    if (!hasLiveStatus) return;
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [hasLiveStatus]);

  const nowSeconds = nowMs / 1000;
  const statusLabel = getSessionActivityText(status) ?? getRuntimeStatusLabel(runtime, t);
  const elapsed =
    status?.taskStartedAt !== null &&
    status?.taskStartedAt !== undefined &&
    (status.taskActive || status.awaitingInput || status.compacting)
      ? formatElapsed(nowSeconds - status.taskStartedAt)
      : null;

  if (statusLabel === null && elapsed === null) {
    return null;
  }

  return (
    <div className="flex items-center gap-2 pt-0.5 text-neutral-500">
      {statusLabel ? (
        <>
          {hasLiveStatus ? (
            <Loader className="h-4 w-4 shrink-0 animate-spin" />
          ) : (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-300" />
          )}
          <span className="truncate font-sans text-sm">{statusLabel}</span>
        </>
      ) : null}
      {elapsed ? (
        <span className="font-sans text-sm">
          {statusLabel ? <span className="mr-2 text-neutral-300">&middot;</span> : null}
          {elapsed}
        </span>
      ) : null}
    </div>
  );
}
