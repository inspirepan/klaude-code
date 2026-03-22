import { useEffect, useRef, useState } from "react";
import { Archive, ArchiveRestore, CirclePause, Loader } from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";
import { cn } from "@/lib/utils";
import { useMountEffect } from "@/hooks/useMountEffect";
import { SessionTitleText } from "@/components/SessionTitleText";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  hasUnreadCompletion: boolean;
  completionAnimationStartedAt?: number;
  onClick: () => void;
  onToggleArchive: (sessionId: string, archived: boolean) => void;
}

function UnreadCompletionDot(): JSX.Element {
  return (
    <span className="flex h-3 w-3 shrink-0 items-center justify-center">
      <span className="h-1.5 w-1.5 rounded-full bg-green-600" />
    </span>
  );
}

function getSessionTitle(session: SessionSummary): string {
  const generatedTitle = session.title?.trim();
  if (generatedTitle !== undefined && generatedTitle.length > 0) {
    return generatedTitle;
  }
  const firstMessage = session.user_messages[0]?.trim();
  if (firstMessage !== undefined && firstMessage.length > 0) {
    return firstMessage;
  }
  return "New session";
}

function formatRelativeTime(timestampSeconds: number): string {
  const diffSeconds = Math.floor(Date.now() / 1000 - timestampSeconds);
  if (diffSeconds < 60) return "now";
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d`;
  const diffWeeks = Math.floor(diffDays / 7);
  if (diffWeeks < 5) return `${diffWeeks}w`;
  const diffMonths = Math.floor(diffDays / 30);
  if (diffMonths < 12) return `${diffMonths}mo`;
  return `${Math.floor(diffDays / 365)}y`;
}

function formatDetailedTime(timestampSeconds: number): string {
  const date = new Date(timestampSeconds * 1000);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

function shortenFileRefs(text: string): string {
  return text.replace(/@[\w./\\-]+\/([^/\s]+)/g, "@$1");
}

function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element | null {
  if (added <= 0 && removed <= 0) {
    return null;
  }
  return (
    <span className="inline-flex shrink-0 gap-1 whitespace-nowrap text-xs leading-4">
      {added > 0 ? <span className="text-emerald-600">+{added}</span> : null}
      {removed > 0 ? <span className="text-rose-600">-{removed}</span> : null}
    </span>
  );
}

export function SessionCard({
  session,
  active,
  runtime,
  hasUnreadCompletion,
  completionAnimationStartedAt,
  onClick,
  onToggleArchive,
}: SessionCardProps): JSX.Element {
  const [showSuccessState, setShowSuccessState] = useState(false);
  const successAnimationFrameRef = useRef<number | null>(null);
  const successTimeoutRef = useRef<number | null>(null);
  const title = shortenFileRefs(getSessionTitle(session));
  const updatedAtDetailed = formatDetailedTime(session.updated_at);
  const relativeTime = formatRelativeTime(session.updated_at);
  const diffSummary = session.file_change_summary;

  useEffect(() => {
    if (completionAnimationStartedAt === undefined) {
      return;
    }

    const elapsed = Date.now() - completionAnimationStartedAt;
    const remaining = 1600 - elapsed;
    if (remaining <= 0) {
      return;
    }

    if (successAnimationFrameRef.current !== null) {
      window.cancelAnimationFrame(successAnimationFrameRef.current);
    }
    if (successTimeoutRef.current !== null) {
      window.clearTimeout(successTimeoutRef.current);
    }

    successAnimationFrameRef.current = window.requestAnimationFrame(() => {
      setShowSuccessState(false);
      successAnimationFrameRef.current = window.requestAnimationFrame(() => {
        setShowSuccessState(true);
        successAnimationFrameRef.current = null;
        successTimeoutRef.current = window.setTimeout(() => {
          setShowSuccessState(false);
          successTimeoutRef.current = null;
        }, remaining);
      });
    });
  }, [completionAnimationStartedAt]);

  useMountEffect(() => {
    return () => {
      if (successAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(successAnimationFrameRef.current);
      }
      if (successTimeoutRef.current !== null) {
        window.clearTimeout(successTimeoutRef.current);
      }
    };
  });

  return (
    <div className="group flex items-center gap-0.5">
      <div
        className={cn(
          "relative flex min-w-0 flex-1 items-center gap-1 rounded-md py-1 pl-1.5 pr-1.5 text-left transition-colors",
          showSuccessState
            ? active
              ? "status-success-card-settle-active"
              : "status-success-card-settle"
            : active
              ? "bg-neutral-200/60"
              : "hover:bg-muted/80",
        )}
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          onClick();
        }}
        title={title}
      >
        {runtime.sessionState !== "idle" ? (
          <span className="flex h-3 w-3 shrink-0 items-center justify-center">
            {runtime.sessionState === "running" ? (
              <Loader className="h-3 w-3 animate-spin text-neutral-500" />
            ) : (
              <CirclePause className="h-3 w-3 text-amber-500" />
            )}
          </span>
        ) : hasUnreadCompletion ? (
          <UnreadCompletionDot />
        ) : null}
        <SessionTitleText
          title={title}
          as="div"
          className="flex min-w-0 flex-1 items-baseline text-sm leading-5"
          secondaryClassName="shrink truncate"
        />
        <DiffStats added={diffSummary.diff_lines_added} removed={diffSummary.diff_lines_removed} />
        <span
          className="w-7 shrink-0 text-right text-xs leading-4 text-neutral-400"
          title={updatedAtDetailed}
        >
          {relativeTime}
        </span>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-neutral-400 opacity-0 transition-opacity hover:text-neutral-700 focus:outline-none focus-visible:opacity-100 group-hover:opacity-100"
            aria-label={session.archived ? "Unarchive session" : "Archive session"}
            onClick={() => {
              onToggleArchive(session.id, !session.archived);
            }}
          >
            {session.archived ? (
              <ArchiveRestore className="h-3 w-3" />
            ) : (
              <Archive className="h-3 w-3" />
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent>
          {session.archived ? "Unarchive session" : "Archive session"}
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
