import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  CircleCheck,
  CirclePause,
  Loader,
  MessagesSquare,
} from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";
import { cn } from "@/lib/utils";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  hasUnreadCompletion: boolean;
  onClick: () => void;
  onToggleArchive: (sessionId: string, archived: boolean) => void;
}

function UnreadCompletionDot(): JSX.Element {
  return (
    <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
      <span className="h-2 w-2 rounded-full bg-green-600" />
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
    return <Loader className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-400" />;
  }
  if (runtime.sessionState === "waiting_user_input") {
    return <CirclePause className="h-3.5 w-3.5 shrink-0 text-amber-500" />;
  }
  if (hasUnreadCompletion) {
    return <UnreadCompletionDot />;
  }
  if (showSuccessState) {
    return <CircleCheck className="status-success-settle h-3.5 w-3.5 shrink-0" />;
  }
  return <CircleCheck className="h-3.5 w-3.5 shrink-0 text-neutral-400" />;
}

function shortenFileRefs(text: string): string {
  return text.replace(/@[\w./\\-]+\/([^/\s]+)/g, "@$1");
}

export function SessionCard({
  session,
  active,
  runtime,
  hasUnreadCompletion,
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
  const modelLabel = session.model_name ?? "N/A model";

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

  return (
    <div className="group">
      <div
        className={cn(
          "relative flex w-full flex-col gap-y-0.5 rounded-lg py-1.5 pl-1.5 pr-2 text-left transition-colors",
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
        <div className="flex min-w-0 items-center gap-1.5 pl-1">
          {getRuntimeIcon(runtime, showSuccessState, hasUnreadCompletion)}
          <span className="flex-1 truncate text-[13px] leading-5 text-neutral-800">{title}</span>
          {runtime.sessionState === "running" ? (
            <span className="inline-flex shrink-0 items-center rounded-full bg-blue-50 px-1.5 text-[10px] leading-4 text-blue-500">
              Running…
            </span>
          ) : null}
        </div>

        <div className="flex min-w-0 items-center gap-1 pl-6 pr-1 text-[10px] leading-4 text-neutral-400">
          <div className="flex min-w-0 items-center gap-1 truncate">
            <MessagesSquare className="h-3 w-3 shrink-0" />
            <span>{messageCountLabel}</span>
            <span>·</span>
            <span className="truncate">{modelLabel}</span>
          </div>

          <div className="ml-auto flex items-center">
            {runtime.sessionState !== "running" && (
              <>
                <span className="whitespace-nowrap group-hover:hidden" title={updatedAtDetailed}>
                  {updatedAt}
                </span>
                <button
                  type="button"
                  className="hidden h-4 w-4 items-center justify-center rounded text-neutral-400 hover:text-neutral-700 focus:outline-none group-hover:inline-flex"
                  title={session.archived ? "Unarchive session" : "Archive session"}
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
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
