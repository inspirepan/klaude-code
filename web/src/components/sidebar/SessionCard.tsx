import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  CircleCheck,
  CirclePause,
  Lock,
  MessageSquare,
} from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";
import { cn } from "@/lib/utils";
import { SessionTitleText } from "@/components/SessionTitleText";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  hasUnreadCompletion: boolean;
  showWorkspace?: boolean;
  compact?: boolean;
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
  const deltaSeconds = Math.max(0, Math.floor(Date.now() / 1000 - timestampSeconds));
  if (deltaSeconds < 60) {
    return "Just now";
  }
  if (deltaSeconds < 3600) {
    return `${Math.floor(deltaSeconds / 60)} min`;
  }
  if (deltaSeconds < 86400) {
    return `${Math.floor(deltaSeconds / 3600)} hr`;
  }
  if (deltaSeconds < 604800) {
    return `${Math.floor(deltaSeconds / 86400)} day`;
  }
  if (deltaSeconds < 2592000) {
    return `${Math.floor(deltaSeconds / 604800)} wk`;
  }
  return `${Math.floor(deltaSeconds / 2592000)} mo`;
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

function getRuntimeIcon(
  runtime: SessionRuntimeState,
  showSuccessState: boolean,
  hasUnreadCompletion: boolean,
): JSX.Element {
  if (runtime.sessionState === "running") {
    return (
      <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-[1.25px] border-neutral-300 border-t-neutral-500" />
    );
  }
  if (runtime.sessionState === "waiting_user_input") {
    return <CirclePause className="h-3 w-3 shrink-0 text-amber-500" />;
  }
  if (hasUnreadCompletion) {
    return <UnreadCompletionDot />;
  }
  if (showSuccessState) {
    return <CircleCheck className="status-success-settle h-3 w-3 shrink-0" />;
  }
  return <CircleCheck className="h-3 w-3 shrink-0 text-neutral-400" />;
}

function shortenFileRefs(text: string): string {
  return text.replace(/@[\w./\\-]+\/([^/\s]+)/g, "@$1");
}

function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((segment) => segment.length > 0);
  if (parts.length === 0) {
    return workDir;
  }
  return parts[parts.length - 1] ?? workDir;
}

function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element | null {
  if (added <= 0 && removed <= 0) {
    return null;
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[9px] leading-4">
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
  showWorkspace = false,
  compact = false,
  onClick,
  onToggleArchive,
}: SessionCardProps): JSX.Element {
  const [showSuccessState, setShowSuccessState] = useState(false);
  const previousSessionStateRef = useRef(runtime.sessionState);
  const successAnimationFrameRef = useRef<number | null>(null);
  const successTimeoutRef = useRef<number | null>(null);
  const title = shortenFileRefs(getSessionTitle(session));
  const updatedAt = formatRelativeTime(session.updated_at);
  const updatedAtDetailed = formatDetailedTime(session.updated_at);
  const messageCountLabel = session.messages_count >= 0 ? String(session.messages_count) : "N/A";
  const diffSummary = session.file_change_summary;

  useEffect(() => {
    const previousSessionState = previousSessionStateRef.current;
    previousSessionStateRef.current = runtime.sessionState;

    if (previousSessionState === "running" && runtime.sessionState === "idle") {
      if (successAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(successAnimationFrameRef.current);
      }
      if (successTimeoutRef.current !== null) {
        window.clearTimeout(successTimeoutRef.current);
      }
      successAnimationFrameRef.current = window.requestAnimationFrame(() => {
        setShowSuccessState(true);
        successAnimationFrameRef.current = null;
        successTimeoutRef.current = window.setTimeout(() => {
          setShowSuccessState(false);
          successTimeoutRef.current = null;
        }, 1600);
      });
    }
  }, [runtime.sessionState]);

  useEffect(() => {
    return () => {
      if (successAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(successAnimationFrameRef.current);
      }
      if (successTimeoutRef.current !== null) {
        window.clearTimeout(successTimeoutRef.current);
      }
    };
  }, []);

  if (compact) {
    return (
      <div className="group">
        <div
          className={cn(
            "relative flex w-full min-w-0 items-center gap-1.5 rounded-md py-1 pl-2 pr-1.5 text-left transition-colors",
            showSuccessState
              ? active
                ? "status-success-card-settle-active"
                : "status-success-card-settle"
              : active
                ? "bg-neutral-200/60"
                : "hover:bg-neutral-100/80",
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
          <SessionTitleText
            title={title}
            as="div"
            className="flex min-w-0 flex-1 items-baseline text-[13px] leading-5"
            secondaryClassName="shrink truncate"
          />
          <DiffStats
            added={diffSummary.diff_lines_added}
            removed={diffSummary.diff_lines_removed}
          />
          <span
            className="shrink-0 whitespace-nowrap text-[10px] leading-4 text-neutral-400"
            title={updatedAtDetailed}
          >
            {updatedAt}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-neutral-400 hover:text-neutral-700 focus:outline-none"
                aria-label={session.archived ? "Unarchive session" : "Archive session"}
                onClick={(event) => {
                  event.stopPropagation();
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
      </div>
    );
  }

  return (
    <div className="group">
      <div
        className={cn(
          "relative flex w-full flex-col gap-y-0 rounded-lg py-1 pl-1.5 pr-1.5 text-left transition-colors",
          showSuccessState
            ? active
              ? "status-success-card-settle-active"
              : "status-success-card-settle"
            : active
              ? "bg-neutral-200/60"
              : "hover:bg-neutral-100/80",
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
        <div className="flex min-w-0 items-start gap-1.5 pl-1">
          <span className="mt-1 flex shrink-0">
            {getRuntimeIcon(runtime, showSuccessState, hasUnreadCompletion)}
          </span>
          <div
            className="min-w-0 flex-1 overflow-hidden text-[13px] leading-5"
            style={{
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 2,
            }}
          >
            <SessionTitleText title={title} as="span" truncate={false} />
          </div>
        </div>

        <div className="flex min-w-0 items-center gap-1 pl-6 pr-1 text-[9px] leading-4 text-neutral-400">
          <div className="flex min-w-0 items-center gap-1 truncate">
            {showWorkspace ? (
              <>
                <span className="truncate text-[11px] text-neutral-500" title={session.work_dir}>
                  {workDirLabel(session.work_dir)}
                </span>
              </>
            ) : null}
            <MessageSquare className="h-2.5 w-2.5 shrink-0" />
            <span>{messageCountLabel}</span>
          </div>

          {session.read_only ? (
            <span
              className="inline-flex shrink-0 items-center rounded-full bg-amber-50 p-0.5 text-amber-700"
              title="Read-only"
              aria-label="Read-only"
            >
              <Lock className="h-3 w-3" />
            </span>
          ) : null}

          <DiffStats
            added={diffSummary.diff_lines_added}
            removed={diffSummary.diff_lines_removed}
          />

          <div className="relative ml-auto flex items-center">
            <span
              className="whitespace-nowrap transition-opacity group-hover:opacity-0"
              title={updatedAtDetailed}
            >
              {updatedAt}
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="pointer-events-none absolute right-0 top-1/2 inline-flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded text-neutral-400 opacity-0 transition-opacity hover:text-neutral-700 focus:outline-none focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover:pointer-events-auto group-hover:opacity-100"
                  aria-label={session.archived ? "Unarchive session" : "Archive session"}
                  onClick={(event) => {
                    event.stopPropagation();
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
        </div>
      </div>
    </div>
  );
}
