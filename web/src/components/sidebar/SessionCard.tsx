import { Archive, ArchiveRestore, CheckCircle, Loader } from "lucide-react";
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
  if (session.user_messages.length > 1) {
    return session.user_messages[session.user_messages.length - 1] ?? "Restored session";
  }
  if (session.messages_count > 1) {
    return `${session.messages_count} messages`;
  }
  return session.model_name ? `Model: ${session.model_name}` : "Draft session";
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

export function SessionCard({ session, active, runtime, onClick, onToggleArchive }: SessionCardProps): JSX.Element {
  const title = getSessionTitle(session);
  const updatedAt = formatRelativeTime(session.updated_at);

  return (
    <div className="group relative">
      <button
        className={`w-full flex items-center justify-between gap-3 px-2 py-[6px] rounded-md text-left transition-colors ${
          active ? "bg-zinc-200/60" : "hover:bg-zinc-100/80"
        }`}
        type="button"
        onClick={onClick}
        title={title}
      >
        <span className="text-[14px] text-zinc-700 font-normal truncate flex-1 pl-1 flex items-center gap-1.5">
          {runtime.sessionState !== "idle" ? (
            <Loader className="shrink-0 w-3.5 h-3.5 text-zinc-400 animate-spin" />
          ) : (
            <CheckCircle className="shrink-0 w-3.5 h-3.5 text-zinc-400" />
          )}
          {title}
        </span>
        <span className="text-[13px] text-zinc-400 shrink-0 transition-opacity group-hover:opacity-0">{updatedAt}</span>
      </button>

      <button
        type="button"
        className="absolute right-1 top-1/2 -translate-y-1/2 inline-flex h-6 w-6 items-center justify-center rounded text-zinc-400 opacity-0 transition-opacity hover:bg-zinc-200/60 hover:text-zinc-700 group-hover:opacity-100 focus:opacity-100"
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
  );
}
