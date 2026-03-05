import { useState } from "react";
import { Folder, FolderOpen, MoreHorizontal } from "lucide-react";
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
}: ProjectGroupProps): JSX.Element {
  const [showAll, setShowAll] = useState(false);
  const displaySessions = showAll ? sessions : sessions.slice(0, 10);
  const hasMore = sessions.length > 10;

  return (
    <Collapsible
      open={!collapsed}
      onOpenChange={onToggle}
      className="mb-3"
    >
      <CollapsibleTrigger className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100/50 transition-colors group">
        {collapsed ? (
          <Folder className="w-4 h-4 shrink-0 text-zinc-400 group-hover:text-zinc-600" />
        ) : (
          <FolderOpen className="w-4 h-4 shrink-0 text-zinc-400 group-hover:text-zinc-600" />
        )}
        <span className="flex-1 text-[13px] font-normal truncate text-left" title={workDir}>
          {workDirLabel(workDir)}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent className="mt-0.5 space-y-0.5">
        {displaySessions.map((session) => (
          <SessionCard
            key={session.id}
            session={session}
            active={activeSessionId === session.id}
            runtime={runtimeBySessionId[session.id] ?? { sessionState: "idle", wsState: "idle", lastError: null }}
            onClick={() => {
              onSelectSession(session.id);
            }}
          />
        ))}
        {hasMore && !showAll && (
          <button
            type="button"
            className="w-full flex items-center px-2 py-[6px] rounded-md text-left transition-colors hover:bg-zinc-100/80 text-zinc-400 hover:text-zinc-600"
            onClick={(e) => {
              e.stopPropagation();
              setShowAll(true);
            }}
          >
            <span className="text-[13px] font-normal flex-1 pl-6">
              Load more ({sessions.length - 10})
            </span>
          </button>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
