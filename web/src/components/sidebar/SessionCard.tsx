import { Archive, ArchiveRestore, CheckCircle, CirclePause, Loader } from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

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

function getRuntimeIcon(runtime: SessionRuntimeState): JSX.Element {
  if (runtime.sessionState === "running") {
    return <Loader className="shrink-0 w-3.5 h-3.5 text-neutral-400 animate-spin" />;
  }
  if (runtime.sessionState === "waiting_user_input") {
    return <CirclePause className="shrink-0 w-3.5 h-3.5 text-amber-500" />;
  }
  return <CheckCircle className="shrink-0 w-3.5 h-3.5 text-neutral-400" />;
}

function shortenFileRefs(text: string): string {
  return text.replace(/@[\w./\\-]+\/([^/\s]+)/g, "@$1");
}

export function SessionCard({ session, active, runtime, onClick, onToggleArchive }: SessionCardProps): JSX.Element {
  const title = shortenFileRefs(getSessionTitle(session));
  const excerpt = shortenFileRefs(getSessionExcerpt(session));
  const updatedAt = formatRelativeTime(session.updated_at);
  const messageCountLabel = session.messages_count >= 0 ? `${session.messages_count} messages` : "N/A messages";
  const modelLabel = session.model_name ?? "N/A model";

  return (
    <div className="group">
      <button
        className={`w-full rounded-md px-2 py-2 text-left transition-colors ${
          active ? "bg-neutral-200/60" : "hover:bg-neutral-100/80"
        }`}
        type="button"
        onClick={onClick}
        title={title}
      >
        <div className="min-w-0 pl-1">
          <div className="flex items-center gap-1.5 min-w-0">
            {getRuntimeIcon(runtime)}
            <span className="text-[14px] leading-5 text-neutral-700 truncate flex-1">{title}</span>
            <div className="relative shrink-0 h-5 -translate-y-0.5">
              <span className="text-[12px] leading-5 text-neutral-400 whitespace-nowrap transition-opacity group-hover:opacity-0 group-focus-within:opacity-0">
                {updatedAt}
              </span>
              <button
                type="button"
                className="absolute inset-0 inline-flex items-center justify-end rounded text-neutral-400 opacity-0 transition-opacity hover:text-neutral-700 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100"
                title={session.archived ? "Unarchive session" : "Archive session"}
                aria-label={session.archived ? "Unarchive session" : "Archive session"}
                onClick={(event) => {
                  event.stopPropagation();
                  onToggleArchive(session.id, !session.archived);
                }}
              >
                {session.archived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>

          <div className="mt-0.5 pl-5 text-[13px] leading-5 text-neutral-500 truncate">{excerpt}</div>

          <div className="mt-0.5 pl-5 text-[11px] leading-4 text-neutral-400 truncate">
            {messageCountLabel} · {modelLabel}
          </div>
        </div>
      </button>
    </div>
  );
}
