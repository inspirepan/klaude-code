import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, BrushCleaning, PanelLeftClose } from "lucide-react";
import { NewSessionButton } from "./NewSessionButton";
import { ProjectGroup } from "./ProjectGroup";
import { SessionSearch } from "./SessionSearch";
import { useSessionStore } from "@/stores/session-store";
import type { SessionSummary } from "@/types/session";
import { useAppStore } from "@/stores/app-store";
import { useMountEffect } from "@/hooks/useMountEffect";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

const ARCHIVE_CLEANUP_AGE_SECONDS = 1 * 24 * 60 * 60;
const ARCHIVED_GROUP_COLLAPSE_STORAGE_KEY = "klaude:left-sidebar:archived-collapsed-groups";

function readStoredCollapsedByWorkDir(storageKey: string): Record<string, boolean> {
  const raw = window.localStorage.getItem(storageKey);
  if (raw === null) return {};

  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return {};

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

export function LeftSidebar(): React.JSX.Element {
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
  const { sidebarWidth, isResizing, handleResizePointerDown } = useSidebarResize();
  const [archivedMenuOpen, setArchivedMenuOpen] = useState(false);
  const [archiveUndoSessionId, setArchiveUndoSessionId] = useState<string | null>(null);
  const [archiveCleanupConfirmOpen, setArchiveCleanupConfirmOpen] = useState(false);
  const [archiveCleanupPending, setArchiveCleanupPending] = useState(false);
  const [searchPopupOpen, setSearchPopupOpen] = useState(false);
  const [archivedCollapsedByWorkDir, setArchivedCollapsedByWorkDir] = useState<
    Record<string, boolean>
  >(() => readStoredCollapsedByWorkDir(ARCHIVED_GROUP_COLLAPSE_STORAGE_KEY));
  const sidebarRef = useRef<HTMLElement | null>(null);
  const archiveCleanupButtonRef = useRef<HTMLButtonElement | null>(null);
  const archiveCleanupContentRef = useRef<HTMLDivElement | null>(null);
  const archivedMenuRef = useRef<HTMLDivElement | null>(null);
  const archiveUndoTimeoutRef = useRef<number | null>(null);
  const prevCompletionTimestampsRef = useRef(recentCompletionStartedAtBySessionId);
  const t = useT();

  useMountEffect(() => {
    return () => {
      if (archiveUndoTimeoutRef.current !== null) {
        window.clearTimeout(archiveUndoTimeoutRef.current);
      }
    };
  });

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
        .filter((session) => !session.archived && session.messages_count > 0)
        .sort((a, b) => b.updated_at - a.updated_at),
    [groups],
  );

  const activeGroups = useMemo(() => {
    const byWorkDir = new Map<string, SessionSummary[]>();
    for (const session of activeSessions) {
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
  }, [activeSessions]);

  // Auto-expand collapsed groups when a session inside them completes
  useEffect(() => {
    const prev = prevCompletionTimestampsRef.current;
    prevCompletionTimestampsRef.current = recentCompletionStartedAtBySessionId;

    for (const group of activeGroups) {
      if (!(collapsedByWorkDir[group.work_dir] ?? false)) continue;

      for (const session of group.sessions) {
        if (
          session.id in recentCompletionStartedAtBySessionId &&
          prev[session.id] !== recentCompletionStartedAtBySessionId[session.id]
        ) {
          toggleGroup(group.work_dir);
          break;
        }
      }
    }
  }, [recentCompletionStartedAtBySessionId, activeGroups, collapsedByWorkDir, toggleGroup]);

  const archiveCleanupEligibleSessions = useMemo(() => {
    const cutoff = Date.now() / 1000 - ARCHIVE_CLEANUP_AGE_SECONDS;
    return activeSessions.filter((session) => {
      const runtime = runtimeBySessionId[session.id];
      if (runtime !== undefined && runtime.sessionState !== "idle") {
        return false;
      }
      const diffSummary = session.file_change_summary;
      const hasNoDiff = diffSummary.diff_lines_added === 0 && diffSummary.diff_lines_removed === 0;
      return session.updated_at < cutoff || hasNoDiff;
    });
  }, [activeSessions, runtimeBySessionId]);

  const archiveCleanupEligibleCount = archiveCleanupEligibleSessions.length;

  const archiveCleanupTooltip = useMemo(() => {
    if (archiveCleanupPending) {
      return t("archiveCleanup.archiving");
    }
    if (archiveCleanupEligibleCount === 0) {
      return t("archiveCleanup.noEligible");
    }
    return t("archiveCleanup.tooltip")(archiveCleanupEligibleCount);
  }, [archiveCleanupEligibleCount, archiveCleanupPending, t]);

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
        await archiveCleanupSessions(ARCHIVE_CLEANUP_AGE_SECONDS);
      } finally {
        setArchiveCleanupPending(false);
      }
    })();
  };

  const handleSearchSelect = useCallback(
    (sessionId: string, archived: boolean, workDir: string) => {
      if (archived) {
        // Open archive popup and expand the group containing this session
        setArchivedMenuOpen(true);
        setArchivedCollapsedByWorkDir((prev) => ({ ...prev, [workDir]: false }));
      } else {
        // Expand the group if collapsed
        if (collapsedByWorkDir[workDir]) {
          toggleGroup(workDir);
        }
      }
      setNewSessionOverlayOpen(false);
      void selectSession(sessionId);
    },
    [collapsedByWorkDir, toggleGroup, selectSession, setNewSessionOverlayOpen],
  );

  const archiveCleanupButtonClassName = `inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-neutral-500 transition-colors ${archiveCleanupEligibleCount === 0 || archiveCleanupPending ? "cursor-default opacity-50" : "cursor-pointer hover:bg-muted hover:text-neutral-700"}`;

  return (
    // Outer div controls the animated visible width; aside stays at fixed sidebarWidth
    // so internal layout is unaffected during the animation.
    <div
      className={`grid h-full min-h-0 ${isResizing ? "transition-none" : "transition-[grid-template-columns,opacity] duration-200 ease-in-out"}`}
      style={{
        gridTemplateColumns: sidebarOpen ? `${sidebarWidth}px` : "0px",
        opacity: sidebarOpen ? 1 : 0,
      }}
    >
      <div
        className={`h-full min-h-0 ${archivedMenuOpen || archiveCleanupConfirmOpen || searchPopupOpen ? "overflow-visible" : "overflow-hidden"}`}
      >
        <aside
          ref={sidebarRef}
          data-sidebar="left"
          className={`relative flex h-full min-h-0 shrink-0 flex-col border-r border-border bg-sidebar ${archivedMenuOpen || archiveCleanupConfirmOpen || searchPopupOpen ? "z-50" : ""}`}
          style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
        >
          {/* header floats above scroll area */}
          <div className="absolute left-0 right-0 top-0 z-40">
            {/* blur + fade: opaque over button row, short fade below */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-[3.75rem] bg-[hsl(var(--sidebar))]/80 backdrop-blur-sm [-webkit-mask-image:linear-gradient(to_bottom,black_0,black_3rem,transparent_3.75rem)] [mask-image:linear-gradient(to_bottom,black_0,black_3rem,transparent_3.75rem)]"
            />
            <div className="relative flex items-center gap-1.5 px-3 py-2">
              <div className="min-w-0 flex-1">
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
                    className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                    onClick={() => {
                      setSidebarOpen(false);
                    }}
                    aria-label={t("sidebar.collapseSidebar")}
                  >
                    <PanelLeftClose className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="flex items-center gap-1.5">
                  <span>{t("sidebar.collapseSidebar")}</span>
                  <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
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
            </div>
          </div>

          <ScrollArea className="min-h-0 w-full flex-1" type="auto">
            {/* pt-14 reserves space so top content isn't hidden behind the floating header */}
            <div className="px-2.5 pb-14 pt-14">
              {loadError !== null ? (
                <div className="mt-3 rounded-lg border border-dashed border-neutral-300 bg-card p-3">
                  <div className="mb-1 font-semibold">{t("sidebar.loadFailed")}</div>
                  <div className="break-words text-sm text-neutral-500">{loadError}</div>
                  <button
                    type="button"
                    className="mt-2 cursor-pointer rounded-md border border-neutral-300 bg-card px-2.5 py-1.5 text-sm"
                    onClick={() => {
                      void refreshSessions();
                    }}
                  >
                    {t("sidebar.clickToRetry")}
                  </button>
                </div>
              ) : null}

              {loadError === null && loading && groups.length === 0 ? (
                <div className="px-2 py-2">
                  <span className="text-shimmer text-sm font-semibold">{t("sidebar.loading")}</span>
                </div>
              ) : null}

              {loadError === null && !loading && groups.length === 0 ? (
                <div className="px-2 py-2 text-neutral-500">
                  <div className="text-sm font-semibold">{t("sidebar.noSessions")}</div>
                  <div className="mt-0.5 text-xs">{t("sidebar.noSessionsHint")}</div>
                </div>
              ) : null}

              <div className="space-y-0.5 pt-1">
                {activeGroups.map((group) => (
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
                    onToggleArchive={handleToggleArchive}
                  />
                ))}
              </div>
            </div>
          </ScrollArea>

          <div className="absolute bottom-0 left-0 right-0 z-40">
            {/* blur + fade: opaque over button row, short fade above */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 bottom-0 h-[3.75rem] bg-[hsl(var(--sidebar))]/80 backdrop-blur-sm [-webkit-mask-image:linear-gradient(to_top,black_0,black_3rem,transparent_3.75rem)] [mask-image:linear-gradient(to_top,black_0,black_3rem,transparent_3.75rem)]"
            />
            <div ref={archivedMenuRef} className="relative flex items-center gap-1 px-3 py-2">
              <SessionSearch
                onSelectSession={handleSearchSelect}
                onOpenChange={setSearchPopupOpen}
                onBeforeOpen={() => {
                  setArchivedMenuOpen(false);
                }}
              />
              {archiveCleanupConfirmOpen ? (
                <button
                  ref={archiveCleanupButtonRef}
                  type="button"
                  className={archiveCleanupButtonClassName}
                  onClick={handleArchiveCleanup}
                  aria-label={t("sidebar.archiveStale")}
                  aria-disabled={archiveCleanupEligibleCount === 0 || archiveCleanupPending}
                >
                  <BrushCleaning
                    className={cn("h-4 w-4", archiveCleanupPending && "animate-pulse")}
                  />
                </button>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      ref={archiveCleanupButtonRef}
                      type="button"
                      className={archiveCleanupButtonClassName}
                      onClick={handleArchiveCleanup}
                      aria-label={t("sidebar.archiveStale")}
                      aria-disabled={archiveCleanupEligibleCount === 0 || archiveCleanupPending}
                    >
                      <BrushCleaning
                        className={cn("h-4 w-4", archiveCleanupPending && "animate-pulse")}
                      />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>{archiveCleanupTooltip}</TooltipContent>
                </Tooltip>
              )}
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                    onClick={() => {
                      setArchivedMenuOpen((prev) => !prev);
                    }}
                    aria-label={t("sidebar.archivedSessions")}
                  >
                    <Archive className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>{t("sidebar.archivedSessions")}</TooltipContent>
              </Tooltip>

              {archivedMenuOpen ? (
                <div className="absolute bottom-full left-0 z-40 mb-2 w-[380px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg bg-card p-1 shadow-float-lg ring-1 ring-black/[0.06]">
                  <div className="flex items-center justify-between border-b border-neutral-100 px-2 py-1.5">
                    <span className="font-mono text-xs font-medium uppercase tracking-wider text-neutral-500">
                      {t("sidebar.archived")}
                    </span>
                    <span className="text-xs text-neutral-500">{archivedSessionCount}</span>
                  </div>
                  {archivedGroups.length > 0 ? (
                    <ScrollArea className="w-full" viewportClassName="max-h-[40rem]" type="auto">
                      <div className="pt-1">
                        {archivedGroups.map((group) => (
                          <ProjectGroup
                            key={`archived-${group.work_dir}`}
                            workDir={group.work_dir}
                            sessions={group.sessions}
                            collapsed={archivedCollapsedByWorkDir[group.work_dir] ?? true}
                            hideNewSessionButton
                            activeSessionId={activeSessionId}
                            runtimeBySessionId={runtimeBySessionId}
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
                            onToggleArchive={handleToggleArchive}
                          />
                        ))}
                      </div>
                    </ScrollArea>
                  ) : (
                    <div className="px-3 py-3 text-sm text-neutral-500">
                      {t("sidebar.noArchivedSessions")}
                    </div>
                  )}
                </div>
              ) : null}
              {archiveCleanupConfirmOpen ? (
                <div
                  ref={archiveCleanupContentRef}
                  className="absolute bottom-full left-3 z-40 mb-2 w-72 rounded-md bg-card px-3 py-2 text-sm text-neutral-700 shadow-sm ring-1 ring-black/[0.06]"
                >
                  <div className="space-y-2">
                    <div className="text-sm font-medium text-neutral-800">
                      {t("archiveCleanup.confirmTitle")(archiveCleanupEligibleCount)}
                    </div>
                    <div className="text-sm text-neutral-500">
                      {t("archiveCleanup.confirmDesc")}
                    </div>
                    <ScrollArea className="w-full" viewportClassName="max-h-40" type="auto">
                      <ul className="text-xs text-neutral-500">
                        {archiveCleanupEligibleSessions.map((session) => (
                          <li key={session.id} className="truncate py-0.5">
                            {session.title?.trim() ||
                              session.user_messages[0]?.trim() ||
                              t("sidebar.newSession")}
                          </li>
                        ))}
                      </ul>
                    </ScrollArea>
                    <div className="flex justify-end gap-1.5">
                      <button
                        type="button"
                        className="rounded-md px-2 py-1 text-sm text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                        onClick={() => {
                          setArchiveCleanupConfirmOpen(false);
                        }}
                      >
                        {t("archiveCleanup.cancel")}
                      </button>
                      <button
                        type="button"
                        className="rounded-md border border-border bg-card px-2 py-1 text-sm font-medium text-neutral-700 transition-colors hover:bg-muted hover:text-neutral-900"
                        onClick={handleConfirmArchiveCleanup}
                      >
                        {t("archiveCleanup.archive")}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {archiveUndoSessionId !== null ? (
            <div className="pointer-events-none absolute inset-x-2 bottom-2 z-40">
              <div className="pointer-events-auto flex items-center justify-between gap-2 rounded-lg bg-card/95 px-2.5 py-2 shadow-toast ring-1 ring-black/[0.06] backdrop-blur">
                <span className="text-sm text-neutral-700">{t("sidebar.sessionArchived")}</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-neutral-600 transition-colors hover:bg-muted hover:text-neutral-900"
                      onClick={() => {
                        const sessionId = archiveUndoSessionId;
                        dismissArchiveUndoToast();
                        void setSessionArchived(sessionId, false);
                      }}
                    >
                      {t("sidebar.undo")}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>{t("sidebar.undoArchive")}</TooltipContent>
                </Tooltip>
              </div>
            </div>
          ) : null}

          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("sidebar.resizeSidebar")}
            className="absolute -right-1 top-0 z-30 flex h-full w-2 cursor-col-resize items-center justify-center"
            onPointerDown={handleResizePointerDown}
          >
            <span className="h-full w-px bg-neutral-200/85" />
          </div>
        </aside>
      </div>
    </div>
  );
}
