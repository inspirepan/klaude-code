import { CircleHelp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { SessionStatusState } from "../../stores/event-reducer";
import type { SessionRuntimeState } from "../../types/session";

interface SessionStatusBarProps {
  status: SessionStatusState | null;
  runtime: SessionRuntimeState | null;
}

function getStatusLabel(status: SessionStatusState | null): string | null {
  if (status === null) return null;
  return status.awaitingInput
    ? "Waiting for input …"
    : status.compacting
      ? "Compacting …"
      : status.thinkingActive
        ? "Thinking …"
        : status.isComposing
          ? "Typing …"
          : status.taskActive
            ? "Running …"
            : null;
}

function getRuntimeStatusLabel(runtime: SessionRuntimeState | null): string | null {
  if (runtime === null) return null;
  if (runtime.sessionState === "waiting_user_input") return "Waiting for input …";
  if (runtime.sessionState === "running") return "Running …";
  return null;
}

function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  if (Math.abs(value) < 1000) return Math.round(value).toString();
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m${remainingSeconds.toString().padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h${remainingMinutes.toString().padStart(2, "0")}m`;
}

function formatCurrency(total: number, currency: string): string {
  const symbol = currency === "CNY" ? "¥" : "$";
  return `${symbol}${total.toFixed(4)}`;
}

function getSessionSummaryParts(status: SessionStatusState | null, nowSeconds: number): string[] {
  if (status === null) return [];

  const parts: string[] = [];
  if (status.contextPercent !== null) {
    parts.push(`${status.contextPercent.toFixed(1)}%`);
  }
  if (status.totalCost !== null) {
    parts.push(formatCurrency(status.totalCost, status.currency));
  }
  if (
    status.taskStartedAt !== null &&
    (status.taskActive || status.awaitingInput || status.compacting)
  ) {
    parts.push(formatElapsed(nowSeconds - status.taskStartedAt));
  }
  return parts;
}

function getSessionMetaRows(
  status: SessionStatusState | null,
  nowSeconds: number,
): Array<{ label: string; value: string }> {
  if (status === null) return [];

  const rows: Array<{ label: string; value: string }> = [];
  if (status.tokenInput !== null) {
    rows.push({ label: "Input", value: formatCompactNumber(status.tokenInput) });
  }
  if ((status.tokenCached ?? 0) > 0) {
    rows.push({
      label: "Cached",
      value:
        status.cacheHitRate !== null
          ? `${formatCompactNumber(status.tokenCached ?? 0)} (${Math.round(status.cacheHitRate * 100)}%)`
          : formatCompactNumber(status.tokenCached ?? 0),
    });
  }
  if ((status.tokenCacheWrite ?? 0) > 0) {
    rows.push({ label: "Cache write", value: formatCompactNumber(status.tokenCacheWrite ?? 0) });
  }
  if (status.tokenOutput !== null) {
    rows.push({ label: "Output", value: formatCompactNumber(status.tokenOutput) });
  }
  if ((status.tokenThought ?? 0) > 0) {
    rows.push({ label: "Thought", value: formatCompactNumber(status.tokenThought ?? 0) });
  }
  if (
    status.contextSize !== null &&
    status.contextEffectiveLimit !== null &&
    status.contextPercent !== null
  ) {
    rows.push({
      label: "Context",
      value: `${formatCompactNumber(status.contextSize)}/${formatCompactNumber(status.contextEffectiveLimit)} (${status.contextPercent.toFixed(1)}%)`,
    });
  }
  if (status.totalCost !== null) {
    rows.push({ label: "Cost", value: formatCurrency(status.totalCost, status.currency) });
  }
  if (
    status.taskStartedAt !== null &&
    (status.taskActive || status.awaitingInput || status.compacting)
  ) {
    rows.push({ label: "Elapsed", value: formatElapsed(nowSeconds - status.taskStartedAt) });
  }
  return rows;
}

export function SessionStatusBar({ status, runtime }: SessionStatusBarProps): JSX.Element | null {
  const [metaOpen, setMetaOpen] = useState(false);
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
  const statusLabel = getStatusLabel(status) ?? getRuntimeStatusLabel(runtime);
  const summaryParts = useMemo(
    () => getSessionSummaryParts(status, nowSeconds),
    [nowSeconds, status],
  );
  const metaRows = useMemo(() => getSessionMetaRows(status, nowSeconds), [nowSeconds, status]);

  if (statusLabel === null && summaryParts.length === 0 && metaRows.length === 0) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 rounded-xl border border-neutral-200/80 bg-neutral-50/80 px-3 py-2 text-neutral-500">
      {statusLabel ? (
        <>
          {hasLiveStatus ? (
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-[1.5px] border-neutral-300 border-t-neutral-500" />
          ) : (
            <span className="h-2 w-2 shrink-0 rounded-full bg-neutral-300" />
          )}
          <span className="truncate font-mono text-[13px] font-medium">{statusLabel}</span>
        </>
      ) : null}
      {summaryParts.length > 0 ? (
        <div className="ml-auto flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-neutral-400">
          {summaryParts.map((part) => (
            <span key={part}>{part}</span>
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
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
            aria-label="Show session metadata"
            onClick={() => setMetaOpen((current) => !current)}
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </button>
          {metaOpen ? (
            <div className="absolute bottom-full right-0 z-20 mb-2 min-w-[180px] rounded-xl border border-neutral-200/80 bg-white p-3 shadow-lg shadow-neutral-200/60">
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
  );
}
