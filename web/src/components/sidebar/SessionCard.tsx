import { useEffect, useRef, useState } from "react";
import { Archive, ArchiveRestore, CheckCircle, CirclePause, Loader } from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";
import { cn } from "@/lib/utils";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  onClick: () => void;
  onToggleArchive: (sessionId: string, archived: boolean) => void;
}

function getSessionTitle(session: SessionSummary): string {
  const firstMessage = session.user_messages[0]?.trim();
  if (firstMessage !== undefined && firstMessage.length > 0) {
    return firstMessage;
  }
  return "New session";
}

function getSessionExcerpt(session: SessionSummary): string {
  if (session.user_messages.length > 0) {
    return session.user_messages[session.user_messages.length - 1] ?? "Restored session";
  }
  return "No user message yet";
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

function getRuntimeIcon(runtime: SessionRuntimeState, showSuccessState: boolean): JSX.Element {
  if (runtime.sessionState === "running") {
    return <Loader className="h-3.5 w-3.5 shrink-0 animate-spin text-neutral-400" />;
  }
  if (runtime.sessionState === "waiting_user_input") {
    return <CirclePause className="h-3.5 w-3.5 shrink-0 text-amber-500" />;
  }
  if (showSuccessState) {
    return <CheckCircle className="status-success-settle h-3.5 w-3.5 shrink-0" />;
  }
  return <CheckCircle className="h-3.5 w-3.5 shrink-0 text-neutral-400" />;
}

function shortenFileRefs(text: string): string {
  return text.replace(/@[\w./\\-]+\/([^/\s]+)/g, "@$1");
}

export function SessionCard({
  session,
  active,
  runtime,
  onClick,
  onToggleArchive,
}: SessionCardProps): JSX.Element {
  const [showSuccessState, setShowSuccessState] = useState(false);
  const previousSessionStateRef = useRef(runtime.sessionState);
  const successAnimationFrameRef = useRef<number | null>(null);
  const successTimeoutRef = useRef<number | null>(null);
  const title = shortenFileRefs(getSessionTitle(session));
  const excerpt = shortenFileRefs(getSessionExcerpt(session));
  const updatedAt = formatRelativeTime(session.updated_at);
  const messageCountLabel =
    session.messages_count >= 0 ? `${session.messages_count} messages` : "N/A messages";
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
      <button
        className={cn(
          "w-full rounded-lg px-2 py-2 text-left transition-colors",
          showSuccessState
            ? active
              ? "status-success-card-settle-active"
              : "status-success-card-settle"
            : active
              ? "bg-neutral-200/60"
              : "hover:bg-neutral-100/80",
        )}
        type="button"
        onClick={onClick}
        title={title}
      >
        <div className="min-w-0 pl-1">
          <div className="flex min-w-0 items-center gap-1.5">
            {getRuntimeIcon(runtime, showSuccessState)}
            <span className="flex-1 truncate text-[14px] leading-5 text-neutral-700">{title}</span>
            <div className="relative h-5 shrink-0 -translate-y-0.5">
              <span className="whitespace-nowrap text-[12px] leading-5 text-neutral-400 transition-opacity group-focus-within:opacity-0 group-hover:opacity-0">
                {updatedAt}
              </span>
              <button
                type="button"
                className="absolute inset-0 inline-flex items-center justify-end rounded text-neutral-400 opacity-0 transition-opacity hover:text-neutral-700 focus:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100"
                title={session.archived ? "Unarchive session" : "Archive session"}
                aria-label={session.archived ? "Unarchive session" : "Archive session"}
                onClick={(event) => {
                  event.stopPropagation();
                  onToggleArchive(session.id, !session.archived);
                }}
              >
                {session.archived ? (
                  <ArchiveRestore className="h-3.5 w-3.5" />
                ) : (
                  <Archive className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>

          <div className="mt-0.5 truncate pl-5 text-[13px] leading-5 text-neutral-500">
            {excerpt}
          </div>

          <div className="mt-0.5 truncate pl-5 text-[11px] leading-4 text-neutral-400">
            {messageCountLabel} · {modelLabel}
          </div>
        </div>
      </button>
    </div>
  );
}
