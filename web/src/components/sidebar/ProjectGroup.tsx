import { useState } from "react";
import { Folder, FolderOpen, SquarePen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SessionCard } from "./SessionCard";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

interface ProjectGroupProps {
  workDir: string;
  sessions: SessionSummary[];
  collapsed: boolean;
  compactSessions?: boolean;
  activeSessionId: string | "draft";
  runtimeBySessionId: Record<string, SessionRuntimeState>;
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
  activeSessionId,
  runtimeBySessionId,
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
      <div className="flex items-start gap-1">
        <CollapsibleTrigger className="group flex min-w-0 flex-1 items-start gap-1.5 rounded-md px-1.5 py-1.5 text-neutral-700 transition-colors hover:bg-neutral-100/50 hover:text-neutral-900">
          {collapsed ? (
            <Folder className="mt-0.5 h-4 w-4 shrink-0 text-neutral-500 group-hover:text-neutral-700" />
          ) : (
            <FolderOpen className="mt-0.5 h-4 w-4 shrink-0 text-neutral-500 group-hover:text-neutral-700" />
          )}
          <div className="min-w-0 flex-1 text-left" title={workDir}>
            <div className="truncate text-sm font-normal leading-5 text-neutral-800">
              {workDirLabel(workDir)}
            </div>
            <div className="mt-0.5 truncate text-2xs leading-4 text-neutral-400" title={workDir}>
              {workDir}
            </div>
          </div>
        </CollapsibleTrigger>
        <button
          type="button"
          className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
          onClick={() => {
            onSelectDraft(workDir);
          }}
          title={`New session in ${workDir}`}
          aria-label={`New session in ${workDir}`}
        >
          <SquarePen className="h-3.5 w-3.5" />
        </button>
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
              className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-neutral-400 transition-colors hover:bg-neutral-100/80 hover:text-neutral-600"
              onClick={(e) => {
                e.stopPropagation();
                setShowAll(true);
              }}
            >
              <span className="flex-1 pl-6 text-xs font-normal">
                Load more ({sessions.length - 10})
              </span>
            </button>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
