import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, BrushCleaning, Loader, PanelLeftClose } from "lucide-react";
import { NewSessionButton } from "./NewSessionButton";
import { ProjectGroup } from "./ProjectGroup";
import { SessionCard } from "./SessionCard";
import { useSessionStore } from "../../stores/session-store";
import type { SessionSummary } from "../../types/session";
import { useAppStore } from "../../stores/app-store";
import { useMountEffect } from "@/hooks/useMountEffect";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const ARCHIVE_CLEANUP_AGE_SECONDS = 3 * 24 * 60 * 60;
const DEFAULT_SIDEBAR_WIDTH = 304;
const SIDEBAR_WIDTH_STORAGE_KEY = "klaude:left-sidebar:width";
const ARCHIVED_GROUP_COLLAPSE_STORAGE_KEY = "klaude:left-sidebar:archived-collapsed-groups";

function clampSidebarWidth(width: number): number {
  const minWidth = 256;
  const hardMaxWidth = 512;
  const rightSidebarWidth =
    (document.querySelector('[data-sidebar="right"]') as HTMLElement | null)?.offsetWidth ?? 0;
  const minMainWidth = 320;
  const availableMaxWidth = window.innerWidth - rightSidebarWidth - minMainWidth;
  const maxWidth = Math.max(minWidth, Math.min(hardMaxWidth, availableMaxWidth));
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function readStoredSidebarWidth(): number | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY);
  if (raw === null) {
    return null;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function readStoredCollapsedByWorkDir(storageKey: string): Record<string, boolean> {
  if (typeof window === "undefined") {
    return {};
  }

  const raw = window.localStorage.getItem(storageKey);
  if (raw === null) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }

    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

export function LeftSidebar(): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const collapsedByWorkDir = useSessionStore((state) => state.collapsedByWorkDir);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const recentCompletionStartedAtBySessionId = useSessionStore(
    (state) => state.recentCompletionStartedAtBySessionId,
  );
  const completedUnreadBySessionId = useSessionStore((state) => state.completedUnreadBySessionId);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const loading = useSessionStore((state) => state.loading);
  const loadError = useSessionStore((state) => state.loadError);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const toggleGroup = useSessionStore((state) => state.toggleGroup);
  const setSessionArchived = useSessionStore((state) => state.setSessionArchived);
  const archiveCleanupSessions = useSessionStore((state) => state.archiveCleanupSessions);
  const selectSession = useSessionStore((state) => state.selectSession);
  const refreshSessions = useSessionStore((state) => state.refreshSessions);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);
  const [archivedMenuOpen, setArchivedMenuOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(
    () => readStoredSidebarWidth() ?? DEFAULT_SIDEBAR_WIDTH,
  );
  const [isResizing, setIsResizing] = useState(false);
  const [archiveUndoSessionId, setArchiveUndoSessionId] = useState<string | null>(null);
  const [archiveCleanupConfirmOpen, setArchiveCleanupConfirmOpen] = useState(false);
  const [archiveCleanupPending, setArchiveCleanupPending] = useState(false);
  const [archivedCollapsedByWorkDir, setArchivedCollapsedByWorkDir] = useState<
    Record<string, boolean>
  >(() => readStoredCollapsedByWorkDir(ARCHIVED_GROUP_COLLAPSE_STORAGE_KEY));
  const sidebarRef = useRef<HTMLElement | null>(null);
  const archiveCleanupButtonRef = useRef<HTMLButtonElement | null>(null);
  const archiveCleanupContentRef = useRef<HTMLDivElement | null>(null);
  const archivedMenuRef = useRef<HTMLDivElement | null>(null);
  const archiveUndoTimeoutRef = useRef<number | null>(null);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);
  const prevCompletionTimestampsRef = useRef(recentCompletionStartedAtBySessionId);

  useMountEffect(() => {
    return () => {
      if (archiveUndoTimeoutRef.current !== null) {
        window.clearTimeout(archiveUndoTimeoutRef.current);
      }
      if (sidebarResizeCleanupRef.current !== null) {
        sidebarResizeCleanupRef.current();
        sidebarResizeCleanupRef.current = null;
      }
    };
  });

  useMountEffect(() => {
    const syncSidebarWidth = (): void => {
      setSidebarWidth((current) => {
        const next = clampSidebarWidth(current);
        return next === current ? current : next;
      });
    };

    syncSidebarWidth();
    window.addEventListener("resize", syncSidebarWidth);
    return () => {
      window.removeEventListener("resize", syncSidebarWidth);
    };
  });

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    window.localStorage.setItem(
      ARCHIVED_GROUP_COLLAPSE_STORAGE_KEY,
      JSON.stringify(archivedCollapsedByWorkDir),
    );
  }, [archivedCollapsedByWorkDir]);

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
    if (!archiveCleanupConfirmOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent): void => {
      const target = event.target as Node;
      if (
        archiveCleanupButtonRef.current?.contains(target) ||
        archiveCleanupContentRef.current?.contains(target)
      ) {
        return;
      }
      setArchiveCleanupConfirmOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setArchiveCleanupConfirmOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [archiveCleanupConfirmOpen]);

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

  const doneGroups = useMemo(() => {
    const byWorkDir = new Map<string, SessionSummary[]>();
    for (const session of doneSessions) {
      const existing = byWorkDir.get(session.work_dir);
      if (existing !== undefined) {
        existing.push(session);
      } else {
        byWorkDir.set(session.work_dir, [session]);
      }
    }
    return Array.from(byWorkDir.entries())
      .map(([work_dir, sessions]) => ({ work_dir, sessions }))
      .sort((a, b) => a.work_dir.localeCompare(b.work_dir));
  }, [doneSessions]);

  // Auto-expand collapsed "Done" groups when a session inside them completes
  useEffect(() => {
    const prev = prevCompletionTimestampsRef.current;
    prevCompletionTimestampsRef.current = recentCompletionStartedAtBySessionId;

    for (const group of doneGroups) {
      if (!(collapsedByWorkDir[group.work_dir] ?? false)) continue;

      for (const session of group.sessions) {
        const ts = recentCompletionStartedAtBySessionId[session.id];
        if (ts !== undefined && prev[session.id] !== ts) {
          toggleGroup(group.work_dir);
          break;
        }
      }
    }
  }, [recentCompletionStartedAtBySessionId, doneGroups, collapsedByWorkDir, toggleGroup]);

  const archiveCleanupEligibleCount = useMemo(() => {
    const cutoff = Date.now() / 1000 - ARCHIVE_CLEANUP_AGE_SECONDS;
    return activeSessions.filter((session) => {
      const diffSummary = session.file_change_summary;
      const hasNoDiff = diffSummary.diff_lines_added === 0 && diffSummary.diff_lines_removed === 0;
      return session.updated_at < cutoff || hasNoDiff;
    }).length;
  }, [activeSessions]);

  const archiveCleanupTooltip = useMemo(() => {
    if (archiveCleanupPending) {
      return "Archiving sessions older than 3 days or with no diff";
    }
    if (archiveCleanupEligibleCount === 0) {
      return "No sessions older than 3 days or with no diff";
    }
    return `Archive ${archiveCleanupEligibleCount} sessions older than 3 days or with no diff`;
  }, [archiveCleanupEligibleCount, archiveCleanupPending]);

  const openNewSessionOverlay = (workDir?: string): void => {
    const normalizedWorkDir = workDir?.trim() ?? "";
    setDraftWorkDir(normalizedWorkDir);
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

  const handleArchiveCleanup = (): void => {
    if (archiveCleanupPending || archiveCleanupEligibleCount === 0) {
      return;
    }

    setArchiveCleanupConfirmOpen(true);
  };

  const handleConfirmArchiveCleanup = (): void => {
    void (async () => {
      setArchiveCleanupConfirmOpen(false);
      setArchiveCleanupPending(true);
      try {
        await archiveCleanupSessions();
      } finally {
        setArchiveCleanupPending(false);
      }
    })();
  };

  const archiveCleanupButtonClassName = `inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-neutral-400 transition-colors ${archiveCleanupEligibleCount === 0 || archiveCleanupPending ? "cursor-default opacity-50" : "cursor-pointer hover:bg-muted hover:text-neutral-600"}`;

  return (
    // grid-template-columns trick (same as CollapseGroupBlock's grid-template-rows):
    // outer div controls the animated visible width; aside stays at fixed sidebarWidth
    // so internal layout (justify-center etc.) is unaffected during the animation.
    <div
      className={`grid h-full min-h-0 ${isResizing ? "transition-none" : "transition-[grid-template-columns,opacity] duration-200 ease-in-out"}`}
      style={{
        gridTemplateColumns: sidebarOpen ? `${sidebarWidth}px` : "0px",
        opacity: sidebarOpen ? 1 : 0,
      }}
    >
      <div
        className={`h-full min-h-0 ${archivedMenuOpen ? "overflow-visible" : "overflow-hidden"}`}
      >
        <aside
          ref={sidebarRef}
          data-sidebar="left"
          className={`relative flex h-full min-h-0 shrink-0 flex-col border-r border-neutral-200 bg-sidebar ${archivedMenuOpen ? "z-50" : ""}`}
          style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
        >
          {/* header floats above scroll area */}
          <div className="absolute left-0 right-0 top-0 z-40">
            {/* blur + fade: opaque over button row, fades to transparent 2rem below */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-[5rem] bg-[hsl(var(--sidebar))]/80 backdrop-blur-sm [-webkit-mask-image:linear-gradient(to_bottom,black_0,black_3rem,transparent_5rem)] [mask-image:linear-gradient(to_bottom,black_0,black_3rem,transparent_5rem)]"
            />
            <div className="relative flex items-center gap-1.5 px-3 py-2">
              <div className="min-w-0 flex-1">
                <NewSessionButton
                  onClick={() => {
                    openNewSessionOverlay();
                  }}
                />
              </div>
              {archiveCleanupConfirmOpen ? (
                <button
                  ref={archiveCleanupButtonRef}
                  type="button"
                  className={archiveCleanupButtonClassName}
                  onClick={handleArchiveCleanup}
                  aria-label="Archive stale sessions"
                  aria-disabled={archiveCleanupEligibleCount === 0 || archiveCleanupPending}
                >
                  {archiveCleanupPending ? (
                    <Loader className="h-4 w-4 animate-spin" />
                  ) : (
                    <BrushCleaning className="h-4 w-4" />
                  )}
                </button>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      ref={archiveCleanupButtonRef}
                      type="button"
                      className={archiveCleanupButtonClassName}
                      onClick={handleArchiveCleanup}
                      aria-label="Archive stale sessions"
                      aria-disabled={archiveCleanupEligibleCount === 0 || archiveCleanupPending}
                    >
                      {archiveCleanupPending ? (
                        <Loader className="h-4 w-4 animate-spin" />
                      ) : (
                        <BrushCleaning className="h-4 w-4" />
                      )}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>{archiveCleanupTooltip}</TooltipContent>
                </Tooltip>
              )}
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
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
                    <span className="inline-flex whitespace-pre text-sm leading-none">
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
              {archiveCleanupConfirmOpen ? (
                <div
                  ref={archiveCleanupContentRef}
                  className="absolute right-3 top-full z-40 mt-2 w-56 rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 shadow-sm"
                >
                  <div className="space-y-2">
                    <div className="text-sm font-medium text-neutral-800">
                      Archive {archiveCleanupEligibleCount} sessions?
                    </div>
                    <div className="text-sm text-neutral-500">
                      Archive sessions older than 3 days or with no diff.
                    </div>
                    <div className="flex justify-end gap-1.5">
                      <button
                        type="button"
                        className="rounded-md px-2 py-1 text-sm text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                        onClick={() => {
                          setArchiveCleanupConfirmOpen(false);
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm font-medium text-neutral-700 transition-colors hover:bg-muted hover:text-neutral-900"
                        onClick={handleConfirmArchiveCleanup}
                      >
                        Archive
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <ScrollArea className="min-h-0 w-full flex-1" type="auto">
            {/* pt-14 reserves space so top content isn't hidden behind the floating header */}
            <div className="px-2.5 pb-14 pt-14">
              {loadError !== null ? (
                <div className="mt-3 rounded-lg border border-dashed border-neutral-300 bg-white p-3">
                  <div className="mb-1 font-semibold">Load failed</div>
                  <div className="break-words text-base text-neutral-500">{loadError}</div>
                  <button
                    type="button"
                    className="mt-2 cursor-pointer rounded-md border border-neutral-300 bg-white px-2.5 py-1.5 text-base"
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
                  <Loader className="h-4 w-4 animate-spin text-neutral-500" />
                  <span className="text-sm font-semibold">Loading…</span>
                </div>
              ) : null}

              {loadError === null && !loading && groups.length === 0 ? (
                <div className="px-2 py-2 text-neutral-500">
                  <div className="text-sm font-semibold">No sessions yet</div>
                  <div className="mt-0.5 text-xs">Click "New Agent" above to start</div>
                </div>
              ) : null}

              <div className="space-y-4 pt-2">
                {inProgressSessions.length > 0 ? (
                  <div>
                    <div className="mb-2 px-1.5">
                      <span className="inline-flex items-center rounded-full border border-blue-200/70 bg-blue-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.08em] text-blue-700">
                        <span>In Progress</span>
                        <span className="ml-2 border-l border-blue-200/80 pl-2 text-blue-600">
                          {inProgressSessions.length}
                        </span>
                      </span>
                    </div>
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
                          completionAnimationStartedAt={
                            recentCompletionStartedAtBySessionId[session.id]
                          }
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
                  </div>
                ) : null}

                {doneGroups.length > 0 ? (
                  <div>
                    <div className="mb-2 px-1.5">
                      <span className="inline-flex items-center rounded-full border border-emerald-200/70 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.08em] text-emerald-700">
                        <span>DONE</span>
                        <span className="ml-2 border-l border-emerald-200/80 pl-2 text-emerald-600">
                          {doneSessions.length}
                        </span>
                      </span>
                    </div>
                    {doneGroups.map((group) => (
                      <ProjectGroup
                        key={group.work_dir}
                        workDir={group.work_dir}
                        sessions={group.sessions}
                        collapsed={collapsedByWorkDir[group.work_dir] ?? false}
                        activeSessionId={activeSessionId}
                        runtimeBySessionId={runtimeBySessionId}
                        recentCompletionStartedAtBySessionId={recentCompletionStartedAtBySessionId}
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
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </ScrollArea>

          <div className="absolute bottom-0 left-0 right-0 z-40">
            {/* blur + fade: opaque over button row, fades to transparent 2rem above */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 bottom-0 h-[5rem] bg-[hsl(var(--sidebar))]/80 backdrop-blur-sm [-webkit-mask-image:linear-gradient(to_top,black_0,black_3rem,transparent_5rem)] [mask-image:linear-gradient(to_top,black_0,black_3rem,transparent_5rem)]"
            />
            <div ref={archivedMenuRef} className="relative px-3 py-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
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
                <div className="absolute bottom-full left-0 z-40 mb-2 w-[380px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-neutral-200/80 bg-white p-1 shadow-[0_8px_30px_rgba(0,0,0,0.08)]">
                  <div className="flex items-center justify-between border-b border-neutral-100 px-2 py-1.5">
                    <span className="text-xs font-medium uppercase tracking-[0.08em] text-neutral-500">
                      Archived
                    </span>
                    <span className="text-xs text-neutral-500">{archivedSessionCount}</span>
                  </div>
                  {archivedGroups.length > 0 ? (
                    <ScrollArea className="w-full" viewportClassName="max-h-80" type="auto">
                      <div className="pt-1">
                        {archivedGroups.map((group) => (
                          <ProjectGroup
                            key={`archived-${group.work_dir}`}
                            workDir={group.work_dir}
                            sessions={group.sessions}
                            collapsed={archivedCollapsedByWorkDir[group.work_dir] ?? true}
                            compactSessions
                            hideNewSessionButton
                            activeSessionId={activeSessionId}
                            runtimeBySessionId={runtimeBySessionId}
                            recentCompletionStartedAtBySessionId={
                              recentCompletionStartedAtBySessionId
                            }
                            completedUnreadBySessionId={completedUnreadBySessionId}
                            onToggle={() => {
                              setArchivedCollapsedByWorkDir((prev) => ({
                                ...prev,
                                [group.work_dir]: !(prev[group.work_dir] ?? true),
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
                    <div className="px-3 py-3 text-sm text-neutral-500">No archived sessions</div>
                  )}
                </div>
              ) : null}
            </div>
          </div>

          {archiveUndoSessionId !== null ? (
            <div className="pointer-events-none absolute inset-x-2 bottom-2 z-40">
              <div className="pointer-events-auto flex items-center justify-between gap-2 rounded-lg border border-neutral-200 bg-white/95 px-2.5 py-2 shadow-[0_8px_24px_-16px_rgba(15,15,15,0.35)] backdrop-blur">
                <span className="text-sm text-neutral-700">Session archived</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-neutral-600 transition-colors hover:bg-muted hover:text-neutral-900"
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
              setIsResizing(true);
              const startX = event.clientX;
              const startWidth = sidebarWidth;
              const onPointerMove = (moveEvent: PointerEvent): void => {
                const deltaX = moveEvent.clientX - startX;
                setSidebarWidth(clampSidebarWidth(startWidth + deltaX));
              };
              const onPointerUp = (): void => {
                setIsResizing(false);
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
      </div>
    </div>
  );
}
