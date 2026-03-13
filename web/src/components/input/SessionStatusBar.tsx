import { CircleHelp, Loader } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { SessionStatusState } from "../../stores/event-reducer";
import type { SessionRuntimeState } from "../../types/session";
import {
  getSessionActivityText,
  getSessionMetaRows,
  getSessionSummaryParts,
} from "../messages/message-list-ui";

interface SessionStatusBarProps {
  status: SessionStatusState | null;
  runtime: SessionRuntimeState | null;
}

function getRuntimeStatusLabel(runtime: SessionRuntimeState | null): string | null {
  if (runtime === null) return null;
  if (runtime.sessionState === "running") return "Running …";
  if (runtime.sessionState === "waiting_user_input") return "Waiting for input …";
  return null;
}

export function SessionStatusBar({ status, runtime }: SessionStatusBarProps): JSX.Element | null {
  const [metaOpen, setMetaOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const isRunning =
    runtime?.sessionState === "running" ||
    (status?.taskActive === true &&
      status.awaitingInput !== true &&
      status.compacting !== true &&
      status.thinkingActive !== true &&
      status.isComposing !== true);

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
  const statusLabel = getSessionActivityText(status) ?? getRuntimeStatusLabel(runtime);
  const summaryParts = useMemo(
    () => getSessionSummaryParts(status, nowSeconds),
    [nowSeconds, status],
  );
  const metaRows = useMemo(() => getSessionMetaRows(status, nowSeconds), [nowSeconds, status]);

  if (statusLabel === null && summaryParts.length === 0 && metaRows.length === 0) {
    return null;
  }

  return (
    <div className="inline-flex w-fit max-w-full items-center gap-2.5 rounded-full bg-white px-3 py-1.5 text-neutral-500 shadow-sm ring-1 ring-black/5">
      {statusLabel ? (
        <>
          {hasLiveStatus ? (
            <Loader
              className={`h-3.5 w-3.5 shrink-0 animate-spin ${isRunning ? "text-blue-500" : "text-neutral-500"}`}
            />
          ) : (
            <span className="h-2 w-2 shrink-0 rounded-full bg-neutral-300" />
          )}
          <span className={`truncate font-sans text-xs ${isRunning ? "text-blue-500" : ""}`}>
            {statusLabel}
          </span>
        </>
      ) : null}
      {summaryParts.length > 0 ? (
        <div className="ml-2 flex flex-wrap items-center gap-y-1 font-sans text-2xs text-neutral-400">
          {summaryParts.map((part, i) => (
            <span key={part} className="flex items-center">
              {i > 0 ? <span className="mx-1.5 text-neutral-300">·</span> : null}
              {part}
            </span>
          ))}
        </div>
      ) : null}
      {metaRows.length > 0 ? (
        <div
          className="relative ml-1"
          onMouseEnter={() => setMetaOpen(true)}
          onMouseLeave={() => setMetaOpen(false)}
        >
          <button
            type="button"
            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-neutral-400 transition-colors hover:bg-neutral-200 hover:text-neutral-600"
            aria-label="Show session metadata"
            onClick={() => setMetaOpen((current) => !current)}
          >
            <CircleHelp className="h-3 w-3" />
          </button>
          {metaOpen ? (
            <div className="absolute bottom-full right-0 z-20 mb-2 min-w-[180px] rounded-xl border border-neutral-200/80 bg-white p-3 shadow-lg shadow-neutral-200/60">
              <div className="space-y-1.5 text-xs leading-5">
                {metaRows.map((row) => (
                  <div key={row.label} className="flex items-start justify-between gap-4">
                    <span className="text-neutral-400">{row.label}</span>
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
