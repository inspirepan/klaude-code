import { useState } from "react";
import { Folder, FolderOpen, SquarePen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SessionCard } from "./SessionCard";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

interface ProjectGroupProps {
  workDir: string;
  sessions: SessionSummary[];
  collapsed: boolean;
  compactSessions?: boolean;
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
  compactSessions = false,
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
  const displaySessions = showAll ? sessions : sessions.slice(0, 10);
  const hasMore = sessions.length > 10;

  return (
    <Collapsible open={!collapsed} onOpenChange={onToggle} className="mb-1.5">
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <CollapsibleTrigger className="group flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1.5 text-neutral-700 transition-colors hover:bg-muted/50 hover:text-neutral-900">
              {collapsed ? (
                <Folder className="h-4 w-4 shrink-0 text-neutral-700" />
              ) : (
                <FolderOpen className="h-4 w-4 shrink-0 text-neutral-700" />
              )}
              <div className="min-w-0 flex-1 text-left">
                <div className="flex min-w-0 items-center gap-1 text-base font-normal leading-5 text-neutral-800">
                  <span className="truncate font-semibold text-neutral-700">
                    {workDirLabel(workDir)}
                  </span>
                  <span className="shrink-0 text-neutral-500">({sessions.length})</span>
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
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-700"
                onClick={() => {
                  onSelectDraft(workDir);
                }}
                aria-label={`New session in ${workDir}`}
              >
                <SquarePen className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent>New session in {workDir}</TooltipContent>
          </Tooltip>
        )}
      </div>

      <CollapsibleContent className="ml-3.5 border-l border-neutral-200 pl-2">
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
              compact={compactSessions}
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
              <span
                className={
                  compactSessions ? "flex-1 text-xs font-normal" : "flex-1 pl-6 text-sm font-normal"
                }
              >
                Load more ({sessions.length - 10})
              </span>
            </button>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
