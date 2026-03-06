import { useState } from "react";
import { Folder, FolderOpen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SessionCard } from "./SessionCard";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

interface ProjectGroupProps {
  workDir: string;
  sessions: SessionSummary[];
  collapsed: boolean;
  activeSessionId: string | "draft";
  runtimeBySessionId: Record<string, SessionRuntimeState>;
  onToggle: () => void;
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
  activeSessionId,
  runtimeBySessionId,
  onToggle,
  onSelectSession,
  onToggleArchive,
}: ProjectGroupProps): JSX.Element {
  const [showAll, setShowAll] = useState(false);
  const displaySessions = showAll ? sessions : sessions.slice(0, 10);
  const hasMore = sessions.length > 10;

  return (
    <Collapsible open={!collapsed} onOpenChange={onToggle} className="mb-3">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-neutral-700 transition-colors hover:bg-neutral-100/50 hover:text-neutral-900">
        {collapsed ? (
          <Folder className="h-4 w-4 shrink-0 -translate-y-px text-neutral-500 group-hover:text-neutral-700" />
        ) : (
          <FolderOpen className="h-4 w-4 shrink-0 -translate-y-px text-neutral-500 group-hover:text-neutral-700" />
        )}
        <span className="flex-1 truncate text-left text-[13px] font-medium" title={workDir}>
          {workDirLabel(workDir)}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent className="mt-0.5 space-y-0.5">
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
            onClick={() => {
              onSelectSession(session.id);
            }}
            onToggleArchive={onToggleArchive}
          />
        ))}
        {hasMore && !showAll && (
          <button
            type="button"
            className="flex w-full items-center rounded-md px-2 py-[6px] text-left text-neutral-400 transition-colors hover:bg-neutral-100/80 hover:text-neutral-600"
            onClick={(e) => {
              e.stopPropagation();
              setShowAll(true);
            }}
          >
            <span className="flex-1 pl-6 text-[13px] font-normal">
              Load more ({sessions.length - 10})
            </span>
          </button>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
