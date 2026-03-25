import { Archive, ArchiveRestore, CirclePause } from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "@/types/session";
import { cn } from "@/lib/utils";
import { SessionTitleText } from "@/components/SessionTitleText";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/i18n";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  hasUnreadCompletion: boolean;
  onClick: () => void;
  onToggleArchive: (sessionId: string, archived: boolean) => void;
}

function getSessionTitle(session: SessionSummary): string | null {
  const generatedTitle = session.title?.trim();
  if (generatedTitle !== undefined && generatedTitle.length > 0) {
    return generatedTitle;
  }
  if (session.user_messages.length > 0) {
    const firstMessage = session.user_messages[0].trim();
    if (firstMessage.length > 0) {
      return firstMessage.length > 40 ? `${firstMessage.slice(0, 40)}...` : firstMessage;
    }
  }
  return null;
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

function DiffStats({
  added,
  removed,
  className,
}: {
  added: number;
  removed: number;
  className?: string;
}): React.JSX.Element | null {
  if (added <= 0 && removed <= 0) {
    return null;
  }
  return (
    <span
      className={cn("inline-flex shrink-0 gap-1 whitespace-nowrap text-xs leading-4", className)}
    >
      {added > 0 ? <span className="text-emerald-600">+{added}</span> : null}
      {removed > 0 ? <span className="text-red-600">-{removed}</span> : null}
    </span>
  );
}

export function SessionCard({
  session,
  active,
  runtime,
  hasUnreadCompletion,
  onClick,
  onToggleArchive,
}: SessionCardProps): React.JSX.Element {
  const t = useT();

  const title = shortenFileRefs(getSessionTitle(session) ?? t("sidebar.newSession"));
  const updatedAtDetailed = formatDetailedTime(session.updated_at);
  const relativeTime = formatRelativeTime(session.updated_at);
  const diffSummary = session.file_change_summary;

  return (
    <div
      className={cn(
        "group relative flex min-w-0 items-center gap-1.5 rounded-md py-1.5 pl-2 pr-2 text-left transition-colors",
        active ? "bg-neutral-200/60" : "hover:bg-muted/80",
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
      {runtime.sessionState === "waiting_user_input" ? (
        <span className="flex h-3 w-3 shrink-0 items-center justify-center">
          <CirclePause className="h-3 w-3 text-amber-500" />
        </span>
      ) : null}
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <SessionTitleText
          title={title}
          as="div"
          className="flex min-w-0 items-baseline text-sm leading-5"
          primaryClassName={runtime.sessionState === "running" ? "text-shimmer" : undefined}
          secondaryClassName="shrink truncate"
        />
        {hasUnreadCompletion ? (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
        ) : null}
      </div>
      {/* Meta info: visible by default, hidden on hover */}
      <DiffStats
        added={diffSummary.diff_lines_added}
        removed={diffSummary.diff_lines_removed}
        className="group-hover:hidden"
      />
      <span
        className="w-7 shrink-0 text-right text-xs leading-4 text-neutral-500 group-hover:hidden"
        title={updatedAtDetailed}
      >
        {relativeTime}
      </span>
      {/* Archive button: hidden by default, shown on hover */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="hidden h-5 w-5 shrink-0 items-center justify-center rounded-md text-neutral-500 hover:text-neutral-700 focus:outline-none focus-visible:inline-flex group-hover:inline-flex"
            aria-label={
              session.archived ? t("sidebar.unarchiveSession") : t("sidebar.archiveSession")
            }
            onClick={(e) => {
              e.stopPropagation();
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
          {session.archived ? t("sidebar.unarchiveSession") : t("sidebar.archiveSession")}
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
