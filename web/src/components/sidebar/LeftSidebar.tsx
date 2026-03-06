import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, PanelLeftClose, RefreshCw } from "lucide-react";
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
  const [showRefreshSuccessState, setShowRefreshSuccessState] = useState(false);
  const [archivedCollapsedByWorkDir, setArchivedCollapsedByWorkDir] = useState<
    Record<string, boolean>
  >({});
  const previousLoadingRef = useRef(loading);
  const refreshSuccessAnimationFrameRef = useRef<number | null>(null);
  const refreshSuccessTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    const previousLoading = previousLoadingRef.current;
    previousLoadingRef.current = loading;

    if (previousLoading && !loading) {
      if (refreshSuccessAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(refreshSuccessAnimationFrameRef.current);
      }
      if (refreshSuccessTimeoutRef.current !== null) {
        window.clearTimeout(refreshSuccessTimeoutRef.current);
      }
      refreshSuccessAnimationFrameRef.current = window.requestAnimationFrame(() => {
        setShowRefreshSuccessState(true);
        refreshSuccessAnimationFrameRef.current = null;
        refreshSuccessTimeoutRef.current = window.setTimeout(() => {
          setShowRefreshSuccessState(false);
          refreshSuccessTimeoutRef.current = null;
        }, 1600);
      });
    }
  }, [loading]);

  useEffect(() => {
    return () => {
      if (refreshSuccessAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(refreshSuccessAnimationFrameRef.current);
      }
      if (refreshSuccessTimeoutRef.current !== null) {
        window.clearTimeout(refreshSuccessTimeoutRef.current);
      }
    };
  }, []);

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
    <aside className="flex w-[260px] min-w-[260px] flex-col border-r border-neutral-200 bg-neutral-50">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="flex-1">
          <NewSessionButton onClick={selectDraft} />
        </div>
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
          onClick={() => {
            void refreshSessions();
          }}
          title="Refresh sessions"
          aria-label="Refresh sessions"
        >
          {loading ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : showRefreshSuccessState ? (
            <Check className="status-success-settle h-4 w-4" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </button>
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
          onClick={() => {
            setSidebarOpen(false);
          }}
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <ScrollArea className="min-h-0 w-full flex-1" type="auto">
        <div className="px-3 pb-3">
          {loadError !== null ? (
            <div className="mt-3 rounded-lg border border-dashed border-neutral-300 bg-white p-3">
              <div className="mb-1 font-semibold">Load failed</div>
              <div className="break-words text-sm text-neutral-500">{loadError}</div>
              <button
                type="button"
                className="mt-2 cursor-pointer rounded-md border border-neutral-300 bg-white px-2.5 py-1.5 text-sm"
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
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-neutral-200 border-t-neutral-500" />
              <span className="text-[13px] font-medium">Loading...</span>
            </div>
          ) : null}

          {loadError === null && !loading && groups.length === 0 ? (
            <div className="px-2 py-2 text-neutral-500">
              <div className="text-[13px] font-medium">No sessions yet</div>
              <div className="mt-0.5 text-[12px]">Click "New Agent" above to start</div>
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

      <div className="shrink-0 border-t border-neutral-200 px-3 py-2">
        {archivedExpanded ? (
          archivedGroups.length > 0 ? (
            <ScrollArea className="max-h-[40vh] w-full" viewportClassName="!h-auto max-h-[40vh]">
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
            className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-neutral-500 transition-colors hover:bg-neutral-100/50 hover:text-neutral-900"
            onClick={() => {
              setArchivedExpanded((prev) => !prev);
            }}
          >
            {archivedExpanded ? (
              <ChevronDown className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0" />
            )}
            <span className="flex-1 text-left text-[13px]">Archived</span>
            <span className="text-[12px] text-neutral-400">{archivedSessionCount}</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
