import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, FolderTree, List, PanelLeftClose } from "lucide-react";
import { NewSessionButton } from "./NewSessionButton";
import { ProjectGroup } from "./ProjectGroup";
import { SessionCard } from "./SessionCard";
import { useSessionStore } from "../../stores/session-store";
import { useAppStore } from "../../stores/app-store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function LeftSidebar(): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const collapsedByWorkDir = useSessionStore((state) => state.collapsedByWorkDir);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const completedUnreadBySessionId = useSessionStore((state) => state.completedUnreadBySessionId);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const draftWorkDir = useSessionStore((state) => state.draftWorkDir);
  const loading = useSessionStore((state) => state.loading);
  const loadError = useSessionStore((state) => state.loadError);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const toggleGroup = useSessionStore((state) => state.toggleGroup);
  const setSessionArchived = useSessionStore((state) => state.setSessionArchived);
  const selectSession = useSessionStore((state) => state.selectSession);
  const refreshSessions = useSessionStore((state) => state.refreshSessions);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);
  const [archivedMenuOpen, setArchivedMenuOpen] = useState(false);
  const [sessionListView, setSessionListView] = useState<"grouped" | "flat">("flat");
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const [archiveUndoSessionId, setArchiveUndoSessionId] = useState<string | null>(null);
  const [archivedCollapsedByWorkDir, setArchivedCollapsedByWorkDir] = useState<
    Record<string, boolean>
  >({});
  const sidebarRef = useRef<HTMLElement | null>(null);
  const archivedMenuRef = useRef<HTMLDivElement | null>(null);
  const archiveUndoTimeoutRef = useRef<number | null>(null);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);

  const clampSidebarWidth = (width: number): number => {
    const minWidth = 256;
    const hardMaxWidth = 512;
    const rightSidebarWidth =
      (document.querySelector('[data-sidebar="right"]') as HTMLElement | null)?.offsetWidth ?? 0;
    const minMainWidth = 320;
    const availableMaxWidth = window.innerWidth - rightSidebarWidth - minMainWidth;
    const maxWidth = Math.max(minWidth, Math.min(hardMaxWidth, availableMaxWidth));
    return Math.min(Math.max(width, minWidth), maxWidth);
  };

  useEffect(() => {
    return () => {
      if (archiveUndoTimeoutRef.current !== null) {
        window.clearTimeout(archiveUndoTimeoutRef.current);
      }
      if (sidebarResizeCleanupRef.current !== null) {
        sidebarResizeCleanupRef.current();
        sidebarResizeCleanupRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!archivedMenuOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent): void => {
      if (!archivedMenuRef.current?.contains(event.target as Node)) {
        setArchivedMenuOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setArchivedMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [archivedMenuOpen]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey || event.key.toLowerCase() !== "v") {
        return;
      }

      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }

      event.preventDefault();
      setSessionListView((prev) => (prev === "grouped" ? "flat" : "grouped"));
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const activeGroups = useMemo(
    () =>
      groups
        .map((group) => ({
          ...group,
          sessions: group.sessions.filter((session) => !session.archived),
        }))
        .filter((group) => group.sessions.length > 0)
        .sort((a, b) => a.work_dir.localeCompare(b.work_dir)),
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
        .sort((a, b) => a.work_dir.localeCompare(b.work_dir)),
    [groups],
  );

  const archivedSessionCount = useMemo(
    () => archivedGroups.reduce((count, group) => count + group.sessions.length, 0),
    [archivedGroups],
  );

  const activeSessions = useMemo(
    () =>
      groups
        .flatMap((group) => group.sessions)
        .filter((session) => !session.archived)
        .sort((a, b) => b.updated_at - a.updated_at),
    [groups],
  );

  const inProgressSessions = useMemo(
    () =>
      activeSessions.filter((session) => {
        const sessionState = runtimeBySessionId[session.id]?.sessionState ?? session.session_state;
        return sessionState !== "idle";
      }),
    [activeSessions, runtimeBySessionId],
  );

  const doneSessions = useMemo(
    () =>
      activeSessions.filter((session) => {
        const sessionState = runtimeBySessionId[session.id]?.sessionState ?? session.session_state;
        return sessionState === "idle";
      }),
    [activeSessions, runtimeBySessionId],
  );

  const activeSession = useMemo(
    () =>
      activeSessionId === "draft"
        ? null
        : (groups
            .flatMap((group) => group.sessions)
            .find((session) => session.id === activeSessionId) ?? null),
    [activeSessionId, groups],
  );

  const openNewSessionOverlay = (workDir?: string): void => {
    const normalizedWorkDir = workDir?.trim() ?? "";
    setDraftWorkDir(normalizedWorkDir || activeSession?.work_dir || draftWorkDir);
    setNewSessionOverlayOpen(activeSessionId !== "draft");
    window.dispatchEvent(new Event("klaude:draft-focus-input"));
  };

  const showArchiveUndoToast = (sessionId: string): void => {
    if (archiveUndoTimeoutRef.current !== null) {
      window.clearTimeout(archiveUndoTimeoutRef.current);
    }
    setArchiveUndoSessionId(sessionId);
    archiveUndoTimeoutRef.current = window.setTimeout(() => {
      setArchiveUndoSessionId(null);
      archiveUndoTimeoutRef.current = null;
    }, 4500);
  };

  const dismissArchiveUndoToast = (): void => {
    if (archiveUndoTimeoutRef.current !== null) {
      window.clearTimeout(archiveUndoTimeoutRef.current);
      archiveUndoTimeoutRef.current = null;
    }
    setArchiveUndoSessionId(null);
  };

  const handleToggleArchive = (sessionId: string, archived: boolean): void => {
    void (async () => {
      await setSessionArchived(sessionId, archived);
      if (archived) {
        showArchiveUndoToast(sessionId);
      } else if (archiveUndoSessionId === sessionId) {
        dismissArchiveUndoToast();
      }
    })();
  };

  return (
    <aside
      ref={sidebarRef}
      data-sidebar="left"
      className="relative flex shrink-0 flex-col border-r border-neutral-200 bg-neutral-50"
      style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
    >
      <div className="flex items-center gap-1.5 px-3 py-2">
        <div className="flex-1">
          <NewSessionButton
            onClick={() => {
              openNewSessionOverlay();
            }}
          />
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              onClick={() => {
                setSessionListView((prev) => (prev === "grouped" ? "flat" : "grouped"));
              }}
              aria-label={
                sessionListView === "grouped" ? "Switch to flat view" : "Switch to grouped view"
              }
            >
              {sessionListView === "grouped" ? (
                <List className="h-4 w-4" />
              ) : (
                <FolderTree className="h-4 w-4" />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent className="flex items-center gap-1.5">
            <span>
              {sessionListView === "grouped" ? "Switch to flat view" : "Switch to grouped view"}
            </span>
            <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
              <span className="inline-flex whitespace-pre text-xs leading-none">
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⇧</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⌘</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">V</span>
                </kbd>
              </span>
            </span>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              onClick={() => {
                setSidebarOpen(false);
              }}
              aria-label="Collapse sidebar"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent className="flex items-center gap-1.5">
            <span>Collapse sidebar</span>
            <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
              <span className="inline-flex whitespace-pre text-xs leading-none">
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⌘</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">B</span>
                </kbd>
              </span>
            </span>
          </TooltipContent>
        </Tooltip>
      </div>

      <ScrollArea className="min-h-0 w-full flex-1" type="auto">
        <div className="px-2.5 pb-3">
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
              <span className="text-xs font-semibold">Loading…</span>
            </div>
          ) : null}

          {loadError === null && !loading && groups.length === 0 ? (
            <div className="px-2 py-2 text-neutral-500">
              <div className="text-xs font-semibold">No sessions yet</div>
              <div className="mt-0.5 text-2xs">Click "New Agent" above to start</div>
            </div>
          ) : null}

          {sessionListView === "grouped" ? (
            activeGroups.map((group) => (
              <ProjectGroup
                key={group.work_dir}
                workDir={group.work_dir}
                sessions={group.sessions}
                collapsed={collapsedByWorkDir[group.work_dir] ?? false}
                activeSessionId={activeSessionId}
                runtimeBySessionId={runtimeBySessionId}
                completedUnreadBySessionId={completedUnreadBySessionId}
                onToggle={() => {
                  toggleGroup(group.work_dir);
                }}
                onSelectDraft={(workDir) => {
                  openNewSessionOverlay(workDir);
                }}
                onSelectSession={(sessionId) => {
                  setNewSessionOverlayOpen(false);
                  void selectSession(sessionId);
                }}
                onToggleArchive={(sessionId, archived) => {
                  handleToggleArchive(sessionId, archived);
                }}
              />
            ))
          ) : (
            <div className="space-y-4 pt-2">
              <div>
                <div className="mb-2 flex items-center gap-1.5 px-1.5">
                  <span className="text-2xs font-medium uppercase tracking-[0.02em] text-neutral-500">
                    In Progress
                  </span>
                  <span className="text-2xs text-neutral-400">{inProgressSessions.length}</span>
                </div>
                {inProgressSessions.length > 0 ? (
                  <div className="space-y-1">
                    {inProgressSessions.map((session) => (
                      <SessionCard
                        key={session.id}
                        session={session}
                        active={activeSessionId === session.id}
                        runtime={
                          runtimeBySessionId[session.id] ?? {
                            sessionState: session.session_state,
                            wsState: "idle",
                            lastError: null,
                          }
                        }
                        hasUnreadCompletion={completedUnreadBySessionId[session.id] === true}
                        showWorkspace
                        onClick={() => {
                          setNewSessionOverlayOpen(false);
                          void selectSession(session.id);
                        }}
                        onToggleArchive={(sessionId, archived) => {
                          handleToggleArchive(sessionId, archived);
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="px-1.5 py-1 text-2xs text-neutral-400">
                    No in-progress sessions
                  </div>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center gap-1.5 px-1.5">
                  <span className="text-2xs font-medium uppercase tracking-[0.02em] text-neutral-500">
                    Done
                  </span>
                  <span className="text-2xs text-neutral-400">{doneSessions.length}</span>
                </div>
                {doneSessions.length > 0 ? (
                  <div className="space-y-1">
                    {doneSessions.map((session) => (
                      <SessionCard
                        key={session.id}
                        session={session}
                        active={activeSessionId === session.id}
                        runtime={
                          runtimeBySessionId[session.id] ?? {
                            sessionState: session.session_state,
                            wsState: "idle",
                            lastError: null,
                          }
                        }
                        hasUnreadCompletion={completedUnreadBySessionId[session.id] === true}
                        showWorkspace
                        onClick={() => {
                          setNewSessionOverlayOpen(false);
                          void selectSession(session.id);
                        }}
                        onToggleArchive={(sessionId, archived) => {
                          handleToggleArchive(sessionId, archived);
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="px-1.5 py-1 text-2xs text-neutral-400">No done sessions</div>
                )}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      <div className="relative shrink-0 px-3 py-2">
        <div ref={archivedMenuRef} className="relative">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                onClick={() => {
                  setArchivedMenuOpen((prev) => !prev);
                }}
                aria-label="Archived sessions"
              >
                <Archive className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent>Archived sessions</TooltipContent>
          </Tooltip>

          {archivedMenuOpen ? (
            <div className="absolute bottom-full left-0 z-40 mb-2 w-[320px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-neutral-200/80 bg-white p-1 shadow-[0_8px_30px_rgba(0,0,0,0.08)]">
              <div className="flex items-center justify-between border-b border-neutral-100 px-2 py-1.5">
                <span className="text-2xs font-medium uppercase tracking-[0.08em] text-neutral-500">
                  Archived
                </span>
                <span className="text-2xs text-neutral-400">{archivedSessionCount}</span>
              </div>
              {archivedGroups.length > 0 ? (
                <ScrollArea className="w-full" viewportClassName="max-h-80" type="auto">
                  <div className="pt-1">
                    {archivedGroups.map((group) => (
                      <ProjectGroup
                        key={`archived-${group.work_dir}`}
                        workDir={group.work_dir}
                        sessions={group.sessions}
                        collapsed={archivedCollapsedByWorkDir[group.work_dir] ?? false}
                        compactSessions
                        compactHeader
                        hideNewSessionButton
                        activeSessionId={activeSessionId}
                        runtimeBySessionId={runtimeBySessionId}
                        completedUnreadBySessionId={completedUnreadBySessionId}
                        onToggle={() => {
                          setArchivedCollapsedByWorkDir((prev) => ({
                            ...prev,
                            [group.work_dir]: !(prev[group.work_dir] ?? false),
                          }));
                        }}
                        onSelectDraft={(workDir) => {
                          setArchivedMenuOpen(false);
                          openNewSessionOverlay(workDir);
                        }}
                        onSelectSession={(sessionId) => {
                          setArchivedMenuOpen(false);
                          setNewSessionOverlayOpen(false);
                          void selectSession(sessionId);
                        }}
                        onToggleArchive={(sessionId, archived) => {
                          handleToggleArchive(sessionId, archived);
                        }}
                      />
                    ))}
                  </div>
                </ScrollArea>
              ) : (
                <div className="px-3 py-3 text-xs text-neutral-400">No archived sessions</div>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {archiveUndoSessionId !== null ? (
        <div className="pointer-events-none absolute inset-x-2 bottom-2 z-40">
          <div className="pointer-events-auto flex items-center justify-between gap-2 rounded-lg border border-neutral-200 bg-white/95 px-2.5 py-2 shadow-[0_8px_24px_-16px_rgba(15,15,15,0.35)] backdrop-blur">
            <span className="text-xs text-neutral-700">Session archived</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="cursor-pointer rounded-md px-2 py-1 text-xs font-medium text-neutral-600 transition-colors hover:bg-neutral-100 hover:text-neutral-900"
                  onClick={() => {
                    const sessionId = archiveUndoSessionId;
                    dismissArchiveUndoToast();
                    if (sessionId !== null) {
                      void setSessionArchived(sessionId, false);
                    }
                  }}
                >
                  Undo
                </button>
              </TooltipTrigger>
              <TooltipContent>Undo archive</TooltipContent>
            </Tooltip>
          </div>
        </div>
      ) : null}

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize left sidebar"
        className="absolute -right-1 top-0 z-30 flex h-full w-2 cursor-col-resize items-center justify-center"
        onPointerDown={(event) => {
          event.preventDefault();
          const startX = event.clientX;
          const startWidth = sidebarWidth;
          const onPointerMove = (moveEvent: PointerEvent): void => {
            const deltaX = moveEvent.clientX - startX;
            setSidebarWidth(clampSidebarWidth(startWidth + deltaX));
          };
          const onPointerUp = (): void => {
            cleanup();
            sidebarResizeCleanupRef.current = null;
          };
          const cleanup = (): void => {
            window.removeEventListener("pointermove", onPointerMove);
            window.removeEventListener("pointerup", onPointerUp);
          };

          if (sidebarResizeCleanupRef.current !== null) {
            sidebarResizeCleanupRef.current();
          }
          sidebarResizeCleanupRef.current = cleanup;
          window.addEventListener("pointermove", onPointerMove);
          window.addEventListener("pointerup", onPointerUp);
        }}
      >
        <span className="h-full w-px bg-neutral-200/85" />
      </div>
    </aside>
  );
}
