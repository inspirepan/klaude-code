import { useState } from "react";
import { Folder, FolderOpen, Loader, SquarePen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SessionCard } from "./SessionCard";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

interface ProjectGroupProps {
  workDir: string;
  sessions: SessionSummary[];
  collapsed: boolean;
  hideNewSessionButton?: boolean;
  activeSessionId: string | "draft";
  runtimeBySessionId: Record<string, SessionRuntimeState>;
  recentCompletionStartedAtBySessionId: Record<string, number>;
  completedUnreadBySessionId: Record<string, boolean>;
  onToggle: () => void;
  onSelectDraft: (workDir: string) => void;
  onSelectSession: (sessionId: string) => void;
  onToggleArchive: (sessionId: string, archived: boolean) => void;
}

function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((segment) => segment.length > 0);
  if (parts.length === 0) {
    return workDir;
  }
  return parts[parts.length - 1] ?? workDir;
}

export function ProjectGroup({
  workDir,
  sessions,
  collapsed,
  hideNewSessionButton = false,
  activeSessionId,
  runtimeBySessionId,
  recentCompletionStartedAtBySessionId,
  completedUnreadBySessionId,
  onToggle,
  onSelectDraft,
  onSelectSession,
  onToggleArchive,
}: ProjectGroupProps): JSX.Element {
  const [showAll, setShowAll] = useState(false);
  const displaySessions = showAll ? sessions : sessions.slice(0, 5);
  const hasMore = sessions.length > 5;
  const hasAnyRunning =
    collapsed &&
    sessions.some((s) => {
      const state = runtimeBySessionId[s.id]?.sessionState ?? s.session_state;
      return state !== "idle";
    });
  const hasAnyUnread =
    !hasAnyRunning && collapsed && sessions.some((s) => completedUnreadBySessionId[s.id] === true);

  return (
    <Collapsible open={!collapsed} onOpenChange={onToggle} className="mb-0.5">
      <div className="flex items-center gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <CollapsibleTrigger className="group flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-neutral-700 transition-colors hover:bg-muted/50 hover:text-neutral-900">
              {collapsed ? (
                <Folder className="h-3.5 w-3.5 shrink-0 text-neutral-500" />
              ) : (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-neutral-500" />
              )}
              <div className="min-w-0 flex-1 text-left">
                <div className="flex min-w-0 items-center gap-1 text-sm font-normal leading-5 text-neutral-800">
                  <span className="truncate font-medium text-neutral-500 [direction:rtl]">
                    {workDirLabel(workDir)}
                  </span>
                  <span className="shrink-0 text-xs text-neutral-400">({sessions.length})</span>
                  {hasAnyRunning ? (
                    <Loader className="h-3 w-3 shrink-0 animate-spin text-neutral-500" />
                  ) : hasAnyUnread ? (
                    <span className="flex h-3 w-3 shrink-0 items-center justify-center">
                      <span className="h-1.5 w-1.5 rounded-full bg-green-600" />
                    </span>
                  ) : null}
                </div>
              </div>
            </CollapsibleTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom">{workDir}</TooltipContent>
        </Tooltip>
        {hideNewSessionButton ? null : (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-700"
                onClick={() => {
                  onSelectDraft(workDir);
                }}
                aria-label={`New session in ${workDir}`}
              >
                <SquarePen className="h-3 w-3" />
              </button>
            </TooltipTrigger>
            <TooltipContent>New session in {workDir}</TooltipContent>
          </Tooltip>
        )}
      </div>

      <CollapsibleContent className="ml-3 border-l border-neutral-200 pl-1.5">
        <div className="space-y-0.5 pb-0.5">
          {displaySessions.map((session) => (
            <SessionCard
              key={session.id}
              session={session}
              active={activeSessionId === session.id}
              runtime={
                runtimeBySessionId[session.id] ?? {
                  sessionState: "idle",
                  wsState: "idle",
                  lastError: null,
                }
              }
              hasUnreadCompletion={completedUnreadBySessionId[session.id] === true}
              completionAnimationStartedAt={recentCompletionStartedAtBySessionId[session.id]}
              onClick={() => {
                onSelectSession(session.id);
              }}
              onToggleArchive={onToggleArchive}
            />
          ))}
          {hasMore && !showAll && (
            <button
              type="button"
              className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-neutral-500 transition-colors hover:bg-muted/80 hover:text-neutral-700"
              onClick={(e) => {
                e.stopPropagation();
                setShowAll(true);
              }}
            >
              <span className="flex-1 text-xs font-normal">Load more ({sessions.length - 5})</span>
            </button>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
