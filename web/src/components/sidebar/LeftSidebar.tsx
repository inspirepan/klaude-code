import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, PanelLeftClose, RefreshCw } from "lucide-react";
import { NewSessionButton } from "./NewSessionButton";
import { ProjectGroup } from "./ProjectGroup";
import { useSessionStore } from "../../stores/session-store";
import { useAppStore } from "../../stores/app-store";
import { ScrollArea } from "@/components/ui/scroll-area";

export function LeftSidebar(): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const collapsedByWorkDir = useSessionStore((state) => state.collapsedByWorkDir);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const loading = useSessionStore((state) => state.loading);
  const loadError = useSessionStore((state) => state.loadError);
  const selectDraft = useSessionStore((state) => state.selectDraft);
  const toggleGroup = useSessionStore((state) => state.toggleGroup);
  const setSessionArchived = useSessionStore((state) => state.setSessionArchived);
  const selectSession = useSessionStore((state) => state.selectSession);
  const refreshSessions = useSessionStore((state) => state.refreshSessions);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const [archivedExpanded, setArchivedExpanded] = useState(false);
  const [archivedCollapsedByWorkDir, setArchivedCollapsedByWorkDir] = useState<Record<string, boolean>>({});

  const activeGroups = useMemo(
    () =>
      groups
        .map((group) => ({
          ...group,
          sessions: group.sessions.filter((session) => !session.archived),
        }))
        .filter((group) => group.sessions.length > 0),
    [groups],
  );

  const archivedGroups = useMemo(
    () =>
      groups
        .map((group) => ({
          ...group,
          sessions: group.sessions.filter((session) => session.archived),
        }))
        .filter((group) => group.sessions.length > 0)
        .sort((a, b) => (b.sessions[0]?.updated_at ?? 0) - (a.sessions[0]?.updated_at ?? 0)),
    [groups],
  );

  const archivedSessionCount = useMemo(
    () => archivedGroups.reduce((count, group) => count + group.sessions.length, 0),
    [archivedGroups],
  );

  return (
    <aside className="w-[260px] min-w-[260px] border-r border-neutral-200 bg-neutral-50 flex flex-col">
      <div className="p-3 flex items-center gap-2">
        <div className="flex-1">
          <NewSessionButton onClick={selectDraft} />
        </div>
        <button
          type="button"
          className="h-10 w-10 shrink-0 inline-flex items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
          onClick={() => {
            void refreshSessions();
          }}
          title="Refresh sessions"
          aria-label="Refresh sessions"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
        <button
          type="button"
          className="h-10 w-10 shrink-0 inline-flex items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
          onClick={() => {
            setSidebarOpen(false);
          }}
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      <ScrollArea className="flex-1 w-full min-h-0" type="auto">
        <div className="px-3 pb-3">
          {loadError !== null ? (
            <div className="mt-3 p-3 border border-dashed border-neutral-300 rounded-lg bg-white">
              <div className="font-semibold mb-1">Load failed</div>
              <div className="text-sm text-neutral-500 break-words">{loadError}</div>
              <button
                type="button"
                className="mt-2 border border-neutral-300 rounded-md bg-white px-2.5 py-1.5 text-sm cursor-pointer"
                onClick={() => {
                  void refreshSessions();
                }}
              >
                Click to retry
              </button>
            </div>
          ) : null}

          {loadError === null && loading && groups.length === 0 ? (
            <div className="flex items-center gap-2 px-2 py-2 text-neutral-500">
              <div className="w-4 h-4 rounded-full border-2 border-neutral-200 border-t-neutral-500 animate-spin" />
              <span className="text-[13px] font-medium">Loading...</span>
            </div>
          ) : null}

          {loadError === null && !loading && groups.length === 0 ? (
            <div className="px-2 py-2 text-neutral-500">
              <div className="text-[13px] font-medium">No sessions yet</div>
              <div className="text-[12px] mt-0.5">Click "New Agent" above to start</div>
            </div>
          ) : null}

          {activeGroups.map((group) => (
            <ProjectGroup
              key={group.work_dir}
              workDir={group.work_dir}
              sessions={group.sessions}
              collapsed={collapsedByWorkDir[group.work_dir] ?? false}
              activeSessionId={activeSessionId}
              runtimeBySessionId={runtimeBySessionId}
              onToggle={() => {
                toggleGroup(group.work_dir);
              }}
              onSelectSession={(sessionId) => {
                void selectSession(sessionId);
              }}
              onToggleArchive={(sessionId, archived) => {
                void setSessionArchived(sessionId, archived);
              }}
            />
          ))}

        </div>
      </ScrollArea>

      <div className="border-t border-neutral-200 px-3 py-2 shrink-0">
        {archivedExpanded ? (
          archivedGroups.length > 0 ? (
            <ScrollArea className="w-full max-h-[40vh]" viewportClassName="!h-auto max-h-[40vh]">
              <div className="pt-1">
                {archivedGroups.map((group) => (
                  <ProjectGroup
                    key={`archived-${group.work_dir}`}
                    workDir={group.work_dir}
                    sessions={group.sessions}
                    collapsed={archivedCollapsedByWorkDir[group.work_dir] ?? false}
                    activeSessionId={activeSessionId}
                    runtimeBySessionId={runtimeBySessionId}
                    onToggle={() => {
                      setArchivedCollapsedByWorkDir((prev) => ({
                        ...prev,
                        [group.work_dir]: !(prev[group.work_dir] ?? false),
                      }));
                    }}
                    onSelectSession={(sessionId) => {
                      void selectSession(sessionId);
                    }}
                    onToggleArchive={(sessionId, archived) => {
                      void setSessionArchived(sessionId, archived);
                    }}
                  />
                ))}
              </div>
            </ScrollArea>
          ) : (
            <div className="px-2 py-1 text-[12px] text-neutral-400">No archived sessions</div>
          )
        ) : null}

        <div className={archivedExpanded ? "mt-1.5" : undefined}>
          <button
            type="button"
            className="w-full flex items-center gap-1 px-2 py-1.5 rounded-md text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100/50 transition-colors"
            onClick={() => {
              setArchivedExpanded((prev) => !prev);
            }}
          >
            {archivedExpanded ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
            <span className="flex-1 text-[13px] text-left">Archived</span>
            <span className="text-[12px] text-neutral-400">{archivedSessionCount}</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
